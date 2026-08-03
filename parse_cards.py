#!/usr/bin/env python3
"""
parse_cards.py — Parse Riva Hotel door-lock card-read PDFs into structured JSON.

Each room PDF (e.g. cardreads/13072026/101.pdf) is an OpenDoor lock dump holding
the last ~200 door events, newest first. Columns (by x position):

    record#  |  card-id  |  card type      | holder     | ... | event date/time (right)
             |           | (İç Kol/Master  | (name or   |     |
             |           |  Kart/Misafir   | Bilinmiyor)|     |
             |           |  Kartı)         |            |     |
    Misafir (guest) rows ALSO carry the card's encoded ISO timestamp in a middle column.

The right-hand column ("Açık süre") is the lock's real chronological event log — the
actual moment the door opened. That is what we use as the entry time.

Timezone: the locks record ~2h ahead of Turkish local time (recorded 16:00 == local
14:00). We subtract LOCK_OFFSET_HOURS to get local wall-clock time.
"""
import subprocess, re, json, sys, os, glob
from datetime import datetime, timedelta

LOCK_OFFSET_HOURS = 2  # local = recorded - 2h

# x-position bands (points) derived from the PDFs
X_CARDID   = (55, 105)
X_TYPE     = (105, 172)
X_HOLDER   = (172, 240)
X_MID_DT   = (168, 225)   # guest-card encoded ISO timestamp column
X_RIGHT_DT = (505, 565)   # real event date/time column

