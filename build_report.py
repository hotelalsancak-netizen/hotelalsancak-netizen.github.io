#!/usr/bin/env python3
"""
build_report.py — render the room-usage security check as an HTML report.

Sections:
  1. Verdict summary (suspicious count).
  2. SUSPICIOUS room-nights — full evidence per case.
  3. Early-check-in room-nights — benign, shown for completeness.
  4. Room x night occupancy matrix (lock reads vs. calendar), mirroring the Oda Planı.

Occupancy comes from occupancy.json (ElektraWeb FN_ROOMCALENDAR_BASIC) with room
changes replayed; if it is absent the report degrades to showing lock evidence only.
"""
import json, os, html
from collections import defaultdict
from datetime import timedelta, datetime, date

from analyze import (night_window, parse_dt, build_occupancy, build_blocks,
                     dedupe_reads, night_of, analyze, norm_id)

LO = date(2026, 7, 6)
HI = date(2026, 7, 12)


TR_DAY = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
TR_DAY_FULL = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def tr_short(d):
    return TR_DAY[d.weekday()]


def tr_long(d):
    return f'{d.strftime("%d.%m.%Y")} {TR_DAY_FULL[d.weekday()]}'


def daterange(lo, hi):
    d = lo
    while d <= hi:
        yield d
        d += timedelta(days=1)


def collect(cards, lo=LO, hi=HI):
    grid = defaultdict(lambda: defaultdict(list))
    for room, evs in cards.items():
        gr = dedupe_reads([e for e in evs if e["type"] == "guest" and e["event_local"]])
        for e in gr:
            d = night_of(parse_dt(e["event_local"]))
            if d and lo <= d <= hi:
                grid[room][d].append(e)
    return grid


