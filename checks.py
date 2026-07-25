#!/usr/bin/env python3
"""
checks.py — owner-control lists for the Riva Hotel Alsancak dashboard.

Each build_* function returns a section dict {label, count, count_label, tone,
sub, updated, html} that dashboard.py encrypts and publishes as a tile.

Data comes from the Elektra views probed live (see elektra_api.py):
  * QA_HOTEL_RESERVATION — reservation model incl. RESSTATE, CANCELUSER,
    CREATORUSER, GENERALBALANCE, AVERAGENIGHTPRICE …
  * QA_HOTEL_FOLIO — folio lines; DEPTTYPENAME PAYMENT vs REVENUE, DEPNAME is the
    method (Cash/Credit Card/Havale/CityLedger), TYPE Discount/Rebate, and
    USERFULLNAME is WHO did it — so every anomaly names the receptionist.
"""
import datetime as dt
import html as _html
from collections import defaultdict, OrderedDict

import elektra_api as E

ROOMS_TOTAL = 55  # Riva Hotel Alsancak

METHOD_TR = {"Cash": "Nakit", "Credit Card": "Kredi Kartı", "Havale": "Havale/EFT",
             "CityLedger": "Cari / Acenta", "Bank": "Banka"}


# --------------------------------------------------------------------------- helpers
def esc(x):
    return _html.escape("" if x is None else str(x))


def num(x):
    if x is None:
        return 0.0
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace("\xa0", "")
    if not s:
        return 0.0
    # tolerate both "1.234,56" and "1234.56"
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def tl(x):
    """1234.5 -> '1.234,50'"""
    n = round(num(x), 2)
    s = f"{abs(n):,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return ("-" if n < 0 else "") + s


def pdate(x):
    if not x:
        return None
    try:
        return dt.date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def bal_tl(r, field="GENERALBALANCE"):
    """Reservation BALANCE fields (GENERAL/GUEST/AGENCYBALANCE, PAIDAMOUNT) are
    already in TL (master currency) in Elektra — return as-is. (Only the PRICE fields
    TOTALPRICE/AVERAGENIGHTPRICE are in the booking currency and need ×CURRENCYRATE.)"""
    return num(r.get(field))


TR_MONTHS = ["", "Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl",
             "Eki", "Kas", "Ara"]


def tr_g(d):
    return f"{d.day} {TR_MONTHS[d.month]}" if d else "—"


def yesterday():
    return dt.date.today() - dt.timedelta(days=1)


def now_str():
    n = dt.datetime.now()
    return f"{n.day:02d}.{n.month:02d}.{n.year} {n.hour:02d}:{n.minute:02d}"


# --------------------------------------------------------------------------- page shell
PAGE_CSS = """
*{box-sizing:border-box}
body{margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  color:#0f172a;background:#f4f6f9;padding:22px}
@media (prefers-color-scheme:dark){body{color:#e8eef7;background:#0b1120}}
.wrap{max-width:960px;margin:0 auto}
.eyebrow{color:#0e7490;font-weight:700;font-size:12px;letter-spacing:.4px;text-transform:uppercase}
@media (prefers-color-scheme:dark){.eyebrow{color:#22b8cf}}
h1{font-size:22px;margin:4px 0 2px}
.sub{color:#64748b;font-size:13px;margin-bottom:18px}
@media (prefers-color-scheme:dark){.sub{color:#94a3b8}}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.stat{background:#fff;border:1px solid #e2e8f0;border-radius:13px;padding:14px 18px;min-width:130px;flex:1}
@media (prefers-color-scheme:dark){.stat{background:#111a2e;border-color:#243049}}
.stat .n{font-size:24px;font-weight:800}
.stat .l{color:#64748b;font-size:12px;margin-top:2px}
.stat.bad .n{color:#dc2626}.stat.ok .n{color:#16a34a}
@media (prefers-color-scheme:dark){.stat.bad .n{color:#f87171}.stat.ok .n{color:#4ade80}}
table{width:100%;border-collapse:collapse;margin:10px 0 22px;font-size:13px;background:#fff;border-radius:12px;overflow:hidden}
@media (prefers-color-scheme:dark){table{background:#111a2e}}
th{background:#f1f5f9;text-align:left;padding:9px 11px;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px;color:#475569}
@media (prefers-color-scheme:dark){th{background:#182338;color:#94a3b8}}
td{padding:9px 11px;border-top:1px solid #eef2f7}
@media (prefers-color-scheme:dark){td{border-color:#1e2a44}}
.r{text-align:right;font-variant-numeric:tabular-nums}
.who{display:inline-block;background:#eef2ff;color:#4338ca;border-radius:6px;padding:1px 7px;font-size:11.5px;font-weight:600}
@media (prefers-color-scheme:dark){.who{background:#1e2450;color:#a5b4fc}}
.bad td:first-child{box-shadow:inset 3px 0 #dc2626}
.money{font-weight:700;font-variant-numeric:tabular-nums}
h2{font-size:15px;margin:22px 0 4px}
.lead{color:#64748b;font-size:12.5px;margin:0 0 8px}
.empty{background:#f0fdf4;border:1px solid #bbf7d0;color:#166534;border-radius:11px;padding:14px 16px;font-weight:600}
@media (prefers-color-scheme:dark){.empty{background:#0f2417;border-color:#14532d;color:#4ade80}}
.note{color:#94a3b8;font-size:11.5px;margin-top:18px;line-height:1.6}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.card{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px}
@media (prefers-color-scheme:dark){.card{background:#111a2e;border-color:#243049}}
.card h3{margin:0 0 10px;font-size:13.5px}
input{font:inherit;padding:9px 11px;border:1px solid #cbd5e1;border-radius:9px;width:100%;background:#fff;color:inherit}
@media (prefers-color-scheme:dark){input{background:#0b1120;border-color:#334155}}
label{font-size:12px;color:#64748b;display:block;margin:8px 0 3px}
.vrow{display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid #eef2f7}
.match{color:#16a34a;font-weight:700}.miss{color:#dc2626;font-weight:700}
"""


