#!/usr/bin/env python3
"""
audit.py — pre-night-audit payment sweep ("gün sonu öncesi ödeme kontrolü").

paycheck.py answers a narrow question: did yesterday's ARRIVALS pay? That misses the
cases that actually cost money. This widens the lens to the whole hotel and splits
what it finds by who owes and how urgent it is:

  A. WALKOUTS   — guests who CHECKED OUT still owing a net balance. The real leak.
  B. IN-HOUSE   — current guests running a net balance, any arrival date. Catches a
                  multi-night stay that paycheck.py never sees.
  C. RECEIVABLES— net balance owed by the AGENCY (Expedia, Tatil Budur, ELARA, …),
                  shown with age. Not a walkout; settles later; kept calm so real
                  problems don't hide among routine agency debt.
  D. OVERPAYMENTS — negative net balances: money the hotel is holding. Usually
                  harmless, occasionally a payment posted to the wrong folio.

THE SIGNAL IS NET GENEL BAKIYE (GENERALBALANCE), proven correct against live data:
78 recent checkouts showed a positive GUEST balance yet netted to zero because an
agency prepayment offset it — flagging guest-balance-alone would raise 78 false
alarms. Within a positive NET balance, guest-owed = urgent (guest is gone / here and
owes), agency-owed = receivable.

Usage:
    python3 audit.py                    # checkouts = yesterday, in-house = now
    python3 audit.py --date 2026-07-15
    python3 audit.py --days 3           # sweep the last 3 days of checkouts
    python3 audit.py --open
Exit: 0 all clear · 1 a guest owes (walkout or in-house) · 2 the check failed
"""
import argparse, datetime as dt, sys
from pathlib import Path

import paycheck as pc

REPORTS = Path("reports")
TOL = 0.5  # ignore sub-lira rounding crumbs; net must exceed this to count as owed


def money(r, field):
    return pc.parse_money(r.get(field)) or 0.0


def categorise(rows, today):
    """Tag each row with net balance, who owes, and age in days."""
    out = {"walkout": [], "inhouse_owes": [], "receivable": [], "overpay": []}
    for r in rows:
        net = money(r, "genel_bakiye")
        guest = money(r, "misafir_bakiye")
        state = str(r.get("durum") or "")
        rec = dict(r, _balance=net, _guest=guest, _agency=money(r, "acenta_bakiye"),
                   _age=age_days(r, today))
        concluded = state in ("CheckOut", "Cancelled", "Deleted")
        if net < -TOL:
            # A negative net on an IN-HOUSE guest is just an agency prepayment that
            # nightly room charges haven't caught up to yet — normal, not a concern.
            # It only counts as a parked overpayment once the stay is concluded.
            if concluded:
                out["overpay"].append(rec)
            continue
        elif net <= TOL:
            continue  # settled
        elif guest > TOL:
            # A guest personally owes. Checked out = walkout; still here = in-house tab.
            out["walkout" if state == "CheckOut" else "inhouse_owes"].append(rec)
        else:
            out["receivable"].append(rec)  # net owed, but by the agency
    out["walkout"].sort(key=lambda r: -r["_balance"])
    out["inhouse_owes"].sort(key=lambda r: -r["_balance"])
    out["receivable"].sort(key=lambda r: -r["_age"])   # oldest agency debt first
    out["overpay"].sort(key=lambda r: r["_balance"])
    return out


def age_days(r, today):
    """Days since the balance became 'open': since checkout for departed guests,
    since check-in otherwise."""
    anchor = r.get("checkout") if str(r.get("durum")) == "CheckOut" else r.get("checkin")
    s = str(anchor or "")[:10]
    try:
        d = dt.date.fromisoformat(s)
    except ValueError:
        return 0
    return max(0, (today - d).days)


# ---- rendering -------------------------------------------------------------
COLS = [("room", "Oda"), ("guest", "Misafir"), ("agency", "Acenta"),
        ("checkin", "Geliş"), ("checkout", "Ayrılış"), ("durum", "Durum")]


