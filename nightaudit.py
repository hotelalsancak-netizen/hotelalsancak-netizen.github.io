#!/usr/bin/env python3
"""
nightaudit.py — one combined "gün sonu hazırlık" (night-audit readiness) report.

Run this once before closing the day. It pulls the whole active hotel and answers,
in a single page: is it safe to take gün sonu, or is something unfinished?

PILLARS
  💰 Payments   — walkouts, in-house guest debts, agency receivables (from audit.py)
  🚪 Arrivals   — expected guests past arrival time still 'Rezervasyon' (not checked
                  in / not no-showed)
  🛎️ Departures — still 'InHouse' past their checkout date (overstay or status error)
  🏷️ Rate       — live real-room reservations sold at 0 / no price (revenue leak)
  🪪 KBS        — NOT YET AUTOMATED. The hotel has KBS configured, but per-guest
                  "reported to police?" status is not in the reservation view; it
                  needs a discovery pass on the guest-level object. Shown as unknown
                  rather than faked, so a green report never implies KBS is done.

Each pillar is ✅ / ⚠️. The header verdict is "hazır" only if every automated pillar
is clean (KBS is always called out as not-checked).

Usage:
    python3 nightaudit.py                 # today's close: departures=yesterday, live now
    python3 nightaudit.py --date 2026-07-15
    python3 nightaudit.py --days 3 --open
Exit: 0 ready · 1 something needs attention · 2 the check failed
"""
import argparse, datetime as dt, sys
from pathlib import Path

import paycheck as pc
import audit

REPORTS = Path("reports")


def is_virtual_folio(r):
    """BOARD FOLIO / CASH FOLIO and the like are accounting containers, not sold
    rooms: their ROOMNO is 'T'+resid (non-numeric) and the guest name says FOLIO."""
    room = str(r.get("room") or "")
    guest = str(r.get("guest") or "").upper()
    return (not room.isdigit()) or ("FOLIO" in guest)


def parse_dt(s):
    try:
        return dt.datetime.fromisoformat(str(s)[:19])
    except (ValueError, TypeError):
        return None


def not_checked_in(rows, now):
    """Expected today/earlier, still 'Rezervasyon' — never arrived or never no-showed."""
    out = []
    for r in rows:
        ci = parse_dt(r.get("checkin"))
        if str(r.get("durum")) == "Reservation" and ci and ci <= now:
            out.append(dict(r, _age=max(0, (now.date() - ci.date()).days)))
    return sorted(out, key=lambda r: r.get("checkin") or "")


def overstays(inhouse, today):
    """Still in-house though their checkout date has passed."""
    out = []
    for r in inhouse:
        co = parse_dt(r.get("checkout"))
        if co and co.date() < today:
            out.append(dict(r, _age=(today - co.date()).days))
    return sorted(out, key=lambda r: -r["_age"])


def zero_rate(rows):
    """In-house real-room reservations sold at 0 / no price — a guest currently
    staying with no room charge, which is a revenue leak. Restricted to InHouse on
    purpose: a future 'Rezervasyon' can legitimately be mid-entry, and a past
    CheckOut is history, so both would add noise to a can-we-close-tonight check.
    Virtual folios (BOARD/CASH FOLIO) are accounting containers, not rooms."""
    out, seen = [], set()
    for r in rows:
        if r.get("durum") != "InHouse" or is_virtual_folio(r):
            continue
        rid = r.get("rez_id")
        if rid in seen:
            continue
        tp = pc.parse_money(r.get("toplam"))
        if tp is None or abs(tp) < 0.005:
            seen.add(rid)
            out.append(r)
    return out


def dedup(rows):
    by_id, out = set(), []
    for r in rows:
        rid = r.get("rez_id")
        if rid in by_id:
            continue
        by_id.add(rid)
        out.append(r)
    return out