def PAGE(eyebrow, title, sub, body):
    return (f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{PAGE_CSS}</style></head><body><div class='wrap'>"
            f"<div class='eyebrow'>{esc(eyebrow)}</div><h1>{esc(title)}</h1>"
            f"<div class='sub'>{esc(sub)}</div>{body}</div></body></html>")


def stat(n, label, tone=""):
    return f"<div class='stat {tone}'><div class='n'>{n}</div><div class='l'>{esc(label)}</div></div>"


def empty_ok(msg):
    return f"<div class='empty'>✓ {esc(msg)}</div>"


# --------------------------------------------------------------------------- svg charts
INK = "#0e7490"


def svg_bars(labels, values, unit="", height=150, fmt=None):
    """Vertical bar chart, self-contained SVG (theme-aware via currentColor tints)."""
    fmt = fmt or (lambda v: f"{v:.0f}")
    n = len(values) or 1
    w = max(320, n * 26)
    mx = max(values) or 1
    bw = w / n * 0.62
    gap = w / n
    bars = []
    for i, v in enumerate(values):
        bh = (v / mx) * (height - 26)
        x = i * gap + (gap - bw) / 2
        y = height - 20 - bh
        show = (n <= 16) or (i % max(1, n // 12) == 0)
        bars.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bw:.1f}' height='{bh:.1f}' rx='2' fill='{INK}' opacity='.85'/>")
        if show:
            bars.append(f"<text x='{x+bw/2:.1f}' y='{height-6}' font-size='9' text-anchor='middle' fill='#94a3b8'>{esc(labels[i])}</text>")
    top = f"<text x='0' y='11' font-size='10' fill='#94a3b8'>en yüksek: {esc(fmt(mx))}{esc(unit)}</text>"
    return (f"<svg viewBox='0 0 {w} {height}' style='width:100%;height:auto;overflow:visible'>"
            f"{top}{''.join(bars)}</svg>")


def svg_line(labels, values, unit="", height=150, fmt=None):
    fmt = fmt or (lambda v: f"{v:.0f}")
    n = len(values) or 1
    w = max(320, n * 26)
    mx = max(values) or 1
    mn = min(values + [0])
    span = (mx - mn) or 1
    pts = []
    for i, v in enumerate(values):
        x = (i / max(1, n - 1)) * (w - 10) + 5
        y = height - 20 - ((v - mn) / span) * (height - 30)
        pts.append((x, y))
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    dots = "".join(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='2.4' fill='{INK}'/>" for x, y in pts)
    labs = []
    step = max(1, n // 10)
    for i in range(0, n, step):
        x = (i / max(1, n - 1)) * (w - 10) + 5
        labs.append(f"<text x='{x:.1f}' y='{height-5}' font-size='9' text-anchor='middle' fill='#94a3b8'>{esc(labels[i])}</text>")
    top = f"<text x='0' y='11' font-size='10' fill='#94a3b8'>en yüksek: {esc(fmt(mx))}{esc(unit)}</text>"
    return (f"<svg viewBox='0 0 {w} {height}' style='width:100%;height:auto;overflow:visible'>"
            f"{top}<polyline points='{poly}' fill='none' stroke='{INK}' stroke-width='2'/>"
            f"{dots}{''.join(labs)}</svg>")


def svg_donut(value, total, center_label):
    pct = (value / total) if total else 0
    r, c = 52, 60
    circ = 2 * 3.14159 * r
    off = circ * (1 - pct)
    return (f"<svg viewBox='0 0 120 120' style='width:150px;height:150px'>"
            f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='#e2e8f0' stroke-width='14'/>"
            f"<circle cx='{c}' cy='{c}' r='{r}' fill='none' stroke='{INK}' stroke-width='14'"
            f" stroke-linecap='round' stroke-dasharray='{circ:.1f}' stroke-dashoffset='{off:.1f}'"
            f" transform='rotate(-90 {c} {c})'/>"
            f"<text x='{c}' y='{c-2}' font-size='22' font-weight='800' text-anchor='middle' fill='currentColor'>{value}</text>"
            f"<text x='{c}' y='{c+16}' font-size='10' text-anchor='middle' fill='#94a3b8'>{esc(center_label)}</text></svg>")


def svg_hbars(pairs, unit="₺"):
    """pairs = [(label, value)], horizontal bars."""
    mx = max([v for _, v in pairs] + [1])
    rows = []
    for lab, v in pairs:
        pct = v / mx * 100
        rows.append(
            f"<div style='margin:7px 0'><div style='display:flex;justify-content:space-between;font-size:12px'>"
            f"<span>{esc(lab)}</span><span class='money'>{tl(v)} {esc(unit)}</span></div>"
            f"<div style='height:8px;background:#eef2f7;border-radius:5px;margin-top:3px'>"
            f"<div style='height:8px;width:{pct:.1f}%;background:{INK};border-radius:5px'></div></div></div>")
    return "".join(rows)


# --------------------------------------------------------------------------- 1) Kasa & POS
def build_kasa(env):
    day = yesterday()
    rows = E.fetch_folio(day.isoformat(), day.isoformat(), env=env)
    pays = [r for r in rows if r.get("DEPTTYPENAME") == "PAYMENT"]

    by_method = defaultdict(float)
    by_user_method = defaultdict(lambda: defaultdict(float))
    for r in pays:
        amt = abs(num(r.get("TOTAL")))
        m = r.get("DEPNAME") or "Diğer"
        by_method[m] += amt
        by_user_method[r.get("USERFULLNAME") or "—"][m] += amt

    cash = by_method.get("Cash", 0.0)
    card = by_method.get("Credit Card", 0.0)
    total = sum(by_method.values())

    order = ["Cash", "Credit Card", "Havale", "CityLedger"]
    methods = [m for m in order if m in by_method] + [m for m in by_method if m not in order]

    stats = stat(f"{tl(total)} ₺", "toplam tahsilat")
    stats += stat(f"{tl(cash)} ₺", "nakit", "")
    stats += stat(f"{tl(card)} ₺", "kredi kartı", "")
    stats += stat(len(pays), "işlem")

    # Method breakdown table
    mrows = "".join(
        f"<tr><td>{esc(METHOD_TR.get(m, m))}</td><td class='r money'>{tl(by_method[m])} ₺</td></tr>"
        for m in methods)
    method_tbl = f"<h2>Ödeme türüne göre</h2><table><tr><th>Tür</th><th class='r'>Tutar</th></tr>{mrows}</table>"

    # Per-user table
    urows = []
    for u in sorted(by_user_method, key=lambda u: -sum(by_user_method[u].values())):
        tot = sum(by_user_method[u].values())
        c = by_user_method[u].get("Cash", 0)
        cc = by_user_method[u].get("Credit Card", 0)
        urows.append(f"<tr><td><span class='who'>{esc(u)}</span></td>"
                     f"<td class='r money'>{tl(c)}</td><td class='r money'>{tl(cc)}</td>"
                     f"<td class='r money'>{tl(tot)} ₺</td></tr>")
    user_tbl = ("<h2>Personele göre tahsilat</h2><table><tr><th>Personel</th>"
                "<th class='r'>Nakit</th><th class='r'>Kredi Kartı</th><th class='r'>Toplam</th></tr>"
                + "".join(urows) + "</table>")

    # Reconciliation mini-form (client-side, localStorage per date).
    form = f"""
    <h2>Kasa & POS mutabakatı</h2>
    <p class='lead'>Fiziki sayılan nakiti ve POS Z-raporu toplamını girin; PMS ile farkı anında görün.</p>
    <div class='grid2'>
      <div class='card'><h3>💵 Nakit</h3>
        <div class='vrow'><span>PMS nakit tahsilat</span><span class='money' id='pmsCash'>{tl(cash)} ₺</span></div>
        <label>Kasada sayılan nakit (₺)</label><input id='inCash' type='number' inputmode='decimal' placeholder='0'>
        <div class='vrow'><span>Fark</span><span id='dCash' class='money'>—</span></div>
      </div>
      <div class='card'><h3>💳 Kredi Kartı / POS</h3>
        <div class='vrow'><span>PMS kart tahsilat</span><span class='money' id='pmsCard'>{tl(card)} ₺</span></div>
        <label>POS Z-raporu toplamı (₺)</label><input id='inCard' type='number' inputmode='decimal' placeholder='0'>
        <div class='vrow'><span>Fark</span><span id='dCard' class='money'>—</span></div>
      </div>
    </div>
    <div class='note'>Fark 0 ise ✓ eşleşti. Nakit farkı = eksik/fazla kasa; kart farkı = POS ile PMS uyuşmazlığı — ikisi de incelenmeli.
    Girdiğiniz sayılar yalnızca bu tarayıcıda saklanır (gün: {day.isoformat()}).</div>
    <script>
    (function(){{
      var CASH={cash:.2f}, CARD={card:.2f}, KEY='kasa-{day.isoformat()}';
      var ic=document.getElementById('inCash'), id=document.getElementById('inCard');
      try{{var s=JSON.parse(localStorage.getItem(KEY)||'{{}}'); if(s.cash!=null)ic.value=s.cash; if(s.card!=null)id.value=s.card;}}catch(e){{}}
      function tlf(n){{return (Math.round(n*100)/100).toLocaleString('tr-TR',{{minimumFractionDigits:2}});}}
      function upd(){{
        function diff(inp,base,out){{
          var v=parseFloat(inp.value);
          if(isNaN(v)){{out.textContent='—';out.className='money';return;}}
          var d=v-base; out.textContent=(d>=0?'+':'')+tlf(d)+' ₺';
          out.className='money '+(Math.abs(d)<0.5?'match':'miss');
        }}
        diff(ic,CASH,document.getElementById('dCash'));
        diff(id,CARD,document.getElementById('dCard'));
        try{{localStorage.setItem(KEY,JSON.stringify({{cash:ic.value,card:id.value}}));}}catch(e){{}}
      }}
      ic.addEventListener('input',upd); id.addEventListener('input',upd); upd();
    }})();
    </script>"""

    body = f"<div class='stats'>{stats}</div>{form}{method_tbl}{user_tbl}"
    body += ("<div class='note'>Not: tutarlar PMS folio 'PAYMENT' satırlarından; iade/düzeltme varsa ayrıca gözden geçirin. "
             "Kaynak: QA_HOTEL_FOLIO.</div>")
    return {"label": "Kasa & POS Mutabakatı", "count": int(round(total)),
            "count_label": "₺ tahsilat", "tone": "ok",
            "sub": f"{tr_g(day)} · nakit {tl(cash)} ₺ · kart {tl(card)} ₺",
            "updated": now_str(), "html": PAGE("Günlük Kasa Kontrolü",
            "Kasa & POS Mutabakatı", f"{tr_g(day)} tahsilatları", body)}


# --------------------------------------------------------------------------- 2) İptal/Silinen
def build_iptal(env):
    today = dt.date.today()
    frm = (today - dt.timedelta(days=30)).isoformat()
    to = today.isoformat()
    res = E.fetch_reservations_between("CHECKIN", frm, to, env=env)
    cancels = [r for r in res if r.get("RESSTATE") in ("Cancelled", "Deleted")]

    # Money taken on these bookings? Cross-ref folio PAYMENT lines by RESID.
    fol = E.fetch_folio(frm, to, env=env)
    paid_by_res = defaultdict(float)
    for r in fol:
        if r.get("DEPTTYPENAME") == "PAYMENT":
            paid_by_res[str(r.get("RESID"))] += abs(num(r.get("TOTAL")))

    flagged = []
    for r in cancels:
        rid = str(r.get("RESID"))
        paid = paid_by_res.get(rid, 0.0) or bal_tl(r, "PAIDAMOUNT")  # folio TL; PAIDAMOUNT→TL
        if paid > 0.5:
            flagged.append((r, paid))
    flagged.sort(key=lambda t: -t[1])

    stats = (stat(len(flagged), "para alınmış iptal", "bad" if flagged else "ok")
             + stat(len(cancels), "toplam iptal/silinen")
             + stat(f"{tl(sum(p for _, p in flagged))} ₺", "riskli tutar"))

    if flagged:
        trs = []
        for r, paid in flagged:
            who = r.get("CANCELUSER") or r.get("CREATORUSER") or "—"
            trs.append(f"<tr class='bad'><td>{esc(r.get('ROOMNO') or '—')}</td>"
                       f"<td>{esc((r.get('GUESTNAMES') or '')[:32])}</td>"
                       f"<td>{esc(r.get('RESSTATE'))}</td>"
                       f"<td class='r money'>{tl(paid)} ₺</td>"
                       f"<td>{tr_g(pdate(r.get('CHECKIN')))}</td>"
                       f"<td><span class='who'>{esc(who)}</span></td></tr>")
        table = ("<h2>Para alınmış ama iptal/silinmiş rezervasyonlar</h2>"
                 "<p class='lead'>Bu rezervasyonlarda tahsilat yapılmış, sonra kayıt iptal/silinmiş. "
                 "Nakit cebe atma riskinin en net sinyali — her biri ilgili personele bağlı.</p>"
                 "<table><tr><th>Oda</th><th>Misafir</th><th>Durum</th><th class='r'>Alınan</th>"
                 "<th>Giriş</th><th>İşlem yapan</th></tr>" + "".join(trs) + "</table>")
    else:
        table = empty_ok("Para alınıp iptal/silinen rezervasyon yok.")

    note = ("<div class='note'>Oda fiziksel olarak kullanıldı mı? Bunu Haftalık Kart Güvenliği listesi "
            "(kapı kilidi) gösterir — iki liste birlikte 'satılmadan kullanılan oda'yı yakalar. "
            "Kaynak: QA_HOTEL_RESERVATION + QA_HOTEL_FOLIO.</div>")
    return {"label": "İptal / Silinen Takibi", "count": len(flagged),
            "count_label": "riskli", "tone": "bad" if flagged else "ok",
            "sub": f"son 30 gün · {len(cancels)} iptal/silinen",
            "updated": now_str(), "html": PAGE("Boş Oda Satışı Kontrolü",
            "İptal / Silinen Rezervasyon Takibi", "son 30 gün", f"<div class='stats'>{stats}</div>{table}{note}")}


# --------------------------------------------------------------------------- 3) İndirim
def build_indirim(env):
    today = dt.date.today()
    frm = (today - dt.timedelta(days=7)).isoformat()
    to = today.isoformat()
    fol = E.fetch_folio(frm, to, env=env)
    disc = [r for r in fol if r.get("TYPE") in ("Discount", "Rebate")]

    by_user = defaultdict(float)
    for r in disc:
        by_user[r.get("USERFULLNAME") or "—"] += abs(num(r.get("TOTAL")))
    total = sum(by_user.values())

    stats = (stat(len(disc), "indirim/rebate satırı", "bad" if disc else "ok")
             + stat(f"{tl(total)} ₺", "toplam indirim")
             + stat(len(by_user) if disc else 0, "personel"))

    if disc:
        chart = ("<div class='card'><h3>Personele göre indirim</h3>"
                 + svg_hbars(sorted(by_user.items(), key=lambda t: -t[1])) + "</div>")
        trs = []
        for r in sorted(disc, key=lambda r: -abs(num(r.get("TOTAL")))):
            trs.append(f"<tr><td>{tr_g(pdate(r.get('FOLIODATE')))}</td>"
                       f"<td>{esc(r.get('ROOMNO') or '—')}</td>"
                       f"<td>{esc((r.get('GUESTNAMES') or '')[:28])}</td>"
                       f"<td>{esc(r.get('TYPE'))}</td>"
                       f"<td class='r money'>{tl(num(r.get('TOTAL')))} ₺</td>"
                       f"<td><span class='who'>{esc(r.get('USERFULLNAME') or '—')}</span></td></tr>")
        table = ("<h2>İndirim & rebate işlemleri (son 7 gün)</h2>"
                 "<p class='lead'>Kim, hangi odaya, ne kadar indirim uygulamış. Yetkisiz/aşırı indirim "
                 "eksik tahsilatın en sık yoludur — hepsini gözden geçirin.</p>"
                 "<table><tr><th>Tarih</th><th>Oda</th><th>Misafir</th><th>Tür</th>"
                 "<th class='r'>Tutar</th><th>İşlem yapan</th></tr>" + "".join(trs) + "</table>")
    else:
        chart = ""
        table = empty_ok("Son 7 günde indirim/rebate işlemi yok.")

    body = f"<div class='stats'>{stats}</div>{chart}{table}"
    body += "<div class='note'>Kaynak: QA_HOTEL_FOLIO (TYPE = Discount/Rebate).</div>"
    return {"label": "İndirim İstisnaları", "count": len(disc),
            "count_label": "gözden geçir", "tone": "bad" if disc else "ok",
            "sub": f"son 7 gün · {tl(total)} ₺ indirim",
            "updated": now_str(), "html": PAGE("Eksik Tahsilat Kontrolü",
            "İndirim İstisnaları", "son 7 gün", body)}


# --------------------------------------------------------------------------- 4) Açık bakiye
def build_bakiye(env):
    """Bakiye Kontrolü — reservations where the guest STILL OWES money (net), so a
    walk-in / direct guest who didn't pay isn't forgotten. Uses NET balance
    (GENERALBALANCE): the guest-folio figure alone over-counts because an agency
    prepayment can offset it to zero (Booking/Expedia). A guest who CHECKED OUT still
    owing net is flagged urgent (left without paying)."""
    today = dt.date.today()
    inhouse = E.fetch_reservations(
        [{"Column": "RESSTATE", "Operator": "=", "Value": "InHouse"}], env=env)
    recent_out = E.fetch_reservations_between(
        "CHECKOUT", (today - dt.timedelta(days=180)).isoformat(), today.isoformat(),
        env=env, extra=[{"Column": "RESSTATE", "Operator": "=", "Value": "CheckOut"}])
    rows = inhouse + recent_out
    # Net owed AND the guest (not the agency) owes it. Balances are already TL.
    owed = [r for r in rows if bal_tl(r) > 0.5 and bal_tl(r, "GUESTBALANCE") > 0.5]
    for r in owed:
        r["_left"] = r.get("RESSTATE") == "CheckOut"        # çıkış yaptı, hâlâ borçlu
    owed.sort(key=lambda r: (0 if r.get("_left") else 1, -bal_tl(r)))

    left = [r for r in owed if r.get("_left")]
    total = sum(bal_tl(r) for r in owed)
    stats = (stat(len(owed), "açık kayıt", "bad" if owed else "ok")
             + stat(f"{tl(total)} ₺", "tahsil edilecek toplam")
             + stat(len(left), "çıkıp borçlu (acil)", "bad" if left else "ok"))

    def age(r):
        if not r.get("_left"):
            return "konaklıyor"
        co = pdate(r.get("CHECKOUT"))
        if not co:
            return "—"
        d = (today - co).days
        return "bugün çıktı" if d <= 0 else f"{d} gün önce çıktı"

    if owed:
        trs = []
        for r in owed:
            durum = ("🔴 ÇIKTI — borçlu" if r.get("_left") else "Konaklıyor")
            trs.append(f"<tr class='{'bad' if r.get('_left') else ''}'>"
                       f"<td>{esc(r.get('ROOMNO') or '—')}</td>"
                       f"<td>{esc((r.get('GUESTNAMES') or '')[:34])}</td>"
                       f"<td>{esc((r.get('AGENCY') or '')[:16])}</td>"
                       f"<td>{durum}</td>"
                       f"<td class='r money'>{tl(bal_tl(r))} ₺</td>"
                       f"<td>{esc(age(r))}</td></tr>")
        table = ("<h2>Ödemesi alınmamış misafir kayıtları</h2>"
                 "<p class='lead'>Misafirin gerçekten borçlu olduğu (net) kayıtlar — en acili "
                 "<b>çıkış yaptığı hâlde borçlu</b> olanlar (kırmızı). Tahsil edilene kadar burada kalır, "
                 "böylece unutulmaz.</p>"
                 "<table><tr><th>Oda</th><th>Misafir</th><th>Acenta</th><th>Durum</th>"
                 "<th class='r'>Borç</th><th>Yaş</th></tr>" + "".join(trs) + "</table>")
    else:
        table = empty_ok("Ödemesi alınmamış misafir kaydı yok — hepsi tahsil edilmiş.")

    note = ("<div class='note'>Net borç (GENERALBALANCE, TL) ve misafirin kendi payı (GUESTBALANCE) > 0 olanlar. "
            "Acenta ön ödemesiyle netlenip sıfırlanan folyolar sayılmaz (yanlış alarm olmasın). "
            "Konaklayan + son 180 gün çıkış. Kaynak: QA_HOTEL_RESERVATION.</div>")
    sub = f"tahsil edilecek {tl(total)} ₺" + (f" · {len(left)} çıkıp borçlu 🔴" if left else "")
    return {"label": "Bakiye Kontrolü", "count": len(owed),
            "count_label": "açık kayıt", "tone": "bad" if owed else "ok",
            "sub": sub, "updated": now_str(),
            "html": PAGE("Tahsilat — Açık Bakiye", "Bakiye Kontrolü",
                         "ödemesi alınmamış misafir kayıtları",
                         f"<div class='stats'>{stats}</div>{table}{note}")}


# --------------------------------------------------------------------------- occupancy engine
# Shared by İstatistikler + Aylık Satışlar. Occupancy = distinct PHYSICAL (numeric)
# rooms with a live reservation per night; revenue = TRY nightly price (MCTOTALPRICE
# / nights) of those rooms. Excludes cancelled/deleted/no-show and virtual tour rooms.
EXCL_STATES = {"Cancelled", "Deleted", "No Show"}
TR_MON_FULL = ["", "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
               "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def try_nightly(r):
    ni = num(r.get("NIGHT")) or 1
    mc = num(r.get("MCTOTALPRICE"))
    return (mc / ni) if mc else num(r.get("AVERAGENIGHTPRICE")) * (num(r.get("CURRENCYRATE")) or 1)


def month_start(d, back=0):
    tot = d.year * 12 + (d.month - 1) - back
    y, m = divmod(tot, 12)
    return dt.date(y, m + 1, 1)


def active_reservations(env, start, end):
    res = E.fetch_reservations(
        [{"Column": "CHECKIN", "Operator": "<=", "Value": f"{end} 23:59:59"},
         {"Column": "CHECKOUT", "Operator": ">=", "Value": f"{start} 00:00:00"}], env=env,
        columns=["RESID", "ROOMNO", "RESSTATE", "MCTOTALPRICE", "NIGHT",
                 "AVERAGENIGHTPRICE", "CURRENCYRATE", "CHECKIN", "CHECKOUT"])
    return [r for r in res if str(r.get("ROOMNO") or "").isdigit()
            and r.get("RESSTATE") not in EXCL_STATES]


def daily_occupancy(active, start, end):
    """OrderedDict date -> {room: try_nightly}. De-dupes rooms per night."""
    out = OrderedDict()
    d, one = start, dt.timedelta(days=1)
    while d <= end:
        rp = {}
        for r in active:
            ci, co = pdate(r.get("CHECKIN")), pdate(r.get("CHECKOUT"))
            if ci and co and ci <= d < co:
                rp[str(r.get("ROOMNO"))] = try_nightly(r)
        out[d] = rp
        d += one
    return out


def monthly_aggregate(daily):
    """daily -> OrderedDict (year,month) -> {rooms, rev, days, occ, adr, revpar}."""
    agg = OrderedDict()
    for d, rp in daily.items():
        a = agg.setdefault((d.year, d.month), {"rooms": 0, "rev": 0.0, "days": 0})
        a["rooms"] += len(rp)
        a["rev"] += sum(rp.values())
        a["days"] += 1
    for a in agg.values():
        cap = ROOMS_TOTAL * a["days"]
        a["occ"] = round(a["rooms"] / cap * 100) if cap else 0
        a["adr"] = a["rev"] / a["rooms"] if a["rooms"] else 0.0
        a["revpar"] = a["rev"] / cap if cap else 0.0
    return agg


def mlabel(key, short=True):
    y, m = key
    return f"{TR_MONTHS[m]} {str(y)[2:]}" if short else f"{TR_MON_FULL[m]} {y}"


# --------------------------------------------------------------------------- 5) İstatistikler
def build_stats(env):
    today = dt.date.today()
    # One 12-month fetch powers both the daily (last 30) and the monthly views.
    start = month_start(today, 11)
    active = active_reservations(env, start, today)
    daily = daily_occupancy(active, start, today)
    day_keys = list(daily.keys())

    last30 = day_keys[-30:]
    occ = [len(daily[d]) for d in last30]
    adr = [(sum(daily[d].values()) / len(daily[d]) if daily[d] else 0.0) for d in last30]
    occ_pct = [min(100, round(c / ROOMS_TOTAL * 100)) for c in occ]
    labels = [f"{d.day:02d}" for d in last30]

    today_occ = len(daily[today])
    today_pct = min(100, round(today_occ / ROOMS_TOTAL * 100))
    today_adr = (sum(daily[today].values()) / today_occ) if today_occ else 0.0
    revpar = today_adr * today_occ / ROOMS_TOTAL if ROOMS_TOTAL else 0
    avg_pct = round(sum(occ_pct) / len(occ_pct)) if occ_pct else 0
    avg_adr = (sum(a for a in adr if a) / len([a for a in adr if a])) if any(adr) else 0

    stats = (stat(f"%{today_pct}", "bugün doluluk", "")
             + stat(f"{today_occ}/{ROOMS_TOTAL}", "dolu oda")
             + stat(f"{tl(today_adr)} ₺", "bugün ADR")
             + stat(f"{tl(revpar)} ₺", "RevPAR"))

    # Payment method split (last 7 days) for a nice breakdown chart.
    fol = E.fetch_folio((today - dt.timedelta(days=7)).isoformat(), today.isoformat(), env=env)
    pm = defaultdict(float)
    for r in fol:
        if r.get("DEPTTYPENAME") == "PAYMENT":
            pm[METHOD_TR.get(r.get("DEPNAME"), r.get("DEPNAME") or "Diğer")] += abs(num(r.get("TOTAL")))

    donut = svg_donut(today_occ, ROOMS_TOTAL, f"/ {ROOMS_TOTAL} oda")
    charts = f"""
    <div class='grid2'>
      <div class='card'><h3>Bugün doluluk</h3><div style='display:flex;justify-content:center'>{donut}</div>
        <div style='text-align:center;color:#94a3b8;font-size:12px'>%{today_pct} dolu · 30 gün ort. %{avg_pct}</div></div>
      <div class='card'><h3>Ödeme türü dağılımı (7 gün)</h3>{svg_hbars(sorted(pm.items(), key=lambda t:-t[1])) or "<div class='lead'>veri yok</div>"}</div>
    </div>
    <div class='card' style='margin-top:16px'><h3>Doluluk % — son 30 gün</h3>{svg_bars(labels, occ_pct, unit='%')}</div>
    <div class='card' style='margin-top:16px'><h3>Ortalama oda fiyatı (ADR ₺) — son 30 gün</h3>{svg_line(labels, adr, unit=' ₺', fmt=lambda v: tl(v))}</div>
    """
    # ---- monthly summary (last 12 months) ----
    monthly = monthly_aggregate(daily)
    mkeys = list(monthly.keys())
    mlabels = [mlabel(k) for k in mkeys]
    m_occ = [monthly[k]["occ"] for k in mkeys]
    m_adr = [monthly[k]["adr"] for k in mkeys]
    mrows = "".join(
        f"<tr><td>{esc(mlabel(k, False))}</td><td class='r'>%{monthly[k]['occ']}</td>"
        f"<td class='r money'>{tl(monthly[k]['adr'])}</td>"
        f"<td class='r money'>{tl(monthly[k]['revpar'])}</td>"
        f"<td class='r'>{monthly[k]['rooms']}</td>"
        f"<td class='r money'>{tl(monthly[k]['rev'])} ₺</td></tr>"
        for k in reversed(mkeys))
    monthly_html = (
        "<h2>Aylık özet (son 12 ay)</h2>"
        f"<div class='card'><h3>Aylık doluluk %</h3>{svg_bars(mlabels, m_occ, unit='%')}</div>"
        f"<div class='card' style='margin-top:16px'><h3>Aylık ADR (₺)</h3>"
        f"{svg_line(mlabels, m_adr, unit=' ₺', fmt=lambda v: tl(v))}</div>"
        "<table><tr><th>Ay</th><th class='r'>Doluluk</th><th class='r'>ADR</th>"
        "<th class='r'>RevPAR</th><th class='r'>Oda-gecesi</th><th class='r'>Oda geliri</th></tr>"
        + mrows + "</table>"
        "<p class='note'>Bu ay kısmidir (bugüne kadar). Oda geliri = konaklanan oda-gecelerinin TL gecelik toplamı (ekstralar hariç).</p>")

    note = (f"<div class='note'>Doluluk = dolu oda / {ROOMS_TOTAL}. ADR = dolu odaların ortalama gecelik fiyatı (TL). "
            f"30 gün ort.: doluluk %{avg_pct}, ADR {tl(avg_adr)} ₺. Kaynak: QA_HOTEL_RESERVATION.</div>")
    body = f"<div class='stats'>{stats}</div>{charts}{monthly_html}{note}"
    return {"label": "İstatistikler & Grafikler", "count": today_pct,
            "count_label": "% bugün doluluk", "tone": "ok",
            "sub": f"bugün %{today_pct} · ADR {tl(today_adr)} ₺ · 30 gün ort. %{avg_pct}",
            "updated": now_str(), "html": PAGE("Doluluk & Gelir",
            "İstatistikler & Grafikler", "son 30 gün + aylık", body)}


# --------------------------------------------------------------------------- 6) Aylık Satışlar
def build_satis(env):
    today = dt.date.today()
    start = month_start(today, 11)
    active = active_reservations(env, start, today)
    daily = daily_occupancy(active, start, today)
    monthly = monthly_aggregate(daily)
    mkeys = list(monthly.keys())
    mlabels = [mlabel(k) for k in mkeys]
    m_rev = [monthly[k]["rev"] for k in mkeys]

    cur = monthly[mkeys[-1]] if mkeys else {"rev": 0, "rooms": 0, "adr": 0}
    prev = monthly[mkeys[-2]] if len(mkeys) > 1 else {"rev": 0}
    ytd = sum(v["rev"] for k, v in monthly.items() if k[0] == today.year)

    stats = (stat(f"{tl(cur['rev'])} ₺", f"{TR_MON_FULL[today.month]} oda geliri")
             + stat(f"{tl(prev['rev'])} ₺", "geçen ay")
             + stat(f"{tl(ytd)} ₺", f"{today.year} yıl toplamı")
             + stat(f"{cur['rooms']}", "bu ay oda-gecesi"))

    revbar = (f"<div class='card'><h3>Aylık oda geliri (₺)</h3>"
              f"{svg_bars(mlabels, m_rev, unit=' ₺', fmt=lambda v: tl(v))}</div>")

    # This-month collections by payment method (folio) — how the money came in.
    fol = E.fetch_folio(month_start(today).isoformat(), today.isoformat(), env=env)
    pm = defaultdict(float)
    for r in fol:
        if r.get("DEPTTYPENAME") == "PAYMENT":
            pm[METHOD_TR.get(r.get("DEPNAME"), r.get("DEPNAME") or "Diğer")] += abs(num(r.get("TOTAL")))
    pm_card = (f"<div class='card'><h3>Bu ay tahsilat — ödeme türü</h3>"
               f"{svg_hbars(sorted(pm.items(), key=lambda t: -t[1])) or '<div class=lead>veri yok</div>'}</div>")

    mrows = "".join(
        f"<tr><td>{esc(mlabel(k, False))}</td><td class='r money'>{tl(monthly[k]['rev'])} ₺</td>"
        f"<td class='r'>{monthly[k]['rooms']}</td><td class='r'>%{monthly[k]['occ']}</td>"
        f"<td class='r money'>{tl(monthly[k]['adr'])}</td></tr>"
        for k in reversed(mkeys))
    table = ("<h2>Aylık satış tablosu</h2><table><tr><th>Ay</th><th class='r'>Oda geliri</th>"
             "<th class='r'>Oda-gecesi</th><th class='r'>Doluluk</th><th class='r'>ADR</th></tr>"
             + mrows + "</table>")

    body = (f"<div class='stats'>{stats}</div>{revbar}"
            f"<div class='grid2' style='margin-top:16px'>{pm_card}</div>{table}"
            "<div class='note'>Oda geliri = konaklanan oda-gecelerinin TL gecelik toplamı (tahakkuk; ekstralar/minibar hariç). "
            "Tahsilat = bu ay folioya girilen ödemeler (TL). Kaynak: QA_HOTEL_RESERVATION + QA_HOTEL_FOLIO.</div>")
    return {"label": "Aylık Satışlar", "count": int(round(cur["rev"] / 1000)),
            "count_label": "bin ₺ · bu ay", "tone": "ok",
            "sub": f"{TR_MON_FULL[today.month]}: {tl(cur['rev'])} ₺ · {today.year} toplam {tl(ytd)} ₺",
            "updated": now_str(), "html": PAGE("Aylık Gelir & Satış",
            "Aylık Satışlar", "son 12 ay oda geliri", body)}


# --------------------------------------------------------------------------- Parite (fiyat) formu
PARITE_CHANNELS = [
    ("kapidan", "🏠 Kapıdan (rezervasyonal)",
     "https://rivahotelalsancak.rezervasyonal.com/?Checkin={ci}&Checkout={co}&Adult=2&child=0&ChildAges=&language=tr"),
    ("booking", "Booking.com",
     "https://www.booking.com/searchresults.tr.html?ss=Riva+Hotel+Alsancak+Izmir&checkin={ci}&checkout={co}&group_adults=2&no_rooms=1&group_children=0"),
    ("hotels", "Hotels.com",
     "https://tr.hotels.com/Hotel-Search?destination=Riva%20Hotel%20Alsancak&startDate={ci}&endDate={co}&adults=2"),
    ("etstur", "Etstur",
     "https://www.etstur.com/oteller?aramaMetni=Riva+Hotel+Alsancak"),
    ("tatilsepeti", "Tatilsepeti",
     "https://www.tatilsepeti.com/arama?SearchText=Riva+Hotel+Alsancak"),
    ("enuygun", "Enuygun",
     "https://www.enuygun.com/otel/?query=Riva+Hotel+Alsancak"),
    ("tatilbudur", "Tatilbudur",
     "https://www.tatilbudur.com/oteller?q=Riva+Hotel+Alsancak"),
]


def build_parite(env):
    """Client-side parity ENTRY FORM. Prices are typed in the browser (OTAs are
    captcha/anti-bot protected, so no reliable auto-scrape). Each channel opens in a
    new tab; you read the price and type it. Cheapest is flagged green, an OTA cheaper
    than the direct rate is a parity violation (red). Saved per day in the browser."""
    ch_js = json.dumps([{"key": k, "name": n, "url": u} for k, n, u in PARITE_CHANNELS],
                       ensure_ascii=False)
    body = f"""
    <p class='lead'>Baz: <b>bu gece · 1 gece · 2 yetişkin · Standart Stüdyo (mutfaklı)</b>.
    Her kanalın <b>Aç →</b> linkine tıkla, fiyatı gör, yaz. 🔴 <b>kapıdandan ucuz</b> satan OTA = parite ihlali.</p>
    <div class='stats' id='psum'></div>
    <table><tr><th>Kanal</th><th></th><th class='r'>Fiyat (₺)</th></tr>
      <tbody id='prows'></tbody></table>
    <div class='note' id='psaved'>Girdiğin fiyatlar bu tarayıcıda, gün gün saklanır. Her gün tekrar gir.</div>
    <script>
    (function(){{
      var CH = {ch_js};
      function pad(n){{return (n<10?'0':'')+n;}}
      var now=new Date(), tom=new Date(Date.now()+864e5);
      var ci=now.getFullYear()+'-'+pad(now.getMonth()+1)+'-'+pad(now.getDate());
      var co=tom.getFullYear()+'-'+pad(tom.getMonth()+1)+'-'+pad(tom.getDate());
      var KEY='parite-'+ci;
      var saved={{}}; try{{saved=JSON.parse(localStorage.getItem(KEY)||'{{}}');}}catch(e){{}}
      var rows=document.getElementById('prows');
      CH.forEach(function(c){{
        var url=c.url.replace('{{ci}}',ci).replace('{{co}}',co);
        var tr=document.createElement('tr'); tr.id='row-'+c.key;
        tr.innerHTML='<td>'+c.name+'</td>'+
          '<td><a href="'+url+'" target="_blank" rel="noopener" style="color:var(--brand,#0e7490);font-weight:600">Aç →</a></td>'+
          '<td class="r"><input type="number" inputmode="decimal" data-k="'+c.key+'" placeholder="—" '+
          'style="width:120px;text-align:right;padding:7px 9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit"'+
          (saved[c.key]!=null?' value="'+saved[c.key]+'"':'')+'></td>';
        rows.appendChild(tr);
      }});
      function tl(n){{return (Math.round(n*100)/100).toLocaleString('tr-TR',{{minimumFractionDigits:2}});}}
      function recalc(){{
        var vals={{}}, store={{}};
        document.querySelectorAll('#prows input').forEach(function(i){{
          var v=parseFloat(i.value); if(!isNaN(v)){{vals[i.dataset.k]=v; store[i.dataset.k]=i.value;}}
        }});
        try{{localStorage.setItem(KEY,JSON.stringify(store));}}catch(e){{}}
        var direct=vals['kapidan'];
        var nums=Object.values(vals); var cheap=nums.length?Math.min.apply(null,nums):null;
        var viol=0;
        CH.forEach(function(c){{
          var tr=document.getElementById('row-'+c.key); var v=vals[c.key];
          tr.className='';
          var td=tr.children[0];
          td.innerHTML=c.name;
          if(v==null) return;
          if(cheap!=null && Math.abs(v-cheap)<0.5) td.innerHTML+=' <span style="color:#16a34a;font-weight:700">· en ucuz</span>';
          if(c.key!=='kapidan' && direct!=null && v<direct-0.5){{ td.innerHTML+=' <span style="color:#dc2626;font-weight:700">· kapıdandan ucuz!</span>'; tr.className='bad'; viol++; }}
        }});
        document.getElementById('psum').innerHTML=
          "<div class='stat'><div class='n'>"+(direct!=null?tl(direct)+' ₺':'—')+"</div><div class='l'>kapıdan</div></div>"+
          "<div class='stat'><div class='n'>"+(cheap!=null?tl(cheap)+' ₺':'—')+"</div><div class='l'>en ucuz</div></div>"+
          "<div class='stat "+(viol?'bad':'ok')+"'><div class='n'>"+viol+"</div><div class='l'>parite ihlali</div></div>";
      }}
      document.querySelectorAll('#prows input').forEach(function(i){{i.addEventListener('input',recalc);}});
      recalc();
    }})();
    </script>"""
    return {"label": "Parite Kontrolü", "count": 0, "count_label": "günlük gir",
            "tone": "ok", "sub": "bugünkü OTA + kapıdan fiyatları · parite ihlali kontrolü",
            "updated": now_str(),
            "html": PAGE("Fiyat / Parite", "Parite Kontrolü", "kanal fiyatlarını gir → parite", body)}
