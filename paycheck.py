#!/usr/bin/env python3
"""
paycheck.py — "did every guest who arrived yesterday actually pay?"

Replaces the manual routine: open the ElektraWeb reservation grid, switch to the
"Günlük Kontrol" column layout, filter Geliş = yesterday, and eyeball the
Genel Bakiye column for red (positive) numbers.

THE RULE (from hotel management):
    Genel Bakiye > 0  ->  money is still owed  ->  FLAG
    Genel Bakiye <= 0 ->  paid, or a credit balance -> fine

Cancelled/deleted reservations are reported in a separate section rather than
mixed in with live ones: a positive balance on a deleted booking is a different
kind of problem (usually a posting left behind) and shouldn't be chased at the
reception desk the same way.

Usage:
    python3 paycheck.py                      # yesterday, live fetch from Elektra
    python3 paycheck.py --date 2026-07-14    # a specific arrival date
    python3 paycheck.py --from-json rows.json  # offline, from a saved fetch
"""
import argparse, datetime as dt, json, pathlib, re, sys

REPORTS = pathlib.Path("reports")

# A balance at or below this (in the row's own currency) is treated as paid.
# 0.0 means "any positive balance is a flag", including 0,59 rounding crumbs.
DEFAULT_TOLERANCE = 0.0

CANCELLED_STATES = {"deleted", "iptal", "cancelled", "noshow", "no show"}


def parse_money(v):
    """Turkish-formatted money -> float.  '192.825,85' -> 192825.85, '' -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("+-").replace(".", "").replace(",", ".")
    try:
        f = float(s)
    except ValueError:
        return None
    return -f if neg else f


def is_cancelled(row):
    return str(row.get("durum") or "").strip().lower() in CANCELLED_STATES


def classify(rows, tolerance=DEFAULT_TOLERANCE):
    """Split rows into unpaid / unpaid-but-cancelled / credit / ok."""
    out = {"unpaid": [], "cancelled_unpaid": [], "credit": [], "ok": [], "no_balance": []}
    for r in rows:
        bal = parse_money(r.get("genel_bakiye"))
        r = dict(r, _balance=bal)
        if bal is None:
            out["no_balance"].append(r)
        elif bal > tolerance:
            out["cancelled_unpaid" if is_cancelled(r) else "unpaid"].append(r)
        elif bal < 0:
            out["credit"].append(r)
        else:
            out["ok"].append(r)
    for k in ("unpaid", "cancelled_unpaid"):
        out[k].sort(key=lambda r: -r["_balance"])
    out["credit"].sort(key=lambda r: r["_balance"])
    return out


def fmt_dt(v):
    """'2026-07-14 14:00:00.000' -> '14.07.2026 14:00'. Midnight loses the time,
    since 00:00 is how Elektra records a date with no meaningful clock time."""
    if not v:
        return ""
    s = str(v)
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?", s)
    if not m:
        return s
    y, mo, d, hh, mm = m.groups()
    out = f"{d}.{mo}.{y}"
    if hh and (hh, mm) != ("00", "00"):
        out += f" {hh}:{mm}"
    return out


def fmt_money(f):
    if f is None:
        return "—"
    s = f"{abs(f):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" if f < 0 else "") + s


def totals_by_currency(rows):
    """Sum balances per currency.  Never add TRY to EUR — the hotel bills in both."""
    tot = {}
    for r in rows:
        tot[r.get("currency") or "?"] = tot.get(r.get("currency") or "?", 0) + r["_balance"]
    return tot


def fmt_totals(rows):
    return " + ".join(f"{fmt_money(v)} {c}" for c, v in sorted(totals_by_currency(rows).items()))


CSS = """
:root{color-scheme:light dark}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem;font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
     background:#f6f7f9;color:#16181d}