CSS = """
:root{
  --ground:#FBFAF8; --panel:#FFFFFF; --ink:#1A1D22; --muted:#6E7076;
  --line:#E4E1DB; --accent:#9C6F2B; --accent-soft:#F0E4CE;
  --clear:#2F6F4F; --clear-soft:#E4EEE7; --warn:#A8641B; --warn-soft:#F5E7D6;
  --crit:#A62B2B; --crit-soft:#F7E3E1;
  --shadow:0 1px 2px rgba(20,22,26,.06),0 1px 10px rgba(20,22,26,.04);
}
@media (prefers-color-scheme:dark){:root{
  --ground:#14161A; --panel:#1B1E23; --ink:#E9E7E3; --muted:#9A9CA2;
  --line:#2B2F36; --accent:#D9A85C; --accent-soft:#3A2E1B;
  --clear:#6FBF95; --clear-soft:#20302A; --warn:#D99B4E; --warn-soft:#33291B;
  --crit:#E8817A; --crit-soft:#3A2220; --shadow:0 1px 2px rgba(0,0,0,.45);
}}
:root[data-theme="dark"]{
  --ground:#14161A; --panel:#1B1E23; --ink:#E9E7E3; --muted:#9A9CA2;
  --line:#2B2F36; --accent:#D9A85C; --accent-soft:#3A2E1B;
  --clear:#6FBF95; --clear-soft:#20302A; --warn:#D99B4E; --warn-soft:#33291B;
  --crit:#E8817A; --crit-soft:#3A2220; --shadow:0 1px 2px rgba(0,0,0,.45);
}
:root[data-theme="light"]{
  --ground:#FBFAF8; --panel:#FFFFFF; --ink:#1A1D22; --muted:#6E7076;
  --line:#E4E1DB; --accent:#9C6F2B; --accent-soft:#F0E4CE;
  --clear:#2F6F4F; --clear-soft:#E4EEE7; --warn:#A8641B; --warn-soft:#F5E7D6;
  --crit:#A62B2B; --crit-soft:#F7E3E1; --shadow:0 1px 2px rgba(20,22,26,.06),0 1px 10px rgba(20,22,26,.04);
}
*{box-sizing:border-box}
body{margin:0;background:var(--ground);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
  font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:40px 24px 72px;
  display:flex;flex-direction:column;gap:30px}
header{display:flex;flex-direction:column;gap:6px}
.eyebrow{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--accent);font-weight:650}
h1{margin:0;font-size:30px;line-height:1.15;letter-spacing:-.02em;text-wrap:balance}
.sub{color:var(--muted);font-size:14px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:12px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:9px;
  padding:15px 17px;box-shadow:var(--shadow);display:flex;flex-direction:column;gap:3px}
.stat .n{font-size:26px;font-weight:670;letter-spacing:-.02em;font-variant-numeric:tabular-nums}
.stat .l{font-size:12px;color:var(--muted)}
.stat.bad{border-color:var(--crit);background:var(--crit-soft)}
.stat.bad .n{color:var(--crit)}
.stat.ok{border-color:var(--clear)}
.stat.ok .n{color:var(--clear)}
section{display:flex;flex-direction:column;gap:14px}
section.dim{opacity:.66}
section.dim .case.crit{border-left-color:var(--warn)}
h2.sec{margin:0;font-size:18px;letter-spacing:-.01em;display:flex;align-items:baseline;gap:10px}
h2.sec .c{font-size:13px;font-weight:500;color:var(--muted)}
.lead{margin:0;color:var(--muted);font-size:14px;max-width:70ch}
.case{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  box-shadow:var(--shadow);overflow:hidden}
.case.crit{border-left:4px solid var(--crit)}
.case.warn{border-left:4px solid var(--warn)}
.case-h{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:14px 18px;
  border-bottom:1px solid var(--line)}
.case-h .rm{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:20px;
  font-weight:680;letter-spacing:-.01em}
.case-h .nt{color:var(--muted);font-size:14px}
.spacer{flex:1}
.rc-dl{font:inherit;font-size:12px;font-weight:600;padding:4px 11px;border-radius:8px;
  border:1px solid var(--crit);background:transparent;color:var(--crit);cursor:pointer;white-space:nowrap}
.rc-dl:hover{background:var(--crit);color:#fff}
.tag{font-size:11px;font-weight:660;letter-spacing:.03em;padding:3px 10px;border-radius:99px}
.tag.crit{background:var(--crit-soft);color:var(--crit)}
.tag.warn{background:var(--warn-soft);color:var(--warn)}
.tag.str{background:var(--accent-soft);color:var(--accent)}
.case-b{padding:14px 18px;display:flex;flex-direction:column;gap:10px}
.row{display:flex;gap:10px;font-size:14px;align-items:baseline}
.row .k{color:var(--muted);min-width:120px;font-size:12.5px;text-transform:uppercase;letter-spacing:.05em}
.row .v{flex:1}
.times{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:13px;
  display:flex;flex-wrap:wrap;gap:6px}
.t{background:var(--crit-soft);color:var(--crit);padding:2px 8px;border-radius:5px;font-weight:600}
.t.eve{background:var(--warn-soft);color:var(--warn)}
.mini{display:flex;gap:2px;margin-top:2px}
.mini .d{width:34px;height:26px;border-radius:4px;border:1px solid var(--line);
  display:flex;align-items:center;justify-content:center;font-size:10px;
  font-family:ui-monospace,monospace;color:var(--muted)}
.mini .d.sold{background:var(--clear-soft);color:var(--clear);border-color:var(--clear)}
.mini .d.flag{background:var(--crit-soft);color:var(--crit);border-color:var(--crit);font-weight:700}
.scroll{overflow-x:auto;background:var(--panel);border:1px solid var(--line);
  border-radius:9px;box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap}
thead th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  font-weight:600;position:sticky;top:0;background:var(--panel)}
tbody tr:last-child td{border-bottom:none}
.room{font-family:ui-monospace,"SF Mono",Menlo,monospace;font-weight:640;font-size:13px;
  position:sticky;left:0;background:var(--panel);border-right:1px solid var(--line)}
.cell{text-align:center;font-family:ui-monospace,"SF Mono",Menlo,monospace;font-size:12px}
.cell.sold{background:var(--clear-soft);color:var(--clear)}
.cell.flag{background:var(--crit);color:#fff;font-weight:700}
.cell.early{background:var(--warn-soft);color:var(--warn)}
.cell.reads{box-shadow:inset 0 0 0 2px var(--accent)}
.cell.empty{color:var(--line)}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--muted);align-items:center}
.legend .sw{display:inline-block;width:12px;height:12px;border-radius:3px;vertical-align:-2px;margin-right:5px}
footer{color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:16px;line-height:1.7}
.actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:4px}
.btn{display:inline-flex;align-items:center;gap:8px;font:inherit;font-size:13.5px;
  font-weight:600;padding:9px 15px;border-radius:8px;border:1px solid var(--accent);
  background:var(--accent);color:#fff;cursor:pointer;box-shadow:var(--shadow);
  transition:filter .12s ease}
.btn:hover{filter:brightness(1.07)}
.btn:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.btn.ghost{background:transparent;color:var(--accent)}
.btn svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:2;
  stroke-linecap:round;stroke-linejoin:round}
@media (max-width:640px){.wrap{padding:24px 14px 48px}h1{font-size:24px}.row{flex-direction:column;gap:2px}.row .k{min-width:0}}
@media print{
  .actions{display:none !important}
  body{font-size:11.5px;background:#fff}
  .wrap{max-width:none;padding:0;gap:18px}
  .scroll{overflow:visible;box-shadow:none}
  .case,.stat{break-inside:avoid}
  section{break-inside:auto}
  @page{size:A4 landscape;margin:12mm}
}
"""