DATE_DDMMYYYY = re.compile(r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$')
TIME_HMS      = re.compile(r'^(\d{2}):(\d{2}):(\d{2})$')
DATE_ISO      = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')
HEXID         = re.compile(r'^[0-9A-Fa-f]{8}$')


def _words_by_page(path):
    xml = subprocess.run(["pdftotext", "-bbox-layout", path, "-"],
                         capture_output=True, text=True).stdout
    pages = re.split(r'<page ', xml)[1:]
    out = []
    for pg in pages:
        ws = []
        for m in re.finditer(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>', pg):
            ws.append((float(m[1]), float(m[2]), float(m[3]), float(m[4]), m[5]))
        out.append(ws)
    return out


def _band(x, band):
    return band[0] <= x < band[1]


def _cluster_rows(words, tol=4.0):
    """Group words into rows by y (a text row). Returns list of (y, [words]) sorted top->bottom."""
    rows = []
    for w in sorted(words, key=lambda w: w[1]):
        placed = False
        for r in rows:
            if abs(r[0] - w[1]) <= tol:
                r[1].append(w); placed = True; break
        if not placed:
            rows.append([w[1], [w]])
    return sorted(rows, key=lambda r: r[0])


ROW_PITCH = 22.68


def parse_room(path):
    """Parse one room PDF into a list of door events, newest first.

    Each record occupies a band of ~22.68pt: the row text sits at the band top,
    the event time ~+5pt below it and the event date ~+17pt below it. We anchor on
    the record-number token at the far left, then bucket every other token into the
    record band it falls in. This is exact -- no overlapping y-windows.
    """
    room = os.path.splitext(os.path.basename(path))[0]
    events = []
    for ws in _words_by_page(path):
        # Anchor rows on the far-left record-number tokens.
        anchors = sorted(
            (y0, int(t)) for x0, y0, x1, y1, t in ws
            if x0 < 55 and re.fullmatch(r'\d{1,3}', t)
        )
        if not anchors:
            continue
        ys = [a[0] for a in anchors]
        buckets = {a[1]: [] for a in anchors}
        order = [a[1] for a in anchors]
        # The date/time cell is vertically centred on its row: date sits ~5pt ABOVE the
        # row text, time ~5pt BELOW it. So assign every token to its NEAREST anchor,
        # within half a row pitch. A forward-only scan would mis-pair each row with the
        # following row's date.
        for w in ws:
            y0 = w[1]
            i = min(range(len(ys)), key=lambda k: abs(ys[k] - y0))
            if abs(ys[i] - y0) >= ROW_PITCH / 2:
                continue  # header/footer token, belongs to no record
            buckets[order[i]].append(w)

        for rec in order:
            cardid = None
            ctype_tokens, holder_tokens = [], []
            rdate = rtime = midiso_d = midiso_t = None
            for x0, y0, x1, y1, t in sorted(buckets[rec], key=lambda w: (w[1], w[0])):
                if _band(x0, X_CARDID) and (HEXID.match(t) or re.fullmatch(r'\d{8}', t)):
                    cardid = t
                elif _band(x0, X_TYPE):
                    ctype_tokens.append(t)
                elif _band(x0, X_MID_DT) and DATE_ISO.match(t):
                    midiso_d = t
                elif _band(x0, X_MID_DT) and TIME_HMS.match(t):
                    midiso_t = t
                elif _band(x0, X_HOLDER):
                    holder_tokens.append(t)
                if _band(x0, X_RIGHT_DT):
                    if DATE_DDMMYYYY.match(t):
                        rdate = t
                    elif TIME_HMS.match(t):
                        rtime = t
            if cardid is None:
                continue
            typ_join = " ".join(ctype_tokens)
            if "Misafir" in typ_join:
                ctype = "guest"
            elif "Master" in typ_join:
                ctype = "master"
            elif "Kol" in typ_join or "İç" in typ_join:
                ctype = "inner"
            else:
                ctype = "other"
            holder = " ".join(h for h in holder_tokens
                              if not DATE_ISO.match(h) and not TIME_HMS.match(h)).strip()
            events.append(dict(room=room, rec=rec, card_id=cardid, type=ctype,
                               holder=holder, r_date=rdate, r_time=rtime,
                               issue_date=midiso_d, issue_time=midiso_t))

    # De-dupe by record number (rows can repeat across a page break); keep the first seen.
    seen = {}
    for e in events:
        seen.setdefault(e["rec"], e)
    events = [seen[k] for k in sorted(seen)]
    for e in events:
        # The exporter prints an empty time for midnight events. Verified across the
        # whole fleet: every date-without-time row is bracketed by neighbours spanning
        # 00:00 (e.g. previous 23:52 -> this row -> next 00:38), so the time is 00:00:00.
        e["time_inferred"] = bool(e["r_date"] and not e["r_time"])
        if e["time_inferred"]:
            e["r_time"] = "00:00:00"
        e["event_local"] = _to_local(e["r_date"], e["r_time"])
        e["event_recorded"] = _fmt(e["r_date"], e["r_time"])
        e["issue_local"] = (_iso_to_local(e["issue_date"], e["issue_time"])
                            if e["issue_date"] and e["issue_time"] else None)
    return events


def _fmt(d, t):
    if not d or not t:
        return None
    dd, mm, yy = DATE_DDMMYYYY.match(d).groups()
    return f"{yy}-{int(mm):02d}-{int(dd):02d} {t}"


def _iso_to_local(d, t):
    """Convert a card's encoded ISO timestamp (yyyy-mm-dd + HH:MM:SS) to local time."""
    try:
        dt = datetime(int(d[0:4]), int(d[5:7]), int(d[8:10]),
                      int(t[0:2]), int(t[3:5]), int(t[6:8]))
    except (ValueError, TypeError):
        return None
    return (dt - timedelta(hours=LOCK_OFFSET_HOURS)).strftime("%Y-%m-%d %H:%M:%S")


def _to_local(d, t):
    if not d or not t:
        return None
    dd, mm, yy = DATE_DDMMYYYY.match(d).groups()
    try:
        dt = datetime(int(yy), int(mm), int(dd),
                      int(t[0:2]), int(t[3:5]), int(t[6:8]))
    except ValueError:
        return None
    dt -= timedelta(hours=LOCK_OFFSET_HOURS)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    folder = sys.argv[1] if len(sys.argv) > 1 else "cardreads/13072026"
    if os.path.isfile(folder):
        files = [folder]
    else:
        files = sorted(glob.glob(os.path.join(folder, "*.pdf")))
    all_rooms = {}
    for f in files:
        evs = parse_room(f)
        room = os.path.splitext(os.path.basename(f))[0]
        all_rooms[room] = evs
        guests = [e for e in evs if e["type"] == "guest"]
        print(f"{room}: {len(evs)} events, {len(guests)} guest-card reads")
    out = sys.argv[2] if len(sys.argv) > 2 else "cards.json"
    with open(out, "w") as fh:
        json.dump(all_rooms, fh, ensure_ascii=False, indent=1)
    print(f"-> wrote {out}")