# ---- rendering -------------------------------------------------------------
EXTRA_CSS = """
.pillars{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:.6rem;margin:0 0 1.5rem}
.pill{border:1px solid #e3e5e9;border-radius:10px;padding:.7rem .85rem;background:#fff}
.pill .lbl{font-size:.8rem;color:#666;display:flex;align-items:center;gap:.35rem}
.pill .val{font-size:1.15rem;font-weight:700;margin-top:.25rem}
.pill.ok .val{color:#0f5132}.pill.warn .val{color:#c0392b}.pill.unknown .val{color:#8a6d1a}
.pill.warn{border-color:#f0a9a9}.pill.ok{border-color:#a3d9b6}.pill.unknown{border-color:#e8c66a}
@media(prefers-color-scheme:dark){
 .pill{background:#1b1e24;border-color:#2c313a}
 .pill.ok .val{color:#8fe0ad}.pill.warn .val{color:#ff8080}.pill.unknown .val{color:#f2d089}
 .pill .lbl{color:#8a909b}
}
.risk{display:flex;flex-wrap:wrap;gap:1.2rem;padding:.9rem 1.1rem;margin:0 0 1.25rem;
 border:1px solid #f0a9a9;border-radius:10px;background:#fdeaea}
.risk .item{font-size:.95rem;color:#8a1c1c}.risk .amt{font-weight:800;font-size:1.15rem}
.clean-line{padding:.5rem .8rem;margin:.35rem 0;border-radius:8px;background:#eef7f0;
 color:#0f5132;font-size:.9rem;border:1px solid #cfe8d6}
.act{font-weight:600}
.sig{margin-top:2rem;padding-top:1rem;border-top:2px solid #d0d3d8;display:flex;
 flex-wrap:wrap;gap:2.5rem;font-size:.9rem;color:#333}
.sig div{min-width:180px}.sig .ln{border-bottom:1px solid #999;height:1.6rem;margin-top:.2rem}
.noprint{margin:0 0 1rem}
button.print{font:inherit;padding:.45rem .9rem;border:1px solid #b9bec6;border-radius:8px;
 background:#fff;cursor:pointer}
@media(prefers-color-scheme:dark){
 .risk{background:#3a1518;border-color:#6d2529}.risk .item{color:#ffb3b3}
 .clean-line{background:#12301f;color:#8fe0ad;border-color:#215c39}
 .sig{color:#c7ccd4;border-color:#3a3f48}.sig .ln{border-color:#666}
 button.print{background:#20242b;color:#e7e9ee;border-color:#3a3f48}
}
@media print{
 .noprint{display:none}
 body{padding:0}.pillars{display:none}
 a[href]:after{content:""}
 *{-webkit-print-color-adjust:exact;print-color-adjust:exact}
 .scroll{overflow:visible;border:none}
 h2{page-break-after:avoid}tr{page-break-inside:avoid}
}
"""

# Every flagged row gets a plain-language instruction. Keyed by section.
ACTIONS = {
    "walkout": "Misafire ulaş, tahsil et",
    "inhouse_owes": "Resepsiyonda tahsil et",
    "not_checked_in": "Giriş yap ya da no-show işaretle",
    "overstays": "Uzatma gir ya da çıkışı yap",
    "zero_rate": "Fiyatı kontrol et / gir",
    "receivable": "Acentadan tahsilat — takip",
}

BASE_COLS = [("room", "Oda"), ("guest", "Misafir"), ("agency", "Acenta"),
             ("checkin", "Geliş"), ("checkout", "Ayrılış"), ("durum", "Durum")]


