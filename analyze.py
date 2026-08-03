#!/usr/bin/env python3
"""
analyze.py — Cross-check door-lock guest-card reads against the ElektraWeb calendar.

THE RULE (from hotel management):
  A hotel night D runs from check-in 14:00 on D to check-out 12:00 on D+1 (local).
  For each room R and night D:
    * calendar says R was occupied for night D            -> nothing to check
    * calendar says R was empty, and no guest card opened
      the door during the night                           -> fine, room unused
    * calendar says R was empty but a "Misafir Kartı"
      (guest card) opened the door in that window         -> SUSPICIOUS

Master/personnel cards and İç Kol (inside handle) events are NOT evidence of a sale —
housekeeping and staff legitimately enter empty rooms. Only guest cards count.

WHY WE REPLAY ROOM CHANGES
  The calendar files a reservation under the room it ENDED in. When a guest occupies
  a room for a few hours and is then moved, the first room's nights disappear from the
  calendar entirely — the room reads as "never sold" even though a paying guest slept
  in it. Two real cases we hit (guest names / reservation ids removed):
     * Guest A — calendar room is literally NULL; their nights in 303 exist only in the
       Oda Değişimi report (303 -> 304).
     * Guest B — calendar says 112, but they were first in 303, then 102, then 112.
  So we rebuild each reservation's true room timeline: check-in -> change -> change ->
  check-out, and mark a room occupied for every night its segment overlaps. Skipping
  this produced 14 "suspicious" nights, most of which were simply moved guests.

TIMEZONE: lock timestamps are ~2h ahead of Turkish local and are already converted to
local by parse_cards.py. ElektraWeb times (changes, reservations) are already local.
"""
import json, sys, os
from collections import defaultdict
from datetime import datetime, timedelta, date

CHECKIN_H = 14   # 14:00 local
CHECKOUT_H = 12  # 12:00 local


def load_json(p):
    with open(p) as fh:
        return json.load(fh)


def parse_dt(s):
    s = str(s)
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S") if len(s) > 16 else \
           datetime.strptime(s, "%Y-%m-%d %H:%M")


def norm_id(s):
    """'12.345.678' and 12345678 are the same reservation (dots stripped)."""
    return str(s or "").replace(".", "").strip()


def night_window(d):
    """(start, end) local datetimes for hotel night d."""
    return (datetime.combine(d, datetime.min.time()) + timedelta(hours=CHECKIN_H),
            datetime.combine(d + timedelta(days=1), datetime.min.time()) + timedelta(hours=CHECKOUT_H))


def dedupe_reads(reads):
    """Collapse low-battery triple-logs. A weak lock (Düşük voltaj) re-logs the same
    swipe two or three times with an identical card id and identical recorded second
    (verified live: three consecutive records at the same HH:MM:SS second, same card id). Same
    card + same second == one physical door opening. Distinct swipes differ by at least
    a minute, so this never merges two real entries."""
    seen, out = set(), []
    for e in sorted(reads, key=lambda e: e["event_local"]):
        key = (e["card_id"], e["event_recorded"])
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def night_of(t):
    """Which hotel night a timestamp belongs to. 12:00-14:00 belongs to neither."""
    for off in (0, -1):
        d = (t + timedelta(days=off)).date()
        ws, we = night_window(d)
        if ws <= t < we:
            return d
    return None


def room_segments(res, changes_by_rez):
    """Yield (start, end, room) — everywhere this reservation's guest may have been.

    Before the first recorded change the guest is in that change's from_room; after
    each change they are in its to_room. With no changes they simply stay put.

    This is deliberately a UNION of evidence, not a single reconstruction. The two
    sources genuinely disagree sometimes, because a room can be reassigned by editing
    the reservation instead of via the Oda Değişimi function — that move leaves no
    change record. Real example (guest name / id removed): a reservation had changes
    411 -> 414 -> 411, yet the calendar files it in 235 — and 235's lock shows six
    guest reads that night, so 235 is where they actually slept. Trusting the chain
    alone invented a "suspicious" night for 235. So we also credit the calendar's room
    for the tail of the stay: an unrecorded move must never manufacture an accusation.
    """
    ci = datetime.strptime(res["checkin"], "%Y-%m-%d") + timedelta(hours=CHECKIN_H)
    co = datetime.strptime(res["checkout"], "%Y-%m-%d") + timedelta(hours=CHECKOUT_H)
    cs = changes_by_rez.get(norm_id(res["rez_id"]), [])
    if not cs:
        yield (ci, co, str(res["room"]))
        return
    yield (ci, parse_dt(cs[0]["when"]), str(cs[0]["from_room"]))
    for i, c in enumerate(cs):
        start = parse_dt(c["when"])
        end = parse_dt(cs[i + 1]["when"]) if i + 1 < len(cs) else co
        if end > start:
            yield (start, end, str(c["to_room"]))
    # The calendar is authoritative for where the reservation ENDED.
    last = parse_dt(cs[-1]["when"])
    if co > last:
        yield (last, co, str(res["room"]))