.wrap{max-width:1100px;margin:0 auto}
h1{font-size:1.5rem;margin:0 0 .25rem}
.sub{color:#666;margin:0 0 1.5rem;font-size:.9rem}
.verdict{padding:1rem 1.25rem;border-radius:10px;font-weight:600;margin:0 0 1.5rem;font-size:1.05rem}
.verdict.clean{background:#e7f6ec;color:#0f5132;border:1px solid #a3d9b6}
.verdict.dirty{background:#fdeaea;color:#8a1c1c;border:1px solid #f0a9a9}
.verdict.partial{background:#fff6e0;color:#7a4f00;border:1px solid #e8c66a}
.caveat{padding:.85rem 1.1rem;border-radius:8px;margin:0 0 1rem;font-size:.9rem;
        background:#fff6e0;color:#7a4f00;border:1px solid #e8c66a}
h2{font-size:1.05rem;margin:1.75rem 0 .5rem}
h2 .n{color:#888;font-weight:400}
.scroll{overflow-x:auto;border:1px solid #e3e5e9;border-radius:10px;background:#fff}
table{border-collapse:collapse;width:100%;font-size:.875rem}
th,td{padding:.55rem .7rem;text-align:left;border-bottom:1px solid #eceef1;white-space:nowrap}
th{background:#fafbfc;font-weight:600;font-size:.8rem;color:#555}
tr:last-child td{border-bottom:0}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.owed{color:#c0392b;font-weight:700}
.cred{color:#1a7f4b}
.tag{display:inline-block;padding:.1rem .45rem;border-radius:4px;background:#eef0f3;font-size:.75rem}
.note{color:#666;font-size:.85rem;margin:.4rem 0 0}
footer{margin-top:2.5rem;color:#999;font-size:.8rem;border-top:1px solid #e3e5e9;padding-top:1rem}
@media(prefers-color-scheme:dark){
 body{background:#14161a;color:#e7e9ee}
 .scroll{background:#1b1e24;border-color:#2c313a}
 th{background:#20242b;color:#aab}
 th,td{border-color:#282d35}
 .verdict.clean{background:#12301f;color:#8fe0ad;border-color:#215c39}
 .verdict.dirty{background:#3a1518;color:#ffb3b3;border-color:#6d2529}
 .sub,.note,footer{color:#8a909b}
 .tag{background:#272c34}
 .owed{color:#ff8080}.cred{color:#6ed69b}
 .verdict.partial,.caveat{background:#3a2e12;color:#f2d089;border-color:#6b5420}
}
"""

# No "Ödeme" column: the API returns PAYMENTTYPE as a bare code (0/1/2) with no
# label column, and the UI maps it client-side. Printing "2" instead of "Kredi
# Kartı" would be noise, and guessing the mapping would be worse. It plays no part
# in the rule, so it is left out.
COLS = [("room", "Oda"), ("guest", "Misafir"), ("agency", "Acenta"),
        ("checkin", "Geliş"), ("checkout", "Ayrılış"), ("durum", "Durum"),
        ("toplam", "Toplam"), ("rez_id", "Rez Id")]
DATE_COLS = {"checkin", "checkout"}
MONEY_COLS = {"toplam"}


def table(rows, kind):
    if not rows:
        return "<p class='note'>Yok.</p>"
    right = " style='text-align:right'"
    h = "".join("<th{}>{}</th>".format(right if k in MONEY_COLS else "", lbl)
                for k, lbl in COLS)
    cls = "owed" if kind == "owed" else ("cred" if kind == "cred" else "")
    body = []
    for r in rows:
        cells = []
        for k, _ in COLS:
            v = r.get(k)
            if k in DATE_COLS:
                cells.append(f"<td>{fmt_dt(v)}</td>")
            elif k in MONEY_COLS:
                mv = parse_money(v)
                cells.append(f"<td class='num'>{fmt_money(mv) if mv is not None else ''}</td>")
            else:
                cells.append(f"<td>{v if v is not None else ''}</td>")
        tds = "".join(cells)
        cur = r.get("currency") or ""
        body.append(f"<tr>{tds}<td class='num {cls}'>{fmt_money(r['_balance'])} {cur}</td></tr>")
    return (f"<div class='scroll'><table><thead><tr>{h}<th style='text-align:right'>Genel Bakiye</th>"
            f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def render(date, groups, meta):
    unpaid, canc = groups["unpaid"], groups["cancelled_unpaid"]
    n = len(unpaid)
    missing = meta.get("missing", 0)

    if n == 0 and not missing:
        verdict = ("clean", f"✅ {date} tarihinde gelen tüm misafirler ödemelerini yapmış. "
                            f"({len(groups['ok']) + len(groups['credit'])} rezervasyon kontrol edildi)")
    elif n == 0 and missing:
        # Never claim "everyone paid" over data we know is incomplete.
        verdict = ("partial", f"⚠️ Kontrol edilen {meta['total']} rezervasyonda borç yok — ancak "
                              f"{missing} rezervasyon bu raporda YOK. «Herkes ödedi» denemez.")
    else:
        verdict = ("dirty", f"⚠️ {n} rezervasyonda ödeme eksik — toplam {fmt_totals(unpaid)} "
                            f"borç görünüyor. Resepsiyona sorulmalı."
                            + (f" Ayrıca {missing} rezervasyon bu raporda yok." if missing else ""))

    parts = []
    if meta.get("note"):
        parts.append(f"<div class='caveat'>⚠️ <strong>Bu rapor eksik veriye dayanıyor.</strong> "
                     f"{meta['note']}</div>")
    parts.append(f"<div class='verdict {verdict[0]}'>{verdict[1]}</div>")
    parts.append(f"<h2>Ödenmemiş <span class='n'>({len(unpaid)})</span></h2>{table(unpaid,'owed')}")
    if canc:
        parts.append(f"<h2>İptal/silinmiş ama bakiyesi var <span class='n'>({len(canc)})</span></h2>"
                     f"{table(canc,'owed')}"
                     "<p class='note'>Bu rezervasyonlar iptal/silinmiş görünüyor; bakiye büyük "
                     "ihtimalle geride kalmış bir kayıttan geliyor.</p>")
    if groups["credit"]:
        parts.append(f"<h2>Negatif bakiye <span class='n'>({len(groups['credit'])})</span></h2>"
                     f"{table(groups['credit'],'cred')}"
                     "<p class='note'>Bilgi amaçlı — kurala göre borç değil. Çoğu acenta "
                     "rezervasyonunda normaldir.</p>")
    if groups["no_balance"]:
        parts.append(f"<h2>Bakiye bilgisi yok <span class='n'>({len(groups['no_balance'])})</span></h2>"
                     f"{table(groups['no_balance'],'')}")
    parts.append(f"<h2>Ödenmiş <span class='n'>({len(groups['ok'])})</span></h2>{table(groups['ok'],'')}")

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Riva ödeme kontrolü {date}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Riva Hotel Alsancak — günlük ödeme kontrolü</h1>
<p class="sub">Geliş tarihi <strong>{date}</strong> · {meta.get('total', 0)} rezervasyon
{f"(+{meta['missing']} eksik)" if meta.get('missing') else ""} ·
oluşturulma {meta.get('generated', '')}</p>
{''.join(parts)}
<footer>Kural: Genel Bakiye &gt; {meta.get('tolerance', 0)} ise ödenmemiş sayılır.
Kaynak: {meta.get('source', '')}, Geliş = {date}. rivacheck/paycheck.py</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="arrival date YYYY-MM-DD (default: yesterday)")
    ap.add_argument("--from-json", help="read rows from a JSON file instead of fetching")
    ap.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                    help="balances at or below this count as paid (default 0)")
    ap.add_argument("--open", action="store_true", help="open the report when done")
    ap.add_argument("--expected", type=int,
                    help="how many reservations the grid says exist (Toplam). If we have "
                         "fewer, the report is marked incomplete instead of 'all paid'.")
    ap.add_argument("--note", help="provenance caveat shown at the top of the report")
    ap.add_argument("--source", default="ElektraWeb res-all/reservation",
                    help="where the data came from (shown in the footer)")
    args = ap.parse_args()

    date = args.date or (dt.date.today() - dt.timedelta(days=1)).isoformat()

    # Exit codes:  0 = everyone paid   1 = unpaid found   2 = the check failed
    # Never let a failure look like a clean bill of health.
    try:
        if args.from_json:
            rows = json.loads(pathlib.Path(args.from_json).read_text())
            if isinstance(rows, dict):
                rows = rows.get("rows", [])
        else:
            # The JSON API, not the browser: faster, no virtualised-grid problem,
            # and safe to run from cron. elektra.py (Playwright) is only a fallback.
            from elektra_api import fetch_arrivals
            rows = fetch_arrivals(date)
    except Exception as e:
        print(f"KONTROL BAŞARISIZ / CHECK FAILED for {date}: {e}", file=sys.stderr)
        return 2

    if not rows:
        print(f"KONTROL BAŞARISIZ / CHECK FAILED: no reservations returned for {date}. "
              f"An empty grid is treated as a failure, not as 'everyone paid'.",
              file=sys.stderr)
        return 2

    groups = classify(rows, args.tolerance)
    REPORTS.mkdir(exist_ok=True)
    meta = {"total": len(rows), "tolerance": args.tolerance,
            "generated": dt.datetime.now().strftime("%d.%m.%Y %H:%M"),
            "note": args.note, "source": args.source,
            "missing": max(0, (args.expected or 0) - len(rows))}
    out = REPORTS / f"{date}.html"
    out.write_text(render(date, groups, meta), encoding="utf-8")

    n = len(groups["unpaid"])
    print(f"{date}: {len(rows)} rezervasyon, {n} ödenmemiş"
          + (f" (toplam {fmt_totals(groups['unpaid'])})" if n else ""))
    for r in groups["unpaid"]:
        print(f"   ODA {r.get('room','?'):<5} {str(r.get('guest',''))[:28]:<28} "
              f"{fmt_money(r['_balance'])} {r.get('currency','')}  {r.get('rez_id','')}")
    print(f"-> {out}")
    if args.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())

    if n:
        return 1
    if meta["missing"]:
        # No debts among the rows we saw, but we didn't see them all — that is
        # "inconclusive", not "everyone paid". Exit 0 here would be a lie to cron.
        print(f"UYARI: {meta['missing']} rezervasyon eksik — sonuç kesin değil.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