def mini_calendar(room, night, sold):
    cells = []
    for d in daterange(LO, HI):
        occ = sold.get(room, {}).get(d)
        cls = "d flag" if d.isoformat() == night else ("d sold" if occ else "d")
        cells.append(f'<div class="{cls}">{d.strftime("%d")}</div>')
    return '<div class="mini">' + "".join(cells) + '</div>'


def room_change_note(room, changes):
    """What the Oda Değişimi report holds for this room — shown so every flag is
    auditable. The covered date range is computed from the data (not hard-coded), so
    stale/partial room-change data is visible rather than silently trusted."""
    if not changes:
        return ("<b>⚠️ bu hafta için oda değişimi (Oda Değişimi raporu) yüklenmedi — "
                "kontrol EDİLEMEDİ</b>; taşınan bir misafir bu odayı açıklıyor olabilir.")
    all_dates = sorted({c["when"][:10] for c in changes if c.get("when")})
    cov = f"{all_dates[0]}–{all_dates[-1]}" if all_dates else "?"
    rows = sorted((c for c in changes if str(c.get("from_room")) == room or str(c.get("to_room")) == room),
                  key=lambda c: c.get("when", ""))
    if not rows:
        return (f"kontrol edildi — oda değişimi verisi <b>{cov}</b> arasını kapsıyor; "
                f"bu oda için kayıt yok.")
    dates = ", ".join(sorted({c["when"][:10] for c in rows}))
    reasons = sorted({(c.get("note") or "").strip() for c in rows if (c.get("note") or "").strip()})
    reason_html = ("<br><b>📝 neden (Oda Notu):</b> "
                   + " · ".join(html.escape(n) for n in reasons)) if reasons else ""
    return (f"kontrol edildi — bu oda için {len(rows)} kayıt ({dates}), "
            f"<b>hiçbiri bu geceyi kapsamıyor</b>.{reason_html}")


def case_card(f, sold, strong, changes, has_pdf=False):
    room, night = f["room"], f["night"]
    nd = datetime.strptime(night, "%Y-%m-%d").date()
    times = []
    for g in f["guest_reads"]:
        hh = int(g["local"][11:13])
        cls = "t" if 14 <= hh or hh < 6 else "t"
        eve = "" if (14 <= hh <= 23) else " eve"
        times.append(f'<span class="t{eve}">{g["local"][11:16]}</span>')
    tag = ('<span class="tag str">güçlü · gece boyu</span>' if strong
           else '<span class="tag warn">zayıf sinyal</span>')
    prev_guest = ""
    # who was the last real guest before this night, for context
    for back in range(1, 8):
        pd = nd - timedelta(days=back)
        occ = sold.get(room, {}).get(pd)
        if occ:
            prev_guest = f'{occ[0]["guest"]} ({(pd+timedelta(days=1)).strftime("%d.%m")} çıkış)'
            break
    nights_vacant = 0
    pd = nd
    while not sold.get(room, {}).get(pd) and pd >= LO - timedelta(days=10):
        nights_vacant += 1
        pd -= timedelta(days=1)
    o = [f'<div class="case crit">']
    o.append('<div class="case-h">')
    o.append(f'<span class="rm">{html.escape(room)}</span>')
    o.append(f'<span class="nt">{tr_long(nd)} gecesi</span>')
    o.append('<span class="spacer"></span>')
    o.append('<span class="tag crit">ŞÜPHELİ</span>' + tag)
    if has_pdf:
        o.append(f'<button class="rc-dl" type="button" data-room="{html.escape(room)}" '
                 f'title="Bu odanın kilit kart-okuma PDF\'ini indir">⤓ Kart PDF</button>')
    o.append('</div><div class="case-b">')
    o.append(f'<div class="row"><span class="k">Misafir kartı açılışı</span>'
             f'<span class="v"><div class="times">{"".join(times)}</div></span></div>')
    o.append(f'<div class="row"><span class="k">Oda planı</span><span class="v">oda '
             f'<b>boş</b> görünüyor — bu geceyi kapsayan rezervasyon yok'
             f'{" ("+str(nights_vacant)+" gecedir boş)" if nights_vacant>1 else ""}.</span></div>')
    o.append(f'<div class="row"><span class="k">Oda değişim raporu</span>'
             f'<span class="v">{room_change_note(room, changes)}</span></div>')
    if prev_guest:
        o.append(f'<div class="row"><span class="k">Son satılan misafir</span>'
                 f'<span class="v">{html.escape(prev_guest)}</span></div>')
    o.append(f'<div class="row"><span class="k">Hafta</span><span class="v">'
             f'{mini_calendar(room, night, sold)}</span></div>')
    o.append('</div></div>')
    return "".join(o)