def build_occupancy(occ, changes):
    """room -> night -> [reservations that genuinely occupied it that night]."""
    by_rez = defaultdict(list)
    for c in changes:
        by_rez[norm_id(c["rez_id"])].append(c)
    for v in by_rez.values():
        v.sort(key=lambda c: c["when"])

    sold = defaultdict(lambda: defaultdict(list))
    for r in occ["reservations"]:
        for start, end, room in room_segments(r, by_rez):
            if not room or room in ("None", "none", ""):
                continue
            # Mark every night whose window overlaps this segment.
            d = (start - timedelta(days=1)).date()
            last = end.date() + timedelta(days=1)
            while d <= last:
                ws, we = night_window(d)
                if start < we and end > ws:      # intervals overlap
                    sold[room][d].append(r)
                d += timedelta(days=1)
    return sold


def build_blocks(occ):
    """room -> set of nights the room was blocked (TADİLAT etc). Context, not a sale."""
    blocked = defaultdict(dict)
    for b in occ.get("blocks", []):
        ci = datetime.strptime(b["checkin"], "%Y-%m-%d").date()
        co = datetime.strptime(b["checkout"], "%Y-%m-%d").date()
        # Blocks are often zero-length (checkin == checkout) or even reversed;
        # treat those as covering the single day they name.
        d, last = ci, max(co - timedelta(days=1), ci)
        while d <= last:
            blocked[b["room"]][d] = b
            d += timedelta(days=1)
    return blocked


def analyze(cards, occ, changes, start=None, end=None):
    sold = build_occupancy(occ, changes)
    blocked = build_blocks(occ)
    findings = []

    all_dates = sorted({e["event_local"][:10] for evs in cards.values()
                        for e in evs if e["event_local"]})
    lo = datetime.strptime(start or all_dates[0], "%Y-%m-%d").date()
    hi = datetime.strptime(end or all_dates[-1], "%Y-%m-%d").date()

    for room, evs in sorted(cards.items()):
        guest_reads = [e for e in evs if e["type"] == "guest" and e["event_local"]]
        by_night = defaultdict(list)
        for e in dedupe_reads(guest_reads):
            d = night_of(parse_dt(e["event_local"]))
            if d:
                by_night[d].append(e)
        d = lo
        while d <= hi:
            reads = sorted(by_night.get(d, []), key=lambda e: e["event_local"])
            if reads and not sold.get(room, {}).get(d):
                blk = blocked.get(room, {}).get(d)
                nextday = d + timedelta(days=1)
                arrives_next = bool(sold.get(room, {}).get(nextday))
                # "Early check-in" boundary: a paid guest arrives in THIS room the next
                # day, and every read is in the small hours of that arrival day, before
                # the 14:00 check-in. That is the arriving guest let in early, dated to
                # their real (paid) reservation — not an unsold room. Confirmed pattern:
                # 5 of 9 raw hits were exactly this (e.g. a room with reads at ~02:23 and
                # the paid guest arriving the next day). Keep them, but a separate benign tier so
                # nobody is sent chasing a guest who simply arrived at night.
                boundary = arrives_next and all(
                    parse_dt(e["event_local"]).date() == nextday
                    and parse_dt(e["event_local"]).hour < CHECKIN_H
                    for e in reads)
                findings.append(dict(
                    room=room, night=d.isoformat(),
                    status="EARLY_CHECKIN" if boundary else "SUSPICIOUS",
                    blocked=(blk or {}).get("guest") if blk else None,
                    next_guest=(sold.get(room, {}).get(nextday, [{}])[0].get("guest")
                                if boundary else None),
                    guest_reads=[dict(local=e["event_local"], card=e["card_id"],
                                      inferred=e.get("time_inferred", False))
                                 for e in reads],
                ))
            d += timedelta(days=1)
    return findings


if __name__ == "__main__":
    cards = load_json("cards.json")
    changes = load_json("room_changes.json")
    if not os.path.exists("occupancy.json"):
        sys.exit("occupancy.json missing — run:\n"
                 "  ./.venv/bin/python elektra_api.py --occupancy 2026-07-01 2026-07-14")
    occ = load_json("occupancy.json")
    start = sys.argv[1] if len(sys.argv) > 1 else None
    end = sys.argv[2] if len(sys.argv) > 2 else None
    f = analyze(cards, occ, changes, start, end)
    with open("findings.json", "w") as fh:
        json.dump(f, fh, ensure_ascii=False, indent=1)
    sus = [x for x in f if x["status"] == "SUSPICIOUS"]
    early = [x for x in f if x["status"] == "EARLY_CHECKIN"]
    print(f"{len(sus)} SUSPICIOUS room-nights, {len(early)} early-check-in (benign)\n")
    for x in sus:
        times = ", ".join(g["local"][11:16] for g in x["guest_reads"])
        blk = f"  [room was BLOCKED: {x['blocked']}]" if x["blocked"] else ""
        print(f"  SUSPICIOUS  ROOM {x['room']}  night {x['night']}  reads: {times}{blk}")
    for x in early:
        times = ", ".join(g["local"][11:16] for g in x["guest_reads"])
        print(f"  early-checkin  ROOM {x['room']}  night {x['night']}  reads: {times}"
              f"  (next-day guest: {x['next_guest']})")