def sec_table(rows, show_age=False, split=False):
    if not rows:
        return "<p class='note'>Yok.</p>"
    head = "".join(f"<th>{lbl}</th>" for _, lbl in COLS)
    if show_age:
        head += "<th style='text-align:right'>Yaş</th>"
    if split:
        head += ("<th style='text-align:right'>Misafir</th>"
                 "<th style='text-align:right'>Acenta</th>")
    head += "<th style='text-align:right'>Genel Bakiye</th><th>Rez Id</th>"
    body = []
    for r in rows:
        tds = ""
        for k, _ in COLS:
            v = r.get(k)
            tds += f"<td>{pc.fmt_dt(v) if k in pc.DATE_COLS else (v if v is not None else '')}</td>"
        if show_age:
            tds += f"<td class='num'>{r['_age']}g</td>"
        cur = r.get("currency") or ""
        if split:
            tds += (f"<td class='num'>{pc.fmt_money(r['_guest'])}</td>"
                    f"<td class='num'>{pc.fmt_money(r['_agency'])}</td>")
        cls = "cred" if r["_balance"] < 0 else "owed"
        tds += (f"<td class='num {cls}'>{pc.fmt_money(r['_balance'])} {cur}</td>"
                f"<td>{r.get('rez_id') or ''}</td>")
        body.append(f"<tr>{tds}</tr>")
    return (f"<div class='scroll'><table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def render(date, cats, meta):
    urgent = cats["walkout"] + cats["inhouse_owes"]
    parts = []
    if urgent:
        parts.append(f"<div class='verdict dirty'>⚠️ {len(urgent)} misafir kendi hesabından "
                     f"borçlu — toplam {pc.fmt_totals(urgent)}. Gün sonundan önce çözülmeli.</div>")
    elif cats["receivable"]:
        parts.append(f"<div class='verdict partial'>✔️ Misafir kaynaklı açık yok. "
                     f"{len(cats['receivable'])} acenta alacağı var (aşağıda) — takip için, "
                     f"acil değil.</div>")
    else:
        parts.append("<div class='verdict clean'>✅ Açık ödeme yok. Herkes ödemiş; "
                     "bekleyen acenta alacağı da yok.</div>")

    parts.append(f"<h2>A · Çıkış yaptı, hâlâ borçlu <span class='n'>({len(cats['walkout'])})</span></h2>"
                 "<p class='note'>Misafir otelden ayrıldı ve net bakiye kaldı — asıl kaçak budur.</p>"
                 + sec_table(cats["walkout"], split=True))
    parts.append(f"<h2>B · İçeride, borçlu <span class='n'>({len(cats['inhouse_owes'])})</span></h2>"
                 "<p class='note'>Hâlâ konaklıyor ve misafir hesabında bakiye var.</p>"
                 + sec_table(cats["inhouse_owes"], split=True))
    parts.append(f"<h2>C · Acenta alacakları <span class='n'>({len(cats['receivable'])})</span></h2>"
                 "<p class='note'>Net bakiyeyi acenta borçlu (Expedia, Tatil Budur, ELARA…). "
                 "Sonradan ödenir; yaş = kaç gündür açık.</p>"
                 + sec_table(cats["receivable"], show_age=True, split=True))
    parts.append(f"<h2>D · Fazla ödeme / alacaklı <span class='n'>({len(cats['overpay'])})</span></h2>"
                 "<p class='note'>Otelin elinde duran bakiye. Genelde zararsız; bazen yanlış "
                 "folyoya işlenmiş ödemedir.</p>"
                 + sec_table(cats["overpay"]))

    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Riva gün sonu ödeme kontrolü {date}</title><style>{pc.CSS}</style></head>
<body><div class="wrap">
<h1>Riva Hotel Alsancak — gün sonu öncesi ödeme kontrolü</h1>
<p class="sub">Çıkışlar <strong>{date}</strong> · içeridekiler anlık ·
{meta['checkouts']} çıkış + {meta['inhouse']} içeride tarandı ·
oluşturulma {meta['generated']}</p>
{''.join(parts)}
<footer>Kural: net Genel Bakiye &gt; {TOL} ise borç. Misafir kaynaklı = acil,
acenta kaynaklı = alacak. Kaynak: ElektraWeb QA_HOTEL_RESERVATION. rivacheck/audit.py</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="pre-night-audit payment sweep")
    ap.add_argument("--date", help="checkout date to check (default: yesterday)")
    ap.add_argument("--days", type=int, default=1,
                    help="also sweep this many days of checkouts back from --date")
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()

    today = dt.date.today()
    date = a.date or (today - dt.timedelta(days=1)).isoformat()

    try:
        from elektra_api import fetch_departed_range, fetch_inhouse
        frm = (dt.date.fromisoformat(date) - dt.timedelta(days=a.days - 1)).isoformat()
        checkouts = fetch_departed_range(frm, date)
        inhouse = fetch_inhouse()
    except Exception as e:
        print(f"KONTROL BAŞARISIZ / CHECK FAILED: {e}", file=sys.stderr)
        return 2

    # In-house rows can share a RESID with nothing else here; combine populations.
    rows = checkouts + inhouse
    cats = categorise(rows, today)

    REPORTS.mkdir(exist_ok=True)
    meta = {"checkouts": len(checkouts), "inhouse": len(inhouse),
            "generated": dt.datetime.now().strftime("%d.%m.%Y %H:%M")}
    out = REPORTS / f"audit-{date}.html"
    out.write_text(render(date, cats, meta), encoding="utf-8")

    urgent = cats["walkout"] + cats["inhouse_owes"]
    print(f"{date}: {len(checkouts)} çıkış + {len(inhouse)} içeride | "
          f"{len(cats['walkout'])} kaçak, {len(cats['inhouse_owes'])} içeride borçlu, "
          f"{len(cats['receivable'])} acenta alacağı, {len(cats['overpay'])} fazla ödeme")
    for r in urgent:
        print(f"   ODA {str(r.get('room')):<6} {str(r.get('guest'))[:26]:<26} "
              f"{pc.fmt_money(r['_balance'])} {r.get('currency','')}  [{r.get('durum')}]  {r.get('rez_id')}")
    print(f"-> {out}")
    if a.open:
        import webbrowser
        webbrowser.open(out.resolve().as_uri())
    return 1 if urgent else 0


if __name__ == "__main__":
    sys.exit(main())