def early_card(f, sold):
    room, night = f["room"], f["night"]
    nd = datetime.strptime(night, "%Y-%m-%d").date()
    times = " ".join(f'<span class="t eve">{g["local"][11:16]}</span>' for g in f["guest_reads"])
    o = [f'<div class="case warn"><div class="case-h">']
    o.append(f'<span class="rm">{html.escape(room)}</span>')
    o.append(f'<span class="nt">{nd.strftime("%d.%m.%Y")} gecesi</span>')
    o.append('<span class="spacer"></span><span class="tag warn">ERKEN GİRİŞ</span></div>')
    o.append('<div class="case-b">')
    o.append(f'<div class="row"><span class="k">Misafir kartı açılışı</span>'
             f'<span class="v"><div class="times">{times}</div></span></div>')
    o.append(f'<div class="row"><span class="k">Açıklama</span><span class="v">'
             f'{html.escape(f["next_guest"] or "ertesi gün misafiri")}, '
             f'<b>{(nd+timedelta(days=1)).strftime("%d.%m")}</b> tarihinde giriş yapıyor — '
             f'bu gece yarısı okumaları erken gelen misafire ait. Ücretli konaklama, sorun yok.'
             f'</span></div>')
    o.append('</div></div>')
    return "".join(o)


def classify_strong(sus, sold):
    """Split suspicious room-nights into STRONG (someone genuinely lived there) vs WEAK.

    STRONG when either:
      * the SAME room is flagged on consecutive nights — a continuous off-book stay
        (live example: 323 flagged six nights in a row, 21→26.07), or
      * a single night shows a real sleep pattern (a read in the small hours 00–05, or
        an evening arrival ≥19:00 together with a morning read ≤10:00) AND the room was
        NOT sold the night before — so it is not simply a paid guest lingering on their
        check-out day.
    Everything else — one lone read, an afternoon-only visit, or a read on the night
    right after a paid check-out — is WEAK: still listed, but not chased first.
    Returns the set of (room, night) that are strong.
    """
    byroom = defaultdict(set)
    for f in sus:
        byroom[f["room"]].add(datetime.strptime(f["night"], "%Y-%m-%d").date())
    strong = set()
    for f in sus:
        room = f["room"]
        nd = datetime.strptime(f["night"], "%Y-%m-%d").date()
        nights = byroom[room]
        consecutive = (nd - timedelta(days=1) in nights) or (nd + timedelta(days=1) in nights)
        hrs = [int(g["local"][11:13]) for g in f["guest_reads"]]
        slept = any(0 <= h <= 5 for h in hrs) or (any(h >= 19 for h in hrs) and any(h <= 10 for h in hrs))
        prev_sold = bool(sold.get(room, {}).get(nd - timedelta(days=1)))
        if consecutive or (slept and not prev_sold and len(f["guest_reads"]) >= 2):
            strong.add((room, f["night"]))
    return strong


def strong_runs(strong_findings):
    """Merge strong findings into continuous-stay events: [(room, first_night, nights)]."""
    byroom = defaultdict(list)
    for f in strong_findings:
        byroom[f["room"]].append(datetime.strptime(f["night"], "%Y-%m-%d").date())
    runs = []
    for room, ds in byroom.items():
        ds.sort()
        run = [ds[0]]
        for d in ds[1:]:
            if (d - run[-1]).days == 1:
                run.append(d)
            else:
                runs.append((room, run[0], len(run)))
                run = [d]
        runs.append((room, run[0], len(run)))
    runs.sort(key=lambda x: (-x[2], x[0]))
    return runs


def _suspicious_room_pdfs(sus, pdf_dir):
    """{room: base64(pdf)} for the DISTINCT suspicious rooms only (not per night, so
    a 3-night flag embeds one PDF). Lets each case card offer the raw lock read for
    that room. Kept to suspicious rooms so the report doesn't carry all 54 PDFs."""
    import base64, glob
    out = {}
    for room in sorted({f["room"] for f in sus}):
        hits = glob.glob(os.path.join(pdf_dir, "**", f"{room}.pdf"), recursive=True)
        if hits:
            try:
                with open(hits[0], "rb") as fh:
                    out[room] = base64.b64encode(fh.read()).decode()
            except OSError:
                pass
    return out