def detail_table(rows, kind, action):
    """One table per section. `kind` picks the money columns:
       money      guest / agency / net balance (payment sections)
       money_age  + Yaş (agency receivables)
       age        Yaş only (arrivals / departures status)
       amount     Toplam (zero-rate)
    Every row ends with a 'Ne yapmalı?' action cell so a receptionist knows the step."""
    cols = list(BASE_COLS)
    extra_head = ""
    if kind in ("money", "money_age"):
        extra_head += "<th style='text-align:right'>Misafir</th><th style='text-align:right'>Acenta</th>"
    if kind == "money_age":
        extra_head += "<th style='text-align:right'>Yaş</th>"
    if kind == "age":
        extra_head += "<th style='text-align:right'>Yaş</th>"
    if kind == "amount":
        extra_head += "<th style='text-align:right'>Toplam</th>"
    extra_head += "<th style='text-align:right'>Genel Bakiye</th>" if kind in ("money", "money_age") else ""
    head = "".join(f"<th>{lbl}</th>" for _, lbl in cols) + extra_head + "<th>Ne yapmalı?</th><th>Rez Id</th>"

    body = []
    for r in rows:
        tds = ""
        for k, _ in cols:
            v = r.get(k)
            tds += f"<td>{pc.fmt_dt(v) if k in pc.DATE_COLS else (v if v is not None else '')}</td>"
        cur = "₺"   # balances are converted to TL upstream (audit.money)
        if kind in ("money", "money_age"):
            tds += (f"<td class='num'>{pc.fmt_money(r.get('_guest', 0))}</td>"
                    f"<td class='num'>{pc.fmt_money(r.get('_agency', 0))}</td>")
        if kind in ("money_age", "age"):
            tds += f"<td class='num'>{r.get('_age', '')}g</td>"
        if kind == "amount":
            mv = pc.parse_money(r.get("toplam"))
            tds += f"<td class='num'>{pc.fmt_money(mv) if mv is not None else '—'} {cur}</td>"
        if kind in ("money", "money_age"):
            tds += f"<td class='num owed'>{pc.fmt_money(r.get('_balance', 0))} {cur}</td>"
        tds += f"<td class='act'>{action}</td><td>{r.get('rez_id') or ''}</td>"
        body.append(f"<tr>{tds}</tr>")
    return (f"<div class='scroll'><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def pill(label, icon, count, state):
    val = "temiz" if (state == "ok" and count == 0) else (str(count) if count is not None else "?")
    return f"<div class='pill {state}'><div class='lbl'>{icon} {label}</div><div class='val'>{val}</div></div>"


# Section order = priority. Guest-owed money first, then operational, receivables last.
SECTIONS = [
    ("walkout",        "💰", "Çıkış yaptı, hâlâ borçlu", "money",
     "Misafir ayrıldı ve net bakiye kaldı — asıl kaçak budur."),
    ("inhouse_owes",   "💰", "İçeride, borçlu", "money",
     "Hâlâ konaklıyor ve misafir hesabında bakiye var."),
    ("not_checked_in", "🚪", "Giriş bekleyen (hâlâ 'Rezervasyon')", "age",
     "Geliş saati geçmiş ama giriş yapılmamış."),
    ("overstays",      "🛎️", "Çıkış gecikmiş (hâlâ 'İçeride')", "age",
     "Ayrılış tarihi geçmiş ama hâlâ içeride — uzatma yoksa gece ücreti kaybolur."),
    ("zero_rate",      "🏷️", "Sıfır / eksik fiyat", "amount",
     "Konaklayan gerçek-oda 0 fiyatla — çoğu zaman girilmemiş fiyat, gelir kaçağı."),
    ("receivable",     "📄", "Acenta alacakları (acil değil)", "money_age",
     "Net bakiyeyi acenta borçlu; sonradan ödenir, takip edin."),
]


def risk_summary(data):
    """Prominent top line: total guest-owed money at risk, per currency."""
    urgent = data["walkout"] + data["inhouse_owes"]
    if not urgent:
        return ""
    by_cur = {}
    for r in urgent:
        by_cur["₺"] = by_cur.get("₺", 0) + r.get("_balance", 0)   # all balances now TL
    amt = " + ".join(f"<span class='amt'>{pc.fmt_money(v)} {c}</span>"
                     for c, v in sorted(by_cur.items()))
    return (f"<div class='risk'><div class='item'>Misafir kaynaklı açık: "
            f"<strong>{len(urgent)}</strong> rezervasyon · {amt}</div></div>")


def render(date, data, meta):
    urgent_n = len(data["walkout"]) + len(data["inhouse_owes"])
    automated_warn = urgent_n + len(data["not_checked_in"]) + len(data["overstays"]) + len(data["zero_rate"])

    checks = [
        ("Ödeme (misafir)", "💰", urgent_n, "warn" if urgent_n else "ok"),
        ("Giriş bekleyen", "🚪", len(data["not_checked_in"]), "warn" if data["not_checked_in"] else "ok"),
        ("Çıkış gecikmiş", "🛎️", len(data["overstays"]), "warn" if data["overstays"] else "ok"),
        ("Sıfır fiyat", "🏷️", len(data["zero_rate"]), "warn" if data["zero_rate"] else "ok"),
        ("KBS", "🪪", None, "unknown"),
    ]
    if automated_warn:
        banner = ("dirty", "⚠️ Gün sonundan önce çözülmesi gerekenler var — aşağıdaki "
                           "kırmızı bölümlere bakın.")
    else:
        banner = ("clean", "✅ Otomatik kontroller temiz — gün sonu alınabilir. "
                           "(KBS elle kontrol edilmeli.)")

    pills = "".join(pill(l, i, c, s) for l, i, c, s in checks)
    parts = [f"<div class='verdict {banner[0]}'>{banner[1]}</div>",
             risk_summary(data),
             f"<div class='pillars'>{pills}</div>"]

    # Only expand sections that have something. Clean sections collapse to one line,
    # so a night receptionist scrolls past nothing that needs no action.
    clean = []
    for key, icon, title, kind, note in SECTIONS:
        rows = data[key]
        if not rows:
            clean.append(f"{icon} {title}")
            continue
        parts.append(f"<h2>{icon} {title} <span class='n'>({len(rows)})</span></h2>"
                     f"<p class='note'>{note}</p>"
                     + detail_table(rows, kind, ACTIONS[key]))
    if clean:
        parts.append("".join(f"<div class='clean-line'>✓ {c} — temiz</div>" for c in clean))

    # KBS — always shown as a manual step, never faked clean.
    parts.append("<h2>🪪 KBS — kimlik bildirim <span class='n'>(otomatik değil)</span></h2>"
                 "<p class='note'>Otelde KBS tanımlı, ama her misafirin polise bildirilip "
                 "bildirilmediği rezervasyon verisinde yok. Bu rapor KBS'yi "
                 "<strong>kontrol etmez</strong>; elle bakın.</p>")

    sign = ("<div class='sig'>"
            "<div>Kontrol eden<div class='ln'></div></div>"
            "<div>İmza<div class='ln'></div></div>"
            "<div>Saat<div class='ln'></div></div></div>")

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive">
<title>Riva gün sonu hazırlık {date}</title><style>{pc.CSS}{EXTRA_CSS}</style></head>
<body><div class="wrap">
<div class="noprint"><button class="print" onclick="window.print()">🖨 Yazdır</button></div>
<h1>Riva Hotel Alsancak — gün sonu hazırlık</h1>
<p class="sub">Çıkışlar <strong>{date}</strong> · içeridekiler anlık ·
{meta['checkouts']} çıkış + {meta['inhouse']} içeride + {meta['expected']} giriş tarandı ·
oluşturulma {meta['generated']}</p>
{''.join(p for p in parts if p)}
{sign}
<footer>Otomatik kontroller: ödeme (net Genel Bakiye), giriş/çıkış durumu, fiyat.
KBS otomatik DEĞİL. Kaynak: ElektraWeb QA_HOTEL_RESERVATION. rivacheck/nightaudit.py</footer>
</div></body></html>"""


def generate(date=None, days=1, env=None, reports_dir=None):
    """Fetch, analyse, and write the gün-sonu report. Shared by the CLI and the
    Windows app. Returns a summary dict. Raises on any fetch/login failure — the
    caller decides how to surface it, and a failure never reads as 'all clear'.

    env: optional pre-built credentials dict (the GUI passes one instead of a file).
    """
    today = dt.date.today()
    now = dt.datetime.now()
    date = date or (today - dt.timedelta(days=1)).isoformat()
    reports = Path(reports_dir) if reports_dir else REPORTS

    from elektra_api import fetch_departed_range, fetch_inhouse, fetch_arrivals
    frm = (dt.date.fromisoformat(date) - dt.timedelta(days=days - 1)).isoformat()
    checkouts = fetch_departed_range(frm, date, env=env)
    inhouse = fetch_inhouse(env=env)
    expected = dedup(fetch_arrivals(today.isoformat(), env=env) + fetch_arrivals(date, env=env))

    cats = audit.categorise(checkouts + inhouse, today)
    # Biggest amounts first within each money section (walkout/inhouse already are).
    cats["receivable"].sort(key=lambda r: -r.get("_balance", 0))
    data = {
        "walkout": cats["walkout"], "inhouse_owes": cats["inhouse_owes"],
        "receivable": cats["receivable"],
        "not_checked_in": not_checked_in(expected, now),
        "overstays": overstays(inhouse, today),
        "zero_rate": zero_rate(inhouse),
    }
    reports.mkdir(parents=True, exist_ok=True)
    meta = {"checkouts": len(checkouts), "inhouse": len(inhouse), "expected": len(expected),
            "generated": now.strftime("%d.%m.%Y %H:%M")}
    out = reports / f"nightaudit-{date}.html"
    out.write_text(render(date, data, meta), encoding="utf-8")

    counts = {k: len(data[k]) for k in
              ("walkout", "inhouse_owes", "receivable", "not_checked_in", "overstays", "zero_rate")}
    counts["guest_urgent"] = counts["walkout"] + counts["inhouse_owes"]
    counts["needs_attention"] = (counts["guest_urgent"] + counts["not_checked_in"]
                                 + counts["overstays"] + counts["zero_rate"])
    return {"date": date, "path": out, "counts": counts, "data": data, "meta": meta}


def main():
    ap = argparse.ArgumentParser(description="combined gün-sonu readiness report")
    ap.add_argument("--date", help="checkout date (default: yesterday)")
    ap.add_argument("--days", type=int, default=1, help="days of checkouts to sweep")
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()

    try:
        res = generate(a.date, a.days)
    except Exception as e:
        print(f"KONTROL BAŞARISIZ / CHECK FAILED: {e}", file=sys.stderr)
        return 2

    c = res["counts"]
    print(f"{res['date']}: ödeme(misafir)={c['guest_urgent']} giriş-bekleyen={c['not_checked_in']} "
          f"çıkış-gecikmiş={c['overstays']} sıfır-fiyat={c['zero_rate']} "
          f"acenta-alacak={c['receivable']} | KBS: otomatik değil")
    print(f"-> {res['path']}")
    if a.open:
        import webbrowser
        webbrowser.open(res["path"].resolve().as_uri())
    return 1 if c["needs_attention"] else 0


if __name__ == "__main__":
    sys.exit(main())