def build(cards, changes, occ, lo=LO, hi=HI, pdf_dir=None):
    grid = collect(cards, lo, hi)
    sold = build_occupancy(occ, changes)
    findings = analyze(cards, occ, changes, lo.isoformat(), hi.isoformat())
    sus = [f for f in findings if f["status"] == "SUSPICIOUS"]
    room_pdf = _suspicious_room_pdfs(sus, pdf_dir) if pdf_dir else {}
    early = [f for f in findings if f["status"] == "EARLY_CHECKIN"]
    strong_set = classify_strong(sus, sold)
    strong = sorted((f for f in sus if (f["room"], f["night"]) in strong_set),
                    key=lambda f: (f["room"], f["night"]))
    weak = sorted((f for f in sus if (f["room"], f["night"]) not in strong_set),
                  key=lambda f: (f["room"], f["night"]))
    runs = strong_runs(strong)
    strong_rooms = strong_set

    nights = list(daterange(lo, hi))
    rooms = sorted(cards.keys())
    total_reads = sum(len(v) for r in grid.values() for v in r.values())
    flagged_cells = {(f["room"], f["night"]) for f in sus}
    early_cells = {(f["room"], f["night"]) for f in early}

    o = ['<div class="wrap">']
    o.append('<header>')
    o.append('<div class="eyebrow">Riva Hotel Alsancak · Oda Kullanım Güvenlik Kontrolü</div>')
    o.append('<h1>Satılmadan kullanılan odalar</h1>')
    o.append(f'<div class="sub">Kapı kilidi kart okumaları ElektraWeb oda planı ile '
             f'karşılaştırıldı · {lo.strftime("%d.%m")}–{hi.strftime("%d.%m.%Y")} · '
             f'{len(rooms)} oda · doluluk {occ.get("fetched","")} çekildi</div>')
    o.append('<div class="actions">'
             '<button class="btn" type="button" id="riva-pdf-btn">'
             '<svg viewBox="0 0 24 24"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/>'
             '<path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>PDF indir</button>'
             '<button class="btn ghost" type="button" id="riva-zip-btn">'
             '<svg viewBox="0 0 24 24"><path d="M4 4h16v16H4z"/><path d="M10 4v4m2-4v4m-2 2v2m2-2v2"/></svg>'
             'Sorunlu oda kayıtları (ZIP)</button>'
             '</div>')
    o.append('</header>')

    # ---- Missing-lock warning: rooms Elektra shows active this week but with NO
    # card PDF in the dump were NOT checked at all (a blind spot — if one is used
    # off-book, this report can't see it). Never let a missing room pass silently.
    occ_rooms = {str(r["room"]) for r in occ.get("reservations", []) + occ.get("blocks", [])}
    missing_cards = sorted(occ_rooms - set(rooms), key=lambda x: (len(x), x))
    if missing_cards:
        o.append('<div style="background:#fef2f2;border:1px solid #fecaca;color:#991b1b;'
                 'padding:12px 16px;border-radius:10px;margin:0 0 16px;font-size:13.5px">'
                 '⚠️ <b>EKSİK KİLİT OKUMASI — kör nokta.</b> Şu oda(lar) bu hafta Elektra\'da '
                 'aktifti ama kart dökümünde YOK, yani <b>hiç kontrol edilemedi</b>: '
                 f'<b>{", ".join(html.escape(r) for r in missing_cards)}</b>. '
                 'Bu oda(lar) satılmadan kullanılsa bu rapor yakalayamaz — terminalden '
                 'eksik odaların kilidini de okutup yeniden yükleyin.</div>')

    o.append('<div class="stats">')
    o.append(f'<div class="stat bad"><div class="n">{len(strong)}</div>'
             f'<div class="l">GÜÇLÜ şüphe (oda-gecesi)</div></div>')
    o.append(f'<div class="stat"><div class="n">{len(weak)}</div>'
             f'<div class="l">zayıf sinyal (tek-tük)</div></div>')
    o.append(f'<div class="stat"><div class="n">{total_reads:,}</div>'
             f'<div class="l">incelenen misafir kartı açılışı</div></div>')
    o.append(f'<div class="stat"><div class="n">{len(occ["reservations"])}</div>'
             f'<div class="l">karşılaştırılan rezervasyon</div></div>')
    o.append('</div>')

    # ---- STRONG: continuous / real off-book stays, shown first ----
    o.append('<section>')
    o.append(f'<h2 class="sec">Güçlü şüphe <span class="c">'
             f'{len(strong)} oda-gecesi · biri gerçekten kalmış gibi</span></h2>')
    multi = [r for r in runs if r[2] >= 2]
    if multi:
        parts = ", ".join(
            f'<b>oda {html.escape(rm)} — {n} gece üst üste</b> '
            f'({d0.strftime("%d")}–{(d0+timedelta(days=n-1)).strftime("%d.%m")})'
            for rm, d0, n in multi)
        o.append(f'<p class="lead">Sürekli kalışlar (en dikkat çekici): {parts}. '
                 f'Aynı oda üst üste gecelerde boş görünüp her gece açılıyorsa, orada biri '
                 f'kaydsız kalıyor demektir.</p>')
    o.append('<p class="lead">Bu odalarda oda planı boş gösteriyor ama misafir kartı '
             '(personel Master Kartı değil) kapıyı açmış; gece boyu / sabaha karşı okuma var ve '
             'bunu açıklayan bir oda değişimi yok. Saatler Türkiye yerel saati. Otel gecesi '
             '14:00 → ertesi gün 12:00.</p>')
    for f in strong:
        o.append(case_card(f, sold, True, changes, f["room"] in room_pdf))
    o.append('</section>')

    # ---- WEAK: single reads / check-out-day lingering, listed for completeness ----
    if weak:
        o.append('<section class="dim">')
        o.append(f'<h2 class="sec">Zayıf sinyal <span class="c">'
                 f'{len(weak)} oda-gecesi · tek okuma ya da çıkış günü — eksiksizlik için</span></h2>')
        o.append('<p class="lead">Boş gecede tek bir okuma, sadece öğleden sonra bir giriş, ya da '
                 'ücretli bir misafirin çıkış günü akşamına taşan okuması. Çoğu masum olabilir; '
                 'yine de sessizce atlanmasın diye listelendi.</p>')
        for f in weak:
            o.append(case_card(f, sold, False, changes, f["room"] in room_pdf))
        o.append('</section>')

    o.append('<section>')
    o.append(f'<h2 class="sec">Erken girişler <span class="c">eksiksizlik için gösteriliyor — '
             f'şüpheli değil</span></h2>')
    o.append('<p class="lead">Burada ücretli bir misafir ertesi gün odaya giriş yapıyor ve '
             'okumalar o girişin gece yarısı saatlerinde — misafir sadece erken alınmış. Hiçbir '
             'şey sessizce atlanmasın diye listelendi.</p>')
    for f in sorted(early, key=lambda f: (f["room"], f["night"])):
        o.append(early_card(f, sold))
    o.append('</section>')

    # ---- Room changes with their reasons (from the reservation's "Oda Notu") ----
    # An uncontrolled room change is itself a leak risk, so every move this week is
    # listed with WHO did it and WHY. A change with no reason written is highlighted.
    o.append('<section>')
    o.append('<h2 class="sec">Oda değişimleri <span class="c">bu hafta yapılan taşımalar · '
             'kim, neden</span></h2>')
    if not changes:
        o.append('<p class="lead">Bu hafta oda değişimi kaydı yok (ya da yüklenmedi).</p>')
    else:
        o.append('<p class="lead">Resepsiyonun yaptığı her oda değişimi burada. Kontrolsüz '
                 'taşıma bir güvenlik açığıdır; neden, rezervasyondaki <b>Oda Notu</b>\'ndan '
                 'gelir. <b style="color:#c0392b">Nedeni yazılmamış</b> değişimler ayrıca '
                 'işaretli — bunları resepsiyona sorun.</p>')
        o.append('<div class="scroll"><table><thead><tr><th>Tarih</th><th>Misafir</th>'
                 '<th>Odadan</th><th>Odaya</th><th>Yapan</th>'
                 '<th>Neden (Oda Notu)</th></tr></thead><tbody>')
        for c in sorted(changes, key=lambda c: c.get("when", "")):
            note = (c.get("note") or "").strip()
            note_cell = (html.escape(note) if note
                         else '<span style="color:#c0392b;font-weight:600">— neden yazılmamış</span>')
            o.append(f'<tr><td>{html.escape(str(c.get("when","")))}</td>'
                     f'<td>{html.escape(c.get("guest",""))}</td>'
                     f'<td class="room">{html.escape(c.get("from_room",""))}</td>'
                     f'<td class="room">{html.escape(c.get("to_room",""))}</td>'
                     f'<td>{html.escape(c.get("user",""))}</td>'
                     f'<td>{note_cell}</td></tr>')
        o.append('</tbody></table></div>')
    o.append('</section>')

    # ---- T-folyo recovery: skip-payment guests whose real room was hidden ----
    # A guest who leaves without paying is moved to a virtual "T-folyo" room; the
    # physical room they slept in then reads as VACANT and would be false-flagged.
    # We rebuild the real room from the reservation log and credit those nights, so
    # they DON'T appear as suspicious. Shown here for transparency: the room did not
    # simply "disappear" — a genuine (unpaid) guest was there.
    tfolyo = sorted({(r["room"], r.get("guest", ""), r.get("checkin", ""), r.get("checkout", ""))
                     for r in occ.get("reservations", []) if r.get("tfolyo")})
    o.append('<section>')
    o.append('<h2 class="sec">T-folyo ile geri kazanılan konaklamalar <span class="c">'
             'ödemeden ayrılan misafirler · yanlış alarm önlendi</span></h2>')
    if not tfolyo:
        o.append('<p class="lead">Bu hafta T-folyoya alınmış (ödemesiz) konaklama bulunamadı.</p>')
    else:
        o.append('<p class="lead">Bir misafir <b>ödemeden ayrılınca</b> Elektra onu sanal bir '
                 '<b>T-folyo</b> odasına taşır; kaldığı gerçek oda o an oda planında <b>boş</b> '
                 'görünür ve normalde "satılmadan kullanıldı" diye <b>yanlış işaretlenirdi</b>. '
                 'Gerçek odayı rezervasyon <b>log</b> kaydından bulup o geceleri konaklama saydık — '
                 'bu yüzden şüpheli listesinde <b>çıkmıyorlar</b>. (Bu misafirlerin ödemesi ayrıca '
                 'takip edilmeli.)</p>')
        o.append('<div class="scroll"><table><thead><tr><th>Oda</th><th>Misafir</th>'
                 '<th>Giriş</th><th>Çıkış</th></tr></thead><tbody>')
        for room, guest, ci, co in tfolyo:
            o.append(f'<tr><td class="room">{html.escape(room)}</td>'
                     f'<td>{html.escape(guest)}</td>'
                     f'<td>{html.escape(ci)}</td><td>{html.escape(co)}</td></tr>')
        o.append('</tbody></table></div>')
    o.append('</section>')

    # Occupancy matrix
    o.append('<section>')
    o.append('<h2 class="sec">Doluluk tablosu <span class="c">kilit okumaları / oda planı, '
             'oda ve gece bazında</span></h2>')
    o.append('<div class="legend">'
             '<span><span class="sw" style="background:var(--clear-soft);border:1px solid var(--clear)"></span>satılmış (oda planı)</span>'
             '<span><span class="sw" style="background:var(--crit)"></span>ŞÜPHELİ: boş gecede okuma</span>'
             '<span><span class="sw" style="background:var(--warn-soft)"></span>erken giriş</span>'
             '<span><span class="sw" style="box-shadow:inset 0 0 0 2px var(--accent);background:transparent"></span>misafir okuması var</span>'
             '<span class="sub">sayı = o geceki kapı açılışı</span></div>')
    o.append('<div class="scroll"><table><thead><tr><th>Oda</th>')
    for d in nights:
        o.append(f'<th style="text-align:center">{d.strftime("%d.%m")}<br>'
                 f'<span style="font-weight:400;text-transform:none">{tr_short(d)}</span></th>')
    o.append('</tr></thead><tbody>')
    for room in rooms:
        o.append(f'<tr><td class="room">{html.escape(room)}</td>')
        for d in nights:
            reads = grid.get(room, {}).get(d, [])
            is_sold = bool(sold.get(room, {}).get(d))
            key = (room, d.isoformat())
            n = len(reads)
            if key in flagged_cells:
                cls, txt = "cell flag", str(n)
            elif key in early_cells:
                cls, txt = "cell early", str(n)
            elif is_sold and reads:
                cls, txt = "cell sold reads", str(n)
            elif is_sold:
                cls, txt = "cell sold", "·"
            elif reads:
                cls, txt = "cell reads", str(n)
            else:
                cls, txt = "cell empty", "·"
            tip = ""
            if reads:
                tip = f'{n} misafir açılışı: ' + ", ".join(g["event_local"][11:16] for g in reads)
            o.append(f'<td class="{cls}" title="{html.escape(tip)}">{txt}</td>')
        o.append('</tr>')
    o.append('</tbody></table></div></section>')

    o.append('<footer>'
             f'{len(rooms)} kapı kilidi PDF dökümü ve ElektraWeb oda planından '
             f'(FN_ROOMCALENDAR_BASIC, {len(occ["reservations"])} rezervasyon) oluşturuldu; '
             f'{len(changes)} satırlık Oda Değişimi raporu yeniden işlenerek taşınan her misafir '
             'gerçekte kaldığı odaya sayıldı. <b>Yalnızca Misafir Kartı okumaları sayılır</b> — '
             'Master Kart (personel) ve İç Kol (iç kol) hariç, çünkü kat hizmetleri boş odalara '
             'meşru şekilde girer. Zayıf pilli kilitlerin aynı geçişi iki-üç kez kaydetmesi '
             'tekilleştirildi. Rezervasyon durumu 2 (TADİLAT / bakım blokları) satılmış değil, '
             f'dolu değil sayılır. Hafta: {lo.strftime("%d.%m")}–{hi.strftime("%d.%m.%Y")}.</footer>')
    o.append('</div>')
    o.append(DOWNLOAD_JS)
    if room_pdf:
        o.append("<script>const RIVA_ROOM_PDF=" + json.dumps(room_pdf) + ";"
                 "document.querySelectorAll('.rc-dl').forEach(function(b){"
                 "b.addEventListener('click',function(){"
                 "var r=b.getAttribute('data-room'),d=RIVA_ROOM_PDF[r];"
                 "if(!d){alert('Bu oda için PDF gömülü değil.');return;}"
                 "rivaSave(rivaB64ToBlob(d,'application/pdf'),'oda-'+r+'-kart-okuma.pdf');"
                 "});});</script>")
    return ("<title>Riva Hotel — Satılmadan kullanılan odalar</title>\n"
            f"<style>{CSS}</style>\n" + "\n".join(o))


# The two big base64 payloads are injected by package_report.py in place of the
# __PDF_B64__ / __ZIP_B64__ tokens. Kept out of build_report so this stays fast to
# re-run; the buttons say so if the report was built without packaging.
DOWNLOAD_JS = """<script>
const RIVA_PDF_B64 = "__PDF_B64__";
const RIVA_ZIP_B64 = "__ZIP_B64__";
const RIVA_PDF_NAME = "Riva_Oda_Kullanim_06-12_Temmuz_2026.pdf";
const RIVA_ZIP_NAME = "Riva_Sorunlu_Odalar_06-12_Temmuz_2026.zip";
function rivaB64ToBlob(b64, type){
  const bin = atob(b64), len = bin.length, arr = new Uint8Array(len);
  for (let i = 0; i < len; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], {type});
}
function rivaSave(blob, name){
  try{
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = name; a.rel = "noopener";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  }catch(e){
    alert("İndirme bu görünümde engellendi olabilir. Raporu tam sekmede açıp tekrar deneyin.");
  }
}
function rivaReady(b64){ return b64 && b64.indexOf("__") !== 0; }
function rivaDownloadPdf(){
  if(!rivaReady(RIVA_PDF_B64)){
    // Not packaged — fall back to the browser's own print-to-PDF.
    window.print(); return;
  }
  rivaSave(rivaB64ToBlob(RIVA_PDF_B64, "application/pdf"), RIVA_PDF_NAME);
}
function rivaDownloadZip(){
  if(!rivaReady(RIVA_ZIP_B64)){
    alert("ZIP paketi bu raporda gömülü değil. build_report.py sonrası package_report.py çalıştırın.");
    return;
  }
  rivaSave(rivaB64ToBlob(RIVA_ZIP_B64, "application/zip"), RIVA_ZIP_NAME);
}
// Attach via addEventListener, NOT inline onclick — the artifact CSP blocks inline
// event-handler attributes, which silently made the buttons do nothing.
(function(){
  var p = document.getElementById("riva-pdf-btn");
  var z = document.getElementById("riva-zip-btn");
  if (p) p.addEventListener("click", rivaDownloadPdf);
  if (z) z.addEventListener("click", rivaDownloadZip);
})();
</script>"""


if __name__ == "__main__":
    cards = json.load(open("cards.json"))
    changes = json.load(open("room_changes.json"))
    if not os.path.exists("occupancy.json"):
        raise SystemExit("occupancy.json missing — run elektra_api.py --occupancy first")
    occ = json.load(open("occupancy.json"))
    out = build(cards, changes, occ)
    with open("report.html", "w") as fh:
        fh.write(out)
    print(f"wrote report.html ({len(out):,} bytes)")
