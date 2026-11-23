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
import json
from collections import Counter, defaultdict, OrderedDict

import elektra_api as E
from zoneinfo import ZoneInfo

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
/* Renkler tek yerde değişken olarak. Gündüz = :root. Gece: OS karanlıksa VE kullanıcı
   'aydınlık'a zorlamadıysa, ya da düğmeyle 'dark' seçildiyse. Böylece shell'deki
   gündüz/gece düğmesi (html[data-theme=...]) bu iframe'e de işler. */
:root{
  --bg:#f4f6f9;--fg:#0f172a;--eyebrow:#0e7490;--sub:#64748b;--card:#fff;--border:#e2e8f0;
  --statbad:#dc2626;--statok:#16a34a;--tbl:#fff;--th-bg:#f1f5f9;--th-fg:#475569;--td-line:#eef2f7;
  --who-bg:#eef2ff;--who-fg:#4338ca;--empty-bg:#f0fdf4;--empty-line:#bbf7d0;--empty-fg:#166534;
  --input-bg:#fff;--input-line:#cbd5e1;
}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
  --bg:#0b1120;--fg:#e8eef7;--eyebrow:#22b8cf;--sub:#94a3b8;--card:#111a2e;--border:#243049;
  --statbad:#f87171;--statok:#4ade80;--tbl:#111a2e;--th-bg:#182338;--th-fg:#94a3b8;--td-line:#1e2a44;
  --who-bg:#1e2450;--who-fg:#a5b4fc;--empty-bg:#0f2417;--empty-line:#14532d;--empty-fg:#4ade80;
  --input-bg:#0b1120;--input-line:#334155;
}}
:root[data-theme=dark]{
  --bg:#0b1120;--fg:#e8eef7;--eyebrow:#22b8cf;--sub:#94a3b8;--card:#111a2e;--border:#243049;
  --statbad:#f87171;--statok:#4ade80;--tbl:#111a2e;--th-bg:#182338;--th-fg:#94a3b8;--td-line:#1e2a44;
  --who-bg:#1e2450;--who-fg:#a5b4fc;--empty-bg:#0f2417;--empty-line:#14532d;--empty-fg:#4ade80;
  --input-bg:#0b1120;--input-line:#334155;
}
body{margin:0;font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif;
  color:var(--fg);background:var(--bg);padding:22px}
.wrap{max-width:1600px;margin:0 auto}
.eyebrow{color:var(--eyebrow);font-weight:700;font-size:12px;letter-spacing:.4px;text-transform:uppercase}
h1{font-size:22px;margin:4px 0 2px}
.sub{color:var(--sub);font-size:13px;margin-bottom:18px}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}
.stat{background:var(--card);border:1px solid var(--border);border-radius:13px;padding:14px 18px;min-width:130px;flex:1}
.stat .n{font-size:24px;font-weight:800}
.stat .l{color:var(--sub);font-size:12px;margin-top:2px}
.stat.bad .n{color:var(--statbad)}.stat.ok .n{color:var(--statok)}
table{width:100%;border-collapse:collapse;margin:10px 0 22px;font-size:13px;background:var(--tbl);border-radius:12px;overflow:hidden}
th{background:var(--th-bg);text-align:left;padding:9px 11px;font-size:11.5px;text-transform:uppercase;letter-spacing:.3px;color:var(--th-fg)}
td{padding:9px 11px;border-top:1px solid var(--td-line)}
.r{text-align:right;font-variant-numeric:tabular-nums}
.who{display:inline-block;background:var(--who-bg);color:var(--who-fg);border-radius:6px;padding:1px 7px;font-size:11.5px;font-weight:600}
.bad td:first-child{box-shadow:inset 3px 0 var(--statbad)}
.money{font-weight:700;font-variant-numeric:tabular-nums}
h2{font-size:15px;margin:22px 0 4px}
.lead{color:var(--sub);font-size:12.5px;margin:0 0 8px}
.empty{background:var(--empty-bg);border:1px solid var(--empty-line);color:var(--empty-fg);border-radius:11px;padding:14px 16px;font-weight:600}
.note{color:var(--sub);font-size:11.5px;margin-top:18px;line-height:1.6}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px}
.card h3{margin:0 0 10px;font-size:13.5px}
input,select,textarea{font:inherit;padding:9px 11px;border:1px solid var(--input-line);border-radius:9px;background:var(--input-bg);color:var(--fg)}
input{width:100%}
select{max-width:100%;cursor:pointer}
select option{background:var(--card);color:var(--fg)}
label{font-size:12px;color:var(--sub);display:block;margin:8px 0 3px}
.vrow{display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid var(--td-line)}
.match{color:var(--statok);font-weight:700}.miss{color:var(--statbad);font-weight:700}
"""


def PAGE(eyebrow, title, sub, body):
    return (f"<!doctype html><html lang='tr'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{esc(title)}</title><style>{PAGE_CSS}</style>{CHART_CSS}</head><body><div class='wrap'>"
            + (f"<div class='eyebrow'>{esc(eyebrow)}</div><h1>{esc(title)}</h1><div class='sub'>{esc(sub)}</div>"
               if eyebrow is not None else "")
            + f"{body}</div></body></html>")


def stat(n, label, tone=""):
    return f"<div class='stat {tone}'><div class='n'>{n}</div><div class='l'>{esc(label)}</div></div>"


def empty_ok(msg):
    return f"<div class='empty'>✓ {esc(msg)}</div>"


# --------------------------------------------------------------------------- svg charts
INK = "#0e7490"


# 20.11.2026: grafikler küçük ve sabit yükseklikte (sahibinin isteği). Eskiden SVG
# viewBox ile genişliğe göre ölçekleniyordu; geniş ekranda tek grafik ekranı
# kaplıyordu. Şimdi HTML/CSS: yükseklik piksel olarak sabit, eksende 0 + 3 ara çizgi,
# çubuk üstünde kısa değer ("3,8 mn"), üzerine gelince tam değer (title).
CHART_CSS = """<style>
.ch{--h:150px;--bar:#0e7490;--bar2:#9fd3dc;position:relative}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .ch{--bar:#22b8cf;--bar2:#1e4f5c}}
:root[data-theme=dark] .ch{--bar:#22b8cf;--bar2:#1e4f5c}
.ch-plot{position:relative;height:var(--h);margin:14px 0 0 48px}
.ch-gl{position:absolute;left:0;right:0;border-top:1px dashed var(--border);height:0}
.ch-gl.z{border-top:1px solid var(--border)}
.ch-gl span{position:absolute;right:calc(100% + 7px);top:-7px;font-size:10px;line-height:1;color:var(--sub);white-space:nowrap}
.ch-cols{position:absolute;inset:0;display:flex;align-items:stretch;gap:var(--gap,6px)}
.ch-c{flex:1 1 0;min-width:0;display:flex;flex-direction:column;justify-content:flex-end;align-items:center;position:relative}
.ch-c b{display:block;width:100%;max-width:42px;background:var(--bar);border-radius:3px 3px 0 0;min-height:1px}
.ch-c.cur b{background:var(--bar2);outline:1px dashed var(--bar);outline-offset:-1px}
.ch-c:hover b{filter:brightness(1.15)}
.ch-v{font-style:normal;font-size:10px;font-weight:700;color:var(--sub);white-space:nowrap;margin-bottom:3px;line-height:1}
.ch.dense .ch-v{position:absolute;bottom:calc(var(--y) + 4px);opacity:0;background:var(--fg);color:var(--bg);
  padding:3px 6px;border-radius:5px;z-index:2;pointer-events:none}
.ch.dense .ch-c:hover .ch-v{opacity:1}
.ch-x{display:flex;gap:var(--gap,6px);margin:5px 0 0 48px}
.ch-x span{flex:1 1 0;min-width:0;text-align:center;font-size:10px;color:var(--sub);white-space:nowrap;overflow:visible}
.ch svg.ln{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.ch-p{position:absolute;width:7px;height:7px;margin:0 0 -3.5px -3.5px;border-radius:50%;background:var(--card);
  border:2px solid var(--bar);box-sizing:border-box}
.ch-hit{position:absolute;top:0;bottom:0}
.ch-hit:hover{background:rgba(14,116,144,.07)}
.ch-hit:hover + .ch-p{transform:scale(1.5)}
.ch-x em{font-style:normal}
@media (max-width:600px){.ch-x em{display:none}.ch-v{font-size:8.5px}.ch-x span{font-size:9px}}
.ch-leg{font-size:11px;color:var(--sub);margin-top:6px}
.ch-leg i{display:inline-block;width:10px;height:10px;border-radius:2px;vertical-align:-1px;margin-right:4px}
</style>"""


def kisa(v, unit=""):
    """Eksen/çubuk etiketi için kısa sayı: 4711383 -> '4,7 mn', 985000 -> '985 bin'."""
    u = unit.strip()
    if u == "%":
        return f"%{v:.0f}"
    a = abs(v)
    if a >= 1e6:
        s = f"{v / 1e6:.1f}".replace(".", ",").replace(",0", "") + " mn"
    elif a >= 1e4:
        s = f"{v / 1e3:.0f} bin"
    elif a >= 1e3:
        s = f"{v / 1e3:.1f}".replace(".", ",").replace(",0", "") + " bin"
    else:
        s = f"{v:.0f}"
    return s + (f" {u}" if u else "")


def _nice(x):
    """x'i 1-2-2,5-5 ×10^k'ya yukarı yuvarla (eksen üst sınırı)."""
    import math
    if x <= 0:
        return 1
    e = 10 ** math.floor(math.log10(x))
    for f in (1, 2, 2.5, 5, 10):
        if x <= f * e + 1e-9:
            return f * e
    return 10 * e


def _grid(lo, hi, unit, steps=4):
    out = []
    for i in range(steps + 1):
        v = lo + (hi - lo) * i / steps
        p = (v - lo) / (hi - lo) * 100 if hi > lo else 0
        out.append(f"<div class='ch-gl{' z' if i == 0 else ''}' style='bottom:{p:.2f}%'>"
                   f"<span>{esc(kisa(v, unit))}</span></div>")
    return "".join(out)


def _xlabels(labels, every):
    return "<div class='ch-x'>" + "".join(
        f"<span>{_xl(l) if (i % every == 0) else ''}</span>" for i, l in enumerate(labels)) + "</div>"


def _xl(l):
    """'Ara 25' -> 'Ara<em> 25</em>': telefonda yıl gizlenir, etiketler üst üste binmesin."""
    a, _, b = str(l).partition(" ")
    return esc(a) + (f"<em> {esc(b)}</em>" if b else "")


def svg_bars(labels, values, unit="", height=150, fmt=None, partial_last=False):
    """Dikey çubuk grafik (HTML/CSS, sabit yükseklik). partial_last: son çubuk henüz
    bitmemiş dönem (bu ay) — açık renk + kesikli çerçeve."""
    fmt = fmt or (lambda v: f"{v:.0f}")
    n = len(values)
    if not n:
        return "<div class='lead'>veri yok</div>"
    hi = _nice(max(values + [0]) * 1.08)
    dense = n > 13
    cols = []
    for i, v in enumerate(values):
        p = max(0.0, v) / hi * 100
        cur = " cur" if (partial_last and i == n - 1) else ""
        cols.append(f"<div class='ch-c{cur}' style='--y:{p:.2f}%' title='{esc(labels[i])}: "
                    f"{esc(fmt(v))}{esc(unit if unit.strip() != '%' else '%')}'>"
                    f"<i class='ch-v'>{esc(kisa(v, '%' if unit.strip() == '%' else ''))}</i><b style='height:{p:.2f}%'></b></div>")
    gap = 6 if n <= 13 else (3 if n <= 31 else 1)
    every = 1 if n <= 16 else max(1, round(n / 10))
    return (f"<div class='ch{' dense' if dense else ''}' style='--h:{height}px;--gap:{gap}px'>"
            f"<div class='ch-plot'>{_grid(0, hi, unit)}<div class='ch-cols'>{''.join(cols)}</div></div>"
            f"{_xlabels(labels, every)}</div>")


def ch_bars2(labels, a, b, height=150, renk=("#16a34a", "#dc2626")):
    """İki serili (yan yana) çubuk grafik — ör. bankaya giren / çıkan."""
    n = len(labels)
    if not n:
        return "<div class='lead'>veri yok</div>"
    hi = _nice(max(list(a) + list(b) + [0]) * 1.08)
    cols = []
    for i in range(n):
        pa, pb = max(0.0, a[i]) / hi * 100, max(0.0, b[i]) / hi * 100
        cols.append(
            f"<div class='ch-c' style='flex-direction:row;align-items:flex-end;gap:2px'>"
            f"<b style='height:{pa:.2f}%;background:{renk[0]};max-width:22px' title='{esc(labels[i])}: {tl(a[i])}'></b>"
            f"<b style='height:{pb:.2f}%;background:{renk[1]};max-width:22px' title='{esc(labels[i])}: {tl(b[i])}'></b></div>")
    return (f"<div class='ch' style='--h:{height}px;--gap:10px'>"
            f"<div class='ch-plot'>{_grid(0, hi, '')}<div class='ch-cols'>{''.join(cols)}</div></div>"
            f"{_xlabels(labels, 1)}</div>")


def svg_line(labels, values, unit="", height=150, fmt=None):
    """Çizgi grafik: sabit yükseklik; eksen veriye göre (0'dan değil) — fiyat gibi
    seriler için. Noktalar HTML (bozulmasın diye), çizgi SVG (non-scaling-stroke)."""
    fmt = fmt or (lambda v: f"{v:.0f}")
    n = len(values)
    if not n:
        return "<div class='lead'>veri yok</div>"
    pos = [v for v in values if v] or [0]
    mn, mx = min(pos), max(pos)
    span = _nice(((mx - mn) or mx or 1) * 1.25 / 4) * 4
    lo = max(0.0, (mn // (span / 4)) * (span / 4))
    hi = lo + span
    while hi < mx:
        hi += span / 4
    def xy(i, v):
        return ((i + .5) / n * 100, (v - lo) / (hi - lo) * 100 if hi > lo else 0)
    pts = [xy(i, v) for i, v in enumerate(values) if v]
    poly = " ".join(f"{x * 10:.1f},{1000 - y * 10:.1f}" for x, y in pts)
    area = (f"{pts[0][0] * 10:.1f},1000 {poly} {pts[-1][0] * 10:.1f},1000" if pts else "")
    hits, dots = [], []
    w = 100 / n
    for i, v in enumerate(values):
        if not v:
            continue
        x, y = xy(i, v)
        t = f"{esc(labels[i])}: {esc(fmt(v))}{esc(unit)}"
        hits.append(f"<div class='ch-hit' style='left:{x - w / 2:.2f}%;width:{w:.2f}%' title='{t}'></div>")
        dots.append(f"<div class='ch-p' style='left:{x:.2f}%;bottom:{y:.2f}%' title='{t}'></div>")
    svg = (f"<svg class='ln' viewBox='0 0 1000 1000' preserveAspectRatio='none'>"
           f"<polygon points='{area}' fill='var(--bar)' opacity='.08'/>"
           f"<polyline points='{poly}' fill='none' stroke='var(--bar)' stroke-width='2' "
           f"vector-effect='non-scaling-stroke' stroke-linejoin='round'/></svg>")
    every = 1 if n <= 16 else max(1, round(n / 10))
    return (f"<div class='ch' style='--h:{height}px;--gap:0px'><div class='ch-plot'>"
            f"{_grid(lo, hi, unit)}{svg}{''.join(h + d for h, d in zip(hits, dots))}</div>"
            f"{_xlabels(labels, every)}</div>")


def svg_donut(value, total, center_label):
    pct = (value / total) if total else 0
    r, c = 52, 60
    circ = 2 * 3.14159 * r
    off = circ * (1 - pct)
    return (f"<svg viewBox='0 0 120 120' style='width:124px;height:124px'>"
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
            f"<div style='height:8px;background:var(--th-bg);border-radius:5px;margin-top:3px'>"
            f"<div style='height:8px;width:{pct:.1f}%;background:{INK};border-radius:5px'></div></div></div>")
    return "".join(rows)


# --------------------------------------------------------------------------- 1) Kasa & POS
KASA_EXTRA_CSS = """<style>
textarea{width:100%;font:12px/1.4 ui-monospace,Menlo,monospace;padding:10px;border:1px solid var(--input-line);
  border-radius:10px;background:var(--input-bg);color:var(--fg);resize:vertical}
.btnrow{display:flex;gap:10px;align-items:center;margin:10px 0 4px;flex-wrap:wrap}
.btn{font:inherit;font-weight:700;padding:9px 16px;border-radius:10px;border:1px solid #0e7490;
  background:#0e7490;color:#fff;cursor:pointer}
.btn.ghost{background:transparent;color:#0e7490}
label.btn{display:inline-block}
.muted{color:#94a3b8;font-size:12px}
.drop{border:2px dashed #93c5c9;border-radius:14px;padding:22px 16px;text-align:center;
  display:flex;flex-direction:column;gap:8px;align-items:center;background:#f0fbfc;color:#0e7490}
@media (prefers-color-scheme:dark){.drop{background:#0c1a24;border-color:#1f4a52}}
.drop.over{background:#dcf5f8;border-color:#0e7490}
.drop-ic{font-size:30px}
.recon{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:16px;margin:14px 0}
.recon h3{margin:0 0 4px;font-size:15px}
.ok{color:#16a34a}.warn{color:#dc2626}.amber{color:#d97706}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:700;margin-left:6px}
.pill.ok{background:#dcfce7;color:#166534}.pill.warn{background:#fee2e2;color:#991b1b}
.pill.amber{background:#fef3c7;color:#92400e}
@media (prefers-color-scheme:dark){.pill.ok{background:#0f2417;color:#4ade80}
  .pill.warn{background:#3a1414;color:#f87171}.pill.amber{background:#3a2a0e;color:#fbbf24}}
</style>"""

# Client-side POS/bank reconciliation, per currency. recon core = pure logic: read an
# uploaded .xlsx (native unzip via DecompressionStream, no library) OR pasted text,
# detect the account currency ("Döviz Cinsi"), categorise rows, and match Elektra card
# vs bank POS with T+1 alignment + commission-add-back. render = DOM + multi-file upload.
# Both node-tested against generated xlsx (TL + EUR) reproducing a real Akbank export.
KASA_RECON_JS = r"""<script>
// Pure core v2: reads pasted text OR an .xlsx file (native, no library), per-currency.
(function(root){
  function parseNum(s){
    s = String(s==null?'':s).replace(/\s/g,'').replace(/[^0-9.\-]/g,'');
    var v = parseFloat(s); return isNaN(v)?0:v;   // bank data: US format 1,234.56
  }
  function toISO(v){
    if(v==null) return null;
    var s=String(v).trim();
    var m=s.match(/(\d{2})\.(\d{2})\.(\d{4})/); if(m) return m[3]+'-'+m[2]+'-'+m[1];
    if(/^\d+(\.\d+)?$/.test(s)){ var n=parseFloat(s);           // Excel serial date
      if(n>20000 && n<80000){ var d=new Date(Date.UTC(1899,11,30)+Math.round(n)*86400000); return d.toISOString().slice(0,10); } }
    return null;
  }
  function splitLine(line){
    if(line.indexOf('\t')>=0) return line.split('\t');
    var out=[], cur='', q=false;
    for(var i=0;i<line.length;i++){ var ch=line[i];
      if(ch==='"'){ q=!q; } else if(ch===',' && !q){ out.push(cur); cur=''; } else cur+=ch; }
    out.push(cur); return out;
  }
  function textToCells(text){
    return String(text).split(/\r?\n/).filter(function(l){return l.trim();})
      .map(function(l){ return splitLine(l).map(function(x){return x.trim().replace(/^"|"$/g,'');}); });
  }
  function colToIdx(ref){ var m=ref.match(/^[A-Z]+/); if(!m) return 0; var s=m[0],n=0;
    for(var i=0;i<s.length;i++){ n=n*26+(s.charCodeAt(i)-64); } return n-1; }
  function unesc(s){ return String(s).replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&apos;/g,"'").replace(/&amp;/g,'&'); }

  async function inflate(u8){
    var ds = new DecompressionStream('deflate-raw');
    var body = new Response(u8).body.pipeThrough(ds);
    var ab = await new Response(body).arrayBuffer();
    return new Uint8Array(ab);
  }
  async function unzip(buf){
    var u8 = new Uint8Array(buf), dv = new DataView(buf);
    var i = buf.byteLength - 22;
    while(i>=0 && dv.getUint32(i,true)!==0x06054b50) i--;
    if(i<0) throw new Error('xlsx okunamadı (ZIP değil)');
    var cdOff = dv.getUint32(i+16,true), cnt = dv.getUint16(i+10,true), entries={}, p=cdOff;
    for(var n=0;n<cnt;n++){
      if(dv.getUint32(p,true)!==0x02014b50) break;
      var method=dv.getUint16(p+10,true), compSize=dv.getUint32(p+20,true),
          nameLen=dv.getUint16(p+28,true), extraLen=dv.getUint16(p+30,true),
          commentLen=dv.getUint16(p+32,true), localOff=dv.getUint32(p+42,true);
      var name=new TextDecoder().decode(u8.subarray(p+46,p+46+nameLen));
      entries[name]={method:method,compSize:compSize,localOff:localOff};
      p += 46+nameLen+extraLen+commentLen;
    }
    async function read(name){
      var e=entries[name]; if(!e) return null;
      var lh=e.localOff, lNameLen=dv.getUint16(lh+26,true), lExtraLen=dv.getUint16(lh+28,true);
      var start=lh+30+lNameLen+lExtraLen, comp=u8.subarray(start,start+e.compSize);
      return e.method===0 ? comp : await inflate(comp);
    }
    return {names:Object.keys(entries), read:read};
  }
  async function readXlsx(buf){
    var zip=await unzip(buf), dec=new TextDecoder();
    var ssName=zip.names.find(function(n){return /xl\/sharedStrings\.xml$/.test(n);});
    var shared=[];
    if(ssName){ var sx=dec.decode(await zip.read(ssName));
      shared=(sx.match(/<si[\s\S]*?<\/si>/g)||[]).map(function(si){
        var ts=si.match(/<t[^>]*>([\s\S]*?)<\/t>/g)||[];
        return ts.map(function(t){return t.replace(/<[^>]+>/g,'');}).join('');
      }).map(unesc);
    }
    var wsName=zip.names.filter(function(n){return /xl\/worksheets\/sheet\d+\.xml$/.test(n);}).sort()[0];
    var wx=dec.decode(await zip.read(wsName)), cells2d=[];
    (wx.match(/<row[\s\S]*?<\/row>/g)||[]).forEach(function(rowXml){
      var cells=[], re=/<c ([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g, m;
      while(m=re.exec(rowXml)){
        var attr=m[1], inner=m[2]||'';
        var rm=attr.match(/r="([A-Z]+\d+)"/); var col=rm?colToIdx(rm[1]):cells.length;
        var tm=attr.match(/t="([^"]+)"/); var t=tm?tm[1]:'';
        var vm=inner.match(/<v>([\s\S]*?)<\/v>/); var val='';
        if(t==='s'){ val=shared[parseInt(vm?vm[1]:'-1',10)]||''; }
        else if(t==='inlineStr'){ var im=inner.match(/<t[^>]*>([\s\S]*?)<\/t>/); val=im?unesc(im[1]):''; }
        else { val=vm?vm[1]:''; }
        cells[col]=val;
      }
      cells2d.push(cells);
    });
    return cells2d;
  }
  function currencyOf(cells){
    for(var i=0;i<cells.length;i++){ var r=cells[i]||[];
      for(var j=0;j<r.length;j++){ if(r[j] && /Döviz\s*Cinsi/i.test(r[j])){
        var c=(r[j+1]||'').trim().toUpperCase(); if(c) return c==='TRY'?'TL':c; } } }
    return 'TL';
  }
  function rowsFromCells(cells){
    var out=[];
    for(var i=0;i<cells.length;i++){ var r=cells[i]||[];
      var d=toISO(r[0]); if(!d) continue;
      var amt=parseNum(r[2]); var ba=(r[4]||'').trim().toUpperCase();
      if(ba!=='A'&&ba!=='B') ba=amt<0?'B':'A';
      var desc=((r[5]||'')+' '+(r[6]||'')).trim();
      out.push({d:d, amt:Math.abs(amt), ba:ba, desc:desc});
    }
    return {currency:currencyOf(cells), rows:out};
  }
  async function readFile(nameLower, bytesOrText){
    // xlsx => ArrayBuffer/Uint8Array; text/csv => string
    if(/\.xlsx$/.test(nameLower) || (bytesOrText && bytesOrText.byteLength!=null)){
      var buf = bytesOrText.buffer ? bytesOrText.buffer : bytesOrText;
      return rowsFromCells(await readXlsx(buf));
    }
    return rowsFromCells(textToCells(String(bytesOrText)));
  }

  function catOf(desc){
    var u=desc.toUpperCase().split('İ').join('I').split('Ş').join('S');
    if(u.indexOf('AKPOS')>=0 || u.indexOf('APOS ')>=0 || u.indexOf('POS PES')>=0) return 'POS';
    if(u.indexOf('EURO KARSILIGI')>=0 || u.indexOf('EURO KAR')>=0) return 'DOVIZ';
    if(u.indexOf('FAST')>=0 || u.indexOf('EFT')>=0) return 'EFT';
    if(u.indexOf('HAV.')>=0 || u.indexOf('HAVALE')>=0) return 'HAVALE';
    return 'DIGER';
  }
  function ksOf(desc){ var m=desc.match(/KS:\s*([0-9.,]+)\s*(?:TL|EUR|USD)/i); return m?parseNum(m[1]):0; }
  function senderOf(desc){
    var s=desc.replace(/^\s*\d+\s*/,'');
    var m=s.match(/(?:EFT:|FAST:|HAV\.|HAVALE)\s*([^_]+?)(?:\s{2,}|_|PN\d|VO\d|$)/i);
    return (m?m[1]:s).replace(/\s+/g,' ').trim().slice(0,34);
  }
  function addDays(iso,delta){ var p=iso.split('-'); var d=new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));
    d.setUTCDate(d.getUTCDate()+delta); return d.toISOString().slice(0,10); }

  function reconcile(rows, days, currency){
    days=days||{}; var CUR=(currency==='TL'?'TRY':currency)||'TRY';
    var key = CUR==='TRY'?'cardTRY':(CUR==='EUR'?'cardEUR':(CUR==='USD'?'cardUSD':null));
    var inc=rows.filter(function(r){return r.ba==='A';});
    var dates=inc.map(function(r){return r.d;}).sort();
    if(!dates.length) return null;
    var bMin=dates[0], bMax=dates[dates.length-1];
    var posDay={}, posGross=0, posKs=0, eft=0, hav=0, doviz=0, senders={};
    inc.forEach(function(r){
      var c=catOf(r.desc);
      if(c==='POS'){ var k=ksOf(r.desc); var g=r.amt+k; posDay[r.d]=(posDay[r.d]||0)+g; posGross+=g; posKs+=k; }
      else if(c==='DOVIZ'){ doviz+=r.amt; }
      else if(c==='EFT'){ eft+=r.amt; var s=senderOf(r.desc); senders[s]=(senders[s]||0)+r.amt; }
      else if(c==='HAVALE'){ hav+=r.amt; var s2=senderOf(r.desc); senders[s2]=(senders[s2]||0)+r.amt; }
    });
    // Elektra is baked only for [startKey .. ]; a bank day whose T+1 source day is before
    // that is UNCOMPARABLE (we simply don't have that day's Elektra card). Mark it unknown,
    // show "—", and leave it out of the totals/verdict so a data gap never reads as "missing".
    var startKey = Object.keys(days).sort()[0] || '9999';
    var tbl=[], elCardSum=0, posComp=0, d=bMin;
    while(d<=bMax){
      var elDay=addDays(d,-1), bankPos=posDay[d]||0;
      var known = !!key && elDay>=startKey && !!days[elDay];
      var elCard = known ? (days[elDay][key]||0) : null;
      tbl.push({bankDay:d, elDay:elDay, elCard:elCard, bankPos:bankPos,
                unknown:!known, diff: known ? elCard-bankPos : null});
      if(known){ elCardSum+=elCard; posComp+=bankPos; }
      d=addDays(d,1);
    }
    return {currency:CUR, hasEl:!!key, bMin:bMin, bMax:bMax, posGross:posGross, posKs:posKs,
            elCardSum:elCardSum, posComp:posComp, tbl:tbl, eft:eft, hav:hav, doviz:doviz, senders:senders};
  }
  var api={parseNum:parseNum,toISO:toISO,textToCells:textToCells,readXlsx:readXlsx,
           rowsFromCells:rowsFromCells,readFile:readFile,reconcile:reconcile,catOf:catOf};
  if(typeof module!=='undefined' && module.exports) module.exports=api; else root.RECON=api;
})(typeof window!=='undefined'?window:this);
</script>
<script>
// Render + multi-file upload wiring. Uses window.RECON (recon2 core) + window.__KASA__.
(function(){
  var R = window.RECON, KASA = window.__KASA__ || {days:{}};
  var $ = function(id){ return document.getElementById(id); };
  var LS = 'kasa-bank-files-v2';
  var state = {};   // currency -> {rows, name}
  function f(n){ return (Math.round(n*100)/100).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2}); }
  function trg(iso){ var p=iso.split('-'); var M=['','Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara']; return (+p[2])+' '+M[+p[1]]; }
  function esc(s){ return String(s).replace(/[&<>]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;'}[c];}); }
  function sym(c){ return c==='TL'?'₺':(c==='EUR'?'€':(c==='USD'?'$':c)); }
  function curName(c){ return c==='TL'?'TL (₺)':(c==='EUR'?'EUR (€)':(c==='USD'?'USD ($)':c)); }

  function renderCurrency(rec){
    // DİKKAT: reconcile() para birimini 'TL' -> 'TRY' diye döndürür. Eskiden buradaki tüm
    // rec.currency==='TL' kontrolleri bu yüzden HİÇ tutmuyordu: TL hesabı 💵 + "TRY" diye
    // görünüyor, eşikler de yanlış (EUR) daldan seçiliyordu. Tek yerde normalize ediyoruz.
    var C = (rec.currency==='TRY' ? 'TL' : rec.currency);
    var s = sym(C);
    var out = "<div class='recon'><h3>"+(C==='TL'?'💳':(C==='EUR'?'💶':'💵'))
      + " POS / Kredi Kartı — "+curName(C);
    if(rec.hasEl){
      // fark = Elektra − Banka.  + : Elektra'da var, bankaya GEÇMEMİŞ.  − : bankaya FAZLA geçmiş.
      // ESKİ HATA: tolerans %5 (362 bin ₺'de ~18 bin ₺!) ve kontrol TEK YÖNLÜYDÜ (diff<=tol),
      // yani hem büyük eksikler hem de bankaya fazla geçen para "✓ Tüm POS geçmiş" görünüyordu.
      // Ayrıca gün bazındaki sapmalar toplamda netleşince tamamen gizleniyordu.
      var diff = rec.elCardSum - rec.posComp;
      var tol = Math.max(rec.elCardSum*0.005, C==='TL'?250:25);
      var dayTol = (C==='TL'?1000:50);
      var offDays = rec.tbl.filter(function(t){ return !t.unknown && Math.abs(t.diff)>dayTol; });
      var worst = offDays.slice().sort(function(a,b){ return Math.abs(b.diff)-Math.abs(a.diff); })[0];
      var badge, lead;
      if(Math.abs(diff)<=tol && !offDays.length){
        badge = "<span class='pill ok'>✓ Eşleşiyor</span>";
        lead = "Hem toplamda hem gün bazında bankaya geçen POS, Elektra'daki kart tahsilatını karşılıyor.";
      } else if(diff > tol){
        badge = "<span class='pill warn'>⚠ "+f(diff)+" "+s+" bankaya geçmemiş</span>";
        lead = "Elektra'da <b>"+f(diff)+" "+s+"</b> kart tahsilatı görünüyor ama bankaya geçen POS'ta yok — <b>incele</b>.";
      } else if(diff < -tol){
        badge = "<span class='pill warn'>⚠ "+f(-diff)+" "+s+" fazla geçmiş</span>";
        lead = "Bankaya, Elektra'daki kart tahsilatından <b>"+f(-diff)+" "+s+" FAZLA</b> para geçmiş — "
             + "Elektra'ya işlenmemiş tahsilat ya da tarih kayması olabilir; <b>incele</b>.";
      } else {
        badge = "<span class='pill warn'>⚠ günler tutmuyor</span>";
        lead = "Toplam örtüşüyor ama gün bazında sapma var — tarih eşleşmesi (T+1) ya da kayıt zamanlaması kaymış olabilir.";
      }
      if(offDays.length){
        lead += " <b>"+offDays.length+"</b> günde gün-bazında fark var"
             + (worst ? " (en büyüğü "+trg(worst.bankDay)+": "+(worst.diff>=0?'+':'')+f(worst.diff)+" "+s+")" : "")
             + " — aşağıdaki tabloda işaretli.";
      }
      out += " "+badge+"</h3><p class='lead'>"+lead+"</p>";
      out += "<div class='stats'>"
        + "<div class='stat'><div class='n'>"+f(rec.elCardSum)+" "+s+"</div><div class='l'>Elektra kart (karşılaştırılan)</div></div>"
        + "<div class='stat'><div class='n'>"+f(rec.posComp)+" "+s+"</div><div class='l'>Banka POS (aynı günler, brüt)</div></div>"
        + "<div class='stat "+(Math.abs(diff)<=tol?'':'bad')+"'><div class='n'>"+(diff>=0?'+':'')+f(diff)+" "+s+"</div><div class='l'>fark (Elektra − Banka)</div></div>"
        + "<div class='stat'><div class='n'>"+f(rec.posKs)+" "+s+"</div><div class='l'>banka komisyonu (toplam)</div></div></div>";
      var rowsH='';
      rec.tbl.forEach(function(t){
        if(t.unknown){
          rowsH += "<tr><td>"+trg(t.bankDay)+"</td><td class='muted'>"+trg(t.elDay)+"</td>"
            +"<td class='r muted'>—</td><td class='r money'>"+f(t.bankPos)+"</td>"
            +"<td class='r muted' title='Bu güne ait Elektra verisi yüklü aralıkta yok'>karşılaştırma dışı</td></tr>";
          return;
        }
        var cls=Math.abs(t.diff)<1?'ok':(Math.abs(t.diff)>=dayTol?'amber':'');
        rowsH += "<tr><td>"+trg(t.bankDay)+"</td><td class='muted'>"+trg(t.elDay)+"</td>"
          +"<td class='r money'>"+f(t.elCard)+"</td><td class='r money'>"+f(t.bankPos)+"</td>"
          +"<td class='r "+cls+"'>"+(t.diff>=0?'+':'')+f(t.diff)+"</td></tr>"; });
      out += "<table><tr><th>Banka günü</th><th>Elektra günü</th><th class='r'>Elektra kart</th>"
        +"<th class='r'>Banka POS</th><th class='r'>fark</th></tr>"+rowsH+"</table>";
    } else {
      out += "</h3><p class='lead'>Bu para birimi için Elektra'da kart tahsilatı yok — yalnızca bankaya geçen POS gösteriliyor.</p>"
        + "<div class='stats'><div class='stat'><div class='n'>"+f(rec.posGross)+" "+s+"</div><div class='l'>Banka POS brüt</div></div>"
        + "<div class='stat'><div class='n'>"+f(rec.posKs)+" "+s+"</div><div class='l'>komisyon</div></div></div>";
    }
    // extra incoming (agency / conversions) if any
    if(rec.doviz>0.5 || (rec.eft+rec.hav)>0.5){
      out += "<div class='stats'>";
      if(rec.doviz>0.5) out += "<div class='stat'><div class='n'>"+f(rec.doviz)+" "+s+"</div><div class='l'>'Euro/döviz karşılığı' yatan</div></div>";
      if((rec.eft+rec.hav)>0.5) out += "<div class='stat'><div class='n'>"+f(rec.eft+rec.hav)+" "+s+"</div><div class='l'>EFT/FAST + havale (gelen)</div></div>";
      out += "</div>";
      var send=Object.keys(rec.senders).map(function(k){return [k,rec.senders[k]];}).sort(function(a,b){return b[1]-a[1];});
      if(send.length){ var sH='';
        send.slice(0,12).forEach(function(x){ sH+="<tr><td>"+esc(x[0])+"</td><td class='r money'>"+f(x[1])+" "+s+"</td></tr>"; });
        out += "<div class='note'>Gelen havaleler (gönderene göre) — 'Kasa karşılığı' = otelin bankaya yatırdığı nakit:</div>"
          + "<table><tr><th>Gönderen</th><th class='r'>Tutar</th></tr>"+sH+"</table>";
      }
    }
    return out + "</div>";
  }

  function renderAll(){
    var curs = Object.keys(state);
    if(!curs.length){ $('results').innerHTML=''; $('fileList').innerHTML=''; return; }
    $('fileList').innerHTML = "Yüklü: " + curs.map(function(c){return "<span class='pill ok'>"+curName(c)+" · "+esc(state[c].name||'')+"</span>";}).join(' ');
    var order=['TL','EUR','USD']; curs.sort(function(a,b){ return (order.indexOf(a)+9)%99 - (order.indexOf(b)+9)%99; });
    var out='';
    curs.forEach(function(c){ out += renderCurrency(R.reconcile(state[c].rows, KASA.days, c)); });
    $('results').innerHTML = out;
  }

  async function handleFiles(list){
    for(var i=0;i<list.length;i++){ var file=list[i]; var nl=file.name.toLowerCase(); var parsed;
      try{
        if(/\.xlsx$/.test(nl)){ var buf=await file.arrayBuffer(); parsed=await R.readFile(nl, new Uint8Array(buf)); }
        else { parsed=await R.readFile(nl, await file.text()); }
      }catch(e){ $('msg').textContent = file.name+': okunamadı — '+e.message; continue; }
      if(!parsed.rows.length){ $('msg').textContent = file.name+': tarihli satır bulunamadı (rapor doğru mu?).'; continue; }
      state[parsed.currency] = {rows:parsed.rows, name:file.name};
      $('msg').textContent = '';
    }
    try{ localStorage.setItem(LS, JSON.stringify(state)); }catch(e){}
    renderAll();
  }

  function boot(){
    try{ var s=localStorage.getItem(LS); if(s){ state=JSON.parse(s)||{}; } }catch(e){ state={}; }
    var inp=$('fileIn'), zone=$('drop');
    inp.addEventListener('change', function(){ handleFiles(inp.files); inp.value=''; });
    ['dragenter','dragover'].forEach(function(ev){ zone.addEventListener(ev, function(e){ e.preventDefault(); zone.classList.add('over'); }); });
    ['dragleave','drop'].forEach(function(ev){ zone.addEventListener(ev, function(e){ e.preventDefault(); zone.classList.remove('over'); }); });
    zone.addEventListener('drop', function(e){ if(e.dataTransfer && e.dataTransfer.files) handleFiles(e.dataTransfer.files); });
    $('clrBtn').addEventListener('click', function(){ state={}; try{localStorage.removeItem(LS);}catch(e){} renderAll(); $('msg').textContent=''; });
    renderAll();
  }
  if(document.readyState!=='loading') boot(); else document.addEventListener('DOMContentLoaded', boot);
})();
</script>"""


def build_kasa(env):
    end = yesterday()
    start = end - dt.timedelta(days=13)          # 14-day window; covers a 7-day bank report + T+1 preroll
    rows = E.fetch_folio(start.isoformat(), end.isoformat(), env=env)
    pays = [r for r in rows if r.get("DEPTTYPENAME") == "PAYMENT"]

    days = OrderedDict()
    d = start
    while d <= end:
        # cardTRY/EUR/USD are NATIVE-currency (CTOTAL) for per-currency POS matching;
        # cardEURtl/cardUSDtl are the TL equivalents (TOTAL) for display only.
        days[d.isoformat()] = {"cardTRY": 0.0, "cardEUR": 0.0, "cardUSD": 0.0,
                               "cardEURtl": 0.0, "cardUSDtl": 0.0,
                               "cash": 0.0, "havale": 0.0, "cityledger": 0.0}
        d += dt.timedelta(days=1)
    week = list(days)[-7:]
    wkset = set(week)
    by_user = defaultdict(lambda: defaultdict(float))
    for r in pays:
        fd = str(r.get("FOLIODATE"))[:10]
        if fd not in days:
            continue
        amt = abs(num(r.get("TOTAL")))       # TL (master currency), always
        native = abs(num(r.get("CTOTAL")))   # original payment currency
        m = r.get("DEPNAME") or ""
        cur = (r.get("CURRENCY") or "").upper()
        slot = days[fd]
        if m == "Credit Card":
            if cur == "EUR":
                slot["cardEUR"] += native
                slot["cardEURtl"] += amt
            elif cur == "USD":
                slot["cardUSD"] += native
                slot["cardUSDtl"] += amt
            else:
                slot["cardTRY"] += amt
        elif m == "Cash":
            slot["cash"] += amt
        elif m == "Havale":
            slot["havale"] += amt
        elif m == "CityLedger":
            slot["cityledger"] += amt
        if fd in wkset:
            by_user[r.get("USERFULLNAME") or "—"][m] += amt

    W = lambda k: sum(days[x][k] for x in week)  # noqa: E731
    wk_cardTRY = W("cardTRY")
    wk_foreigntl = W("cardEURtl") + W("cardUSDtl")
    wk_cash, wk_hav, wk_cl = W("cash"), W("havale"), W("cityledger")

    stats = stat(f"{tl(wk_cardTRY)} ₺", "kredi kartı ₺ (7 gün)")
    stats += stat(f"{tl(wk_foreigntl)} ₺", "yabancı kart TL krş. (7 gün)", "")
    stats += stat(f"{tl(wk_cash)} ₺", "nakit (7 gün)", "")
    stats += stat(f"{tl(wk_hav + wk_cl)} ₺", "havale + acente (7 gün)", "")

    intro = (
        "<h2>Banka POS mutabakatı — haftalık</h2>"
        "<p class='lead'>Her pazartesi bankadan indirdiğin <b>Hesap Hareketleri</b> Excel'lerini "
        "(TL, EUR, USD — her biri ayrı dosya) aşağıya <b>sürükle-bırak</b> ya da "
        "<b>Dosya seç</b> ile yükle. Her dosyanın para birimini kendi tanır ve Elektra'daki "
        "kart tahsilatıyla bankaya <b>gerçekten geçen</b> POS'u karşılaştırır. Dosyalar yalnızca "
        "bu tarayıcıda işlenir — dışarı gitmez.</p>")

    form = (
        "<div id='drop' class='drop'><div class='drop-ic'>📄⬆️</div>"
        "<div><b>Banka Excel'lerini buraya bırak</b> (TL / EUR / USD)</div>"
        "<div class='muted'>.xlsx · birden fazla dosya seçebilirsin</div>"
        "<label class='btn' for='fileIn'>Dosya seç</label>"
        "<input id='fileIn' type='file' accept='.xlsx,.xls,.csv' multiple hidden></div>"
        "<div class='btnrow'><button id='clrBtn' class='btn ghost'>Temizle</button>"
        "<span id='fileList' class='muted'></span></div>"
        "<div id='msg' class='warn' style='font-size:12.5px'></div>"
        "<div id='results'></div>")

    # Weekly per-user collection table (who collected how much).
    urows = []
    for u in sorted(by_user, key=lambda u: -sum(by_user[u].values())):
        tot = sum(by_user[u].values())
        c = by_user[u].get("Cash", 0)
        cc = by_user[u].get("Credit Card", 0)
        urows.append(f"<tr><td><span class='who'>{esc(u)}</span></td>"
                     f"<td class='r money'>{tl(c)}</td><td class='r money'>{tl(cc)}</td>"
                     f"<td class='r money'>{tl(tot)} ₺</td></tr>")
    user_tbl = ("<h2>Personele göre tahsilat (7 gün)</h2><table><tr><th>Personel</th>"
                "<th class='r'>Nakit</th><th class='r'>Kredi Kartı</th><th class='r'>Toplam</th></tr>"
                + "".join(urows) + "</table>")

    # Elektra per-day context table (all baked days, newest first). Foreign card shown
    # both native (EUR/USD) and TL-equivalent.
    trows = ""
    for dd in list(days)[::-1]:
        s = days[dd]
        eur = f"{tl(s['cardEUR'])} €" if s["cardEUR"] else "—"
        usd = f"{tl(s['cardUSD'])} $" if s["cardUSD"] else ""
        foreign = (eur + (" · " + usd if usd else "")) if (s["cardEUR"] or s["cardUSD"]) else "—"
        trows += (f"<tr><td>{tr_g(dt.date.fromisoformat(dd))}</td>"
                  f"<td class='r money'>{tl(s['cardTRY'])}</td><td class='r'>{foreign}</td>"
                  f"<td class='r'>{tl(s['cash'])}</td><td class='r'>{tl(s['havale'])}</td>"
                  f"<td class='r'>{tl(s['cityledger'])}</td></tr>")
    eltable = ("<h2>Elektra günlük tahsilat</h2><table><tr><th>Gün</th><th class='r'>Kart ₺</th>"
               "<th class='r'>Yabancı kart</th><th class='r'>Nakit</th><th class='r'>Havale</th>"
               "<th class='r'>Acente/Cari</th></tr>" + trows + "</table>")

    # --- Nakit akışı (Ön Kasa): resepsiyon folyo nakdi → otel kasasına devir → banka. ---
    # ŞEFFAF GÖSTERİM (otomatik suçlama YOK): tahsil edilen nakdin kasaya tam geçip geçmediğini
    # sahibin kendi iş akışıyla görebilmesi için. Fark çoğunlukla o gün nakitten ödenen giderdir;
    # Kasa hareketlerinden doğrulanır (giderler de nakitten çıkar, notlar serbest-metin — bu
    # yüzden güvenilir bir otomatik hırsızlık-flag'i mümkün değil). Kaynak: Ön Kasa defteri.
    import re as _re
    try:
        cdet = [r for r in E.fetch_cash_detail(
                    start.isoformat(), (end + dt.timedelta(days=2)).isoformat(), env=env)
                if (r.get("CURRENCY") or "") == "TRY"]
        folio_cash = defaultdict(float)
        for r in cdet:
            if r.get("TYPE") == "Folio Cash":
                folio_cash[str(r.get("DATE"))[:10]] += num(r.get("LOCALAMOUNT"))
        DATE_RE = _re.compile(r"(\d{1,2})[.\-/](\d{1,2})")
        to_safe = defaultdict(float)
        moves = []
        for r in cdet:
            if r.get("TYPE") != "Safe Advance":
                continue
            cin = num(r.get("CASHTAKEN")); cout = num(r.get("CASHGIVEN"))
            nt = (r.get("NOTES") or "").strip()
            if cin or cout:
                moves.append((str(r.get("DATE"))[:10], cin, cout, nt))
            # Sadece NET tek-tarihli "GG.AA kasa" devirlerini o güne ata (yüksek kesinlik).
            # Çok-günlü ("14.08-15.08-16.08"), "önceki kasa", "ana kasadan avans" gibi notlar
            # atfedilmez — yalnızca aşağıdaki hareketler listesinde görünür.
            dmatches = DATE_RE.findall(nt)
            if cin > 0 and len(dmatches) == 1 and "kasa" in nt.lower() \
                    and "önceki" not in nt.lower() and "ana kasa" not in nt.lower():
                dd, mm = int(dmatches[0][0]), int(dmatches[0][1])
                to_safe[f"{start.year}-{mm:02d}-{dd:02d}"] += cin
        crows = ""
        for dk in list(days):
            fc = folio_cash.get(dk, 0.0); ts = to_safe.get(dk, 0.0)
            if fc <= 0.5 and ts <= 0.5:
                continue
            gap = fc - ts
            gcell = (f"<span style='color:#b45309;font-weight:700'>{tl(gap)} ₺</span>"
                     if (ts > 0.5 and abs(gap) > 0.5) else ("0" if ts > 0.5 else "—"))
            crows += (f"<tr><td>{tr_g(dt.date.fromisoformat(dk))}</td>"
                      f"<td class='r money'>{tl(fc)} ₺</td>"
                      f"<td class='r'>{tl(ts) + ' ₺' if ts > 0.5 else '—'}</td>"
                      f"<td class='r'>{gcell}</td></tr>")
        mrows = ""
        for dk, cin, cout, nt in sorted(moves, key=lambda x: x[0], reverse=True):
            mrows += (f"<tr><td>{tr_g(dt.date.fromisoformat(dk))}</td>"
                      f"<td class='r'>{tl(cin) + ' ₺' if cin > 0.5 else ''}</td>"
                      f"<td class='r'>{tl(cout) + ' ₺' if cout > 0.5 else ''}</td>"
                      f"<td>{esc(nt) or '—'}</td></tr>")
        cash_html = (
            "<h2>Nakit akışı — Ön Kasa (resepsiyon → otel kasası → banka)</h2>"
            "<p class='lead'>Resepsiyonun tahsil ettiği <b>folyo nakdi</b>, ertesi gün "
            "<b>“GG.AA kasa”</b> notuyla otel kasasına devredilir; oradan bankaya yatar. Aşağıda "
            "o günkü tahsilat ile kasaya devredilen yan yana. <b>Fark</b> çoğunlukla o gün nakitten "
            "ödenen giderdir — alttaki <b>Kasa hareketleri</b>nden doğrula; açıklanamayan fark varsa "
            "resepsiyon/muhasebeye sor. (“—” = o gün için henüz net devir kaydı yok.)</p>"
            "<table><tr><th>Gün</th><th class='r'>Folyo nakit tahsilat</th>"
            "<th class='r'>Otel kasasına devir</th><th class='r'>Fark</th></tr>" + crows + "</table>"
            "<h2 style='font-size:14px;margin-top:18px'>Kasa hareketleri (devir · banka · gider)</h2>"
            "<div class='scroll'><table><tr><th>Gün</th><th class='r'>Kasaya giren</th>"
            "<th class='r'>Kasadan çıkan</th><th>Not</th></tr>" + mrows + "</table></div>")
    except Exception as ex:
        cash_html = f"<p class='lead'>(Ön Kasa nakit akışı alınamadı: {esc(str(ex)[:90])})</p>"

    note = ("<div class='note'>POS parası bankaya genelde <b>ertesi gün</b> geçer (T+1); tablo "
            "bunu hizalar. Banka <b>net</b> yatırır (komisyon düşülür) — rapor komisyonu geri "
            "ekleyip <b>brüt</b> karşılaştırır. Her para birimi kendi hesabına geçer: TL kartlar "
            "TL POS'a, yabancı (EUR/USD) kartlar döviz POS hesabına — bu yüzden her döviz dosyası "
            "ayrı karşılaştırılır. Acente EFT'leri kendi takviminde ödendiğinden gün-gün "
            "tutmayabilir. Kaynak: QA_HOTEL_FOLIO (PAYMENT satırları).</div>")

    data_script = ("<script>window.__KASA__=" + json.dumps(
        {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        ensure_ascii=False) + ";</script>")

    body = (KASA_EXTRA_CSS + f"<div class='stats'>{stats}</div>" + intro + form
            + user_tbl + eltable + cash_html + note + data_script + KASA_RECON_JS)
    return {"label": "Kasa & POS Mutabakatı", "count": int(round(wk_cardTRY + wk_foreigntl)),
            "count_label": "₺ kart (7g)", "tone": "ok",
            "sub": f"{tr_g(start)}–{tr_g(end)} · POS için banka Excel'ini yükle",
            "updated": now_str(), "html": PAGE("Haftalık Kasa Kontrolü",
            "Kasa & POS Mutabakatı", f"{tr_g(start)} – {tr_g(end)} · banka POS mutabakatı", body)}


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
ELEKTRA_RES_GRID = "https://app.elektraweb.com/app/grid/res-all/reservation"


def fbal(r):
    """Net folio balance (TL) from the res-guest-balance-list view."""
    return num(r.get("FOLIO_BALANCE"))


# Robust clipboard copy that also works inside the sandboxed dashboard iframe: the old
# navigator.clipboard API is blocked there without a clipboard-write permission, so fall
# back to a hidden-textarea + execCommand('copy') which runs on the click gesture.
REZ_COPY_JS = ("<script>function rivaCopyRez(el,t){var ok=false;"
               "try{var a=document.createElement('textarea');a.value=t;a.setAttribute('readonly','');"
               "a.style.position='fixed';a.style.top='-1000px';a.style.opacity='0';document.body.appendChild(a);"
               "a.select();a.setSelectionRange(0,t.length);ok=document.execCommand('copy');document.body.removeChild(a);}catch(e){}"
               "try{if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t);ok=true;}}catch(e){}"
               "if(ok&&el){var o=el.textContent;el.textContent='kopyalandı ✓';setTimeout(function(){el.textContent=o;},1200);}"
               "return true;}</script>")


def rez_link(resid):
    """Reservation number as a link: opens Elektra's reservation grid (they're logged in) and
    copies the id to the clipboard. Elektra opens cards as modals with no per-card URL and its
    grid filter is not in the URL either, so we can't deep-link the card — the owner pastes the
    copied id into the grid's 'Rez Id' box (⌘V) and double-clicks the row. Needs REZ_COPY_JS
    on the page."""
    r = esc(str(resid or "")).strip()
    if not r:
        return "—"
    return (f"<a href='{ELEKTRA_RES_GRID}' target='_blank' rel='noopener' "
            f"onclick=\"return rivaCopyRez(this,'{r}')\" "
            f"title='Tıkla: Elektra açılır + {r} panoya kopyalanır → Rez Id kutusuna ⌘V yapıştır, satıra çift tıkla' "
            f"style='font-variant-numeric:tabular-nums;font-weight:600'>{r}</a>")


def is_internal_folio(guest):
    """BOARD FOLIO / CASH FOLIO / MASTER FOLYO ve benzerleri Elektra'nın İÇ muhasebe
    kaplarıdır — gerçek misafir değil. Misafir adında FOLIO/FOLYO geçer (Türkçe İ dahil).
    Tüm listelerden (çıkışlar, açık bakiye, ...) elenmeli."""
    g = (guest or "").upper().replace("İ", "I")
    return "FOLIO" in g or "FOLYO" in g


def open_balances(env):
    """res-guest-balance-list (QA_HOTEL_RESERVATION_GUESTFOLIOS): folios that GENUINELY
    owe money, i.e. FOLIO_BALANCE > 0. This is the authoritative signal because the view
    already (a) consolidates FOLIO ROUTING — a reservation whose folio is routed to another
    shows 0, the target carries the combined balance — and (b) nets agency prepayments. So
    it catches what per-reservation GENERALBALANCE missed: agency-side debts and routed
    folios. _left=True when the guest checked out (RESSTATEID 4) still owing. Sorted:
    checked-out-owing first, then by amount. Shared by build_bakiye and build_odeme.
    BOARD/CASH FOLIO iç kayıtları elenir (is_internal_folio)."""
    rows = E.fetch_guest_folios(env)
    owed = [r for r in rows if fbal(r) > 0.5 and not is_internal_folio(r.get("GUESTNAMES"))]
    for r in owed:
        r["_left"] = r.get("RESSTATEID") == 4                # çıkış yaptı, hâlâ borçlu
    owed.sort(key=lambda r: (0 if r.get("_left") else 1, -fbal(r)))
    return owed


# OTA channels the owner asked to exclude from cari receivables — they auto-settle, so
# their running balance is channel float, not "who hasn't paid me".
CARI_CHANNELS = ("EXPEDIA", "BOOKING", "AGODA", "OTELZ", "HOTELS", "ETSTUR",
                 "HOTELBEDS", "CTRIP", "TRIP.COM", "PLANET")


def cari_receivables(env):
    """Alıcılar (120.x) hesapları — sana borçlu olanlar — GERÇEK ekstre bakiyesiyle
    (E.fetch_account_balances). QA_ACCOUNTS'un kayıtlı bakiyesi BAYAT: hem şişiriyor (borcunu
    ödemiş bir acenteyi hâlâ eski borcuyla gösteriyor) hem kaçırıyor (yeni bir borcu 0
    gösterip listeden düşürüyor). Ekstre proc'u canlı/doğru. LOCALBALANCE burada = ekstre
    Σ(borç−alacak); > 0 = borç = bize borçlu. Otomatik OTA kanalları hariç (kendileri
    mahsuplaşır)."""
    out = []
    for r in E.fetch_account_balances(env, master_code="120"):
        if num(r.get("LOCALBALANCE")) <= 0.5:          # sadece borç bakiyeliler (bize borçlu)
            continue
        if any(ch in str(r.get("NAME") or "").upper() for ch in CARI_CHANNELS):
            continue
        out.append(r)
    out.sort(key=lambda r: -num(r.get("LOCALBALANCE")))
    return out


def build_bakiye(env):
    """Bakiye Kontrolü — folios with an open balance (res-guest-balance-list, FOLIO_BALANCE>0)
    so a walk-in / direct guest who didn't pay isn't forgotten. Source handles folio routing
    and agency-prepayment netting (see open_balances). A guest who CHECKED OUT still owing is
    flagged urgent (left without paying)."""
    today = dt.date.today()
    owed = open_balances(env)

    left = [r for r in owed if r.get("_left")]
    total = sum(fbal(r) for r in owed)
    cari = cari_receivables(env)
    cari_total = sum(num(r.get("LOCALBALANCE")) for r in cari)
    stats = (stat(len(owed), "açık misafir kaydı", "bad" if owed else "ok")
             + stat(f"{tl(total)} ₺", "misafir tahsilat (acil)")
             + stat(len(cari), "cari alacak (firma)", "bad" if cari else "ok")
             + stat(f"{tl(cari_total)} ₺", "cari alacak toplam"))

    def age(r):
        if not r.get("_left"):
            return "konaklıyor"
        co = pdate(r.get("CHECKOUTDATE"))
        if not co:
            return "—"
        d = (today - co).days
        return "bugün çıktı" if d <= 0 else f"{d} gün önce çıktı"

    def ci_co(r):
        ci = pdate(r.get("CHECKINDATE")); co = pdate(r.get("CHECKOUTDATE"))
        return f"{tr_g(ci) if ci else '—'} → {tr_g(co) if co else '—'}"

    if owed:
        trs = []
        for r in owed:
            durum = ("🔴 ÇIKTI — borçlu" if r.get("_left") else "Konaklıyor")
            trs.append(f"<tr class='{'bad' if r.get('_left') else ''}'>"
                       f"<td>{rez_link(r.get('RESID'))}</td>"
                       f"<td>{esc(r.get('ROOMNO') or '—')}</td>"
                       f"<td>{esc((r.get('GUESTNAMES') or '')[:34])}</td>"
                       f"<td>{esc((r.get('AGENCY') or '')[:16])}</td>"
                       f"<td style='white-space:nowrap'>{ci_co(r)}</td>"
                       f"<td>{durum}</td>"
                       f"<td class='r money'>{tl(fbal(r))} ₺</td>"
                       f"<td>{esc(age(r))}</td></tr>")
        table = ("<h2>Ödemesi alınmamış misafir kayıtları</h2>"
                 "<p class='lead'>Folyosunda gerçekten açık bakiye (net borç) olan kayıtlar — en acili "
                 "<b>çıkış yaptığı hâlde borçlu</b> olanlar (kırmızı). Rez No'ya tıkla → Elektra açılır "
                 "(numara kopyalanır, Rez Id filtresine yapıştır). Tahsil edilene kadar burada kalır.</p>"
                 "<table><tr><th>Rez No</th><th>Oda</th><th>Misafir</th><th>Acenta</th>"
                 "<th>Giriş → Çıkış</th><th>Durum</th>"
                 "<th class='r'>Borç</th><th>Yaş</th></tr>" + "".join(trs) + "</table>")
    else:
        table = empty_ok("Ödemesi alınmamış misafir kaydı yok — hepsi tahsil edilmiş.")

    if cari:
        crows = "".join(
            f"<tr><td>{esc(r.get('CODE') or '')}</td>"
            f"<td>{esc((r.get('NAME') or '')[:36])}</td>"
            f"<td class='r money'>{tl(num(r.get('LOCALBALANCE')))} ₺</td></tr>"
            for r in cari)
        cari_panel = ("<h2>🏢 Cari Alacaklar — acente / firma</h2>"
                      "<p class='lead'>City ledger'a (cariye) geçmiş, sana <b>borçlu</b> acente/firmalar — "
                      "net bakiye (TL). Otomatik kanallar (Expedia/Booking/Agoda) hariç. Bunlar bankaya "
                      "genelde havale ile gelir. <i>Muhtelif Alıcılar</i> = çeşitli küçük müşterilerin toplamı. "
                      "Rakam Elektra muhasebe <b>net</b> bakiyesidir (kümülatif); ekrandaki dönem-bakiyesinden "
                      "farklı olabilir.</p>"
                      "<table><tr><th>Kod</th><th>Cari / Firma</th><th class='r'>Alacak (net)</th></tr>"
                      + crows +
                      f"<tr><td></td><td class='r'><b>TOPLAM</b></td>"
                      f"<td class='r money'><b>{tl(cari_total)} ₺</b></td></tr></table>")
    else:
        cari_panel = ""

    note = ("<div class='note'>Misafir kayıtları: <b>res-guest-balance-list</b> "
            "(QA_HOTEL_RESERVATION_GUESTFOLIOS) FOLIO_BALANCE>0 — routing + acenta/misafir netlenmiş. "
            "Cari alacaklar: <b>QA_ACCOUNTS</b> (Kredili Hesaplar), Alıcılar 120.x borç (D) bakiye, "
            "net TL, otomatik kanallar hariç.</div>")
    fresh = ("<div style='background:#fef3c7;border:1px solid #fde68a;color:#92400e;"
             "padding:9px 13px;border-radius:9px;margin:0 0 12px;font-size:12.5px'>"
             f"⏱ Bu sayfadaki veriler <b>{now_str()}</b> itibarıyladır. Bu saatten sonra "
             "yapılan giriş/ödeme hareketleri bir sonraki güncellemede görünür.</div>")
    sub = (f"misafir {tl(total)} ₺ · cari {tl(cari_total)} ₺"
           + (f" · {len(left)} çıkıp borçlu 🔴" if left else ""))
    return {"label": "Bakiye Kontrolü", "count": len(owed) + len(cari),
            "count_label": "açık + cari", "tone": "bad" if (owed or cari) else "ok",
            "sub": sub, "updated": now_str(),
            "html": PAGE("Tahsilat — Açık Bakiye", "Bakiye Kontrolü",
                         "misafir açık bakiyeleri + cari alacaklar",
                         f"<div class='stats'>{stats}</div>{fresh}{table}{cari_panel}{note}{REZ_COPY_JS}")}


DAY_ABBR = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]


def build_odeme(env):
    """Günlük Ödeme Kontrolü — date-SELECTABLE arrival-payment check plus an open-balances
    panel (res-guest-balance-list). On Monday the owner picks Saturday / Sunday to see each
    day's arrivals' payment status, while the open-balances panel surfaces anyone from a past
    day who still owes — so a weekend non-payer is never missed."""
    import paycheck
    today = dt.date.today()
    ndays = 7

    # 1) Per-day arrivals classified by paid/unpaid (one fetch per day, last ndays).
    daydata = OrderedDict()
    total_rows = 0
    for i in range(1, ndays + 1):
        day = (today - dt.timedelta(days=i)).isoformat()
        rows = E.fetch_arrivals(day, env=env)
        total_rows += len(rows)
        daydata[day] = (len(rows), paycheck.classify(rows)["unpaid"])
    if total_rows == 0:
        raise RuntimeError("son 7 günde hiç giriş dönmedi — boş grid 'hepsi ödedi' sayılmaz "
                           "(API sorunu olabilir).")

    # 2) Open balances (the red res-guest-balance-list rows), day-independent.
    owed = open_balances(env)
    left = [r for r in owed if r.get("_left")]
    owed_total = sum(fbal(r) for r in owed)

    stats = (stat(len(owed), "ödenmemiş rezervasyon", "bad" if owed else "ok")
             + stat(f"{tl(owed_total)} ₺", "tahsil edilecek toplam")
             + stat(len(left), "çıkıp borçlu 🔴", "bad" if left else "ok"))

    def age(r):
        if not r.get("_left"):
            return "konaklıyor"
        co = pdate(r.get("CHECKOUTDATE"))
        if not co:
            return "—"
        d = (today - co).days
        return "bugün çıktı" if d <= 0 else f"{d} gün önce çıktı"

    if owed:
        trs = "".join(
            f"<tr class='{'bad' if r.get('_left') else ''}'>"
            f"<td>{rez_link(r.get('RESID'))}</td>"
            f"<td>{esc(r.get('ROOMNO') or '—')}</td>"
            f"<td>{esc((r.get('GUESTNAMES') or '')[:34])}</td>"
            f"<td>{esc((r.get('AGENCY') or '')[:16])}</td>"
            f"<td>{esc(str(r.get('CHECKINDATE') or '')[:10])}</td>"
            f"<td>{esc(str(r.get('CHECKOUTDATE') or '')[:10])}</td>"
            f"<td>{'🔴 ÇIKTI — borçlu' if r.get('_left') else 'Konaklıyor'}</td>"
            f"<td class='r money'>{tl(fbal(r))} ₺</td><td>{esc(age(r))}</td></tr>"
            for r in owed)
        openpanel = ("<h2>🔴 Ödenmemiş rezervasyonlar (açık bakiye)</h2>"
                     "<p class='lead'>Şu an folyosunda <b>açık bakiye</b> olan tüm rezervasyonlar — "
                     "Elektra'nın res-guest-balance-list (kırmızı) ekranıyla birebir; folyo yönlendirme "
                     "ve acenta tarafı dahil, hiçbiri kaçmaz. En acili <b>çıkış yaptığı hâlde borçlu</b>. "
                     "<b>Rez No'ya tıkla</b> → Elektra açılır, numara kopyalanır (Rez Id filtresine yapıştır). "
                     "Tahsil edilene kadar burada kalır.</p>"
                     "<table><tr><th>Rez No</th><th>Oda</th><th>Misafir</th><th>Acenta</th><th>Giriş</th>"
                     "<th>Çıkış</th><th>Durum</th><th class='r'>Borç</th><th>Yaş</th></tr>"
                     + trs + "</table>")
    else:
        openpanel = empty_ok("Açık (ödenmemiş) bakiye yok — hepsi tahsil edilmiş.")

    # 3) Per-day arrival panels + a day selector (client-side show/hide).
    def day_label(iso):
        d = dt.date.fromisoformat(iso)
        return f"{tr_g(d)} {DAY_ABBR[d.weekday()]}"

    opts, panels = "", ""
    for iso, (arrivals, unpaid) in daydata.items():
        tag = f"{len(unpaid)} ödenmemiş" if unpaid else ("giriş yok" if not arrivals else "hepsi ödedi")
        opts += f"<option value='{iso}'>{esc(day_label(iso))} — {tag}</option>"
        if unpaid:
            rows_html = "".join(
                f"<tr><td>{rez_link(r.get('rez_id'))}</td>"
                f"<td>{esc(r.get('room') or '—')}</td>"
                f"<td>{esc((r.get('guest') or '')[:34])}</td>"
                f"<td>{esc((r.get('agency') or '')[:16])}</td>"
                f"<td>{esc(str(r.get('checkin') or '')[:10])} → {esc(str(r.get('checkout') or '')[:10])}</td>"
                f"<td class='r money'>{tl(r.get('_balance'))} ₺</td></tr>"
                for r in unpaid)
            inner = (f"<p class='lead'><b class='miss'>{len(unpaid)} rezervasyonda ödeme eksik</b> — "
                     f"toplam {tl(sum(r['_balance'] for r in unpaid))} ₺. Resepsiyona sorulmalı.</p>"
                     "<table><tr><th>Rez No</th><th>Oda</th><th>Misafir</th><th>Acenta</th><th>Giriş→Çıkış</th>"
                     "<th class='r'>Genel Bakiye</th></tr>" + rows_html + "</table>")
        elif not arrivals:
            inner = "<p class='lead'>Bu tarihte giriş yok.</p>"
        else:
            inner = empty_ok(f"{arrivals} girişin hepsi ödemesini yapmış.")
        panels += f"<div class='daypanel' data-day='{iso}' style='display:none'>{inner}</div>"

    selector = ("<h2>Güne göre giriş ödemeleri</h2>"
                "<p class='lead'>Bir gün seç — o gün <b>giriş yapan</b> misafirlerin ödeme durumu. "
                "Pazartesi baktığında cumartesi ve pazarı ayrı ayrı görebilirsin.</p>"
                "<select id='daySel'>" + opts + "</select>"
                + panels +
                "<script>(function(){var s=document.getElementById('daySel');"
                "function show(){var v=s.value;var ps=document.querySelectorAll('.daypanel');"
                "for(var i=0;i<ps.length;i++){ps[i].style.display=ps[i].getAttribute('data-day')===v?'block':'none';}}"
                "s.addEventListener('change',show);show();})();</script>")

    note = ("<div class='note'>Ödenmemiş rezervasyonlar: <b>res-guest-balance-list</b> "
            "(QA_HOTEL_RESERVATION_GUESTFOLIOS) <b>FOLIO_BALANCE>0</b> — folyonun net bakiyesi; "
            "folyo yönlendirme (routing) birleştirilmiş, acenta ön ödemesi netlenmiş, borç misafir "
            "veya acenta tarafında olsun yakalanır (hiçbiri kaçmaz). Konaklayan + son 180 gün çıkış. "
            "Güne göre panel: o gün Geliş = tarih olan rezervasyonların ödeme durumu (paycheck).</div>")

    # Veri tazeliği: pano bulutta periyodik üretilir; aradaki yeni giriş/ödeme hareketleri
    # bir sonraki üretime kadar görünmez. Bunu GİZLEMEK yanlış "hepsi ödedi" izlenimi verir.
    fresh = ("<div style='background:#fef3c7;border:1px solid #fde68a;color:#92400e;"
             "padding:9px 13px;border-radius:9px;margin:0 0 12px;font-size:12.5px'>"
             f"⏱ Bu sayfadaki veriler <b>{now_str()}</b> itibarıyladır. Bu saatten sonra "
             "yapılan giriş/ödeme hareketleri bir sonraki güncellemede görünür — "
             "en güncel hâli için Elektra'ya bak.</div>")
    body = f"<div class='stats'>{stats}</div>{fresh}{openpanel}{selector}{note}{REZ_COPY_JS}"
    sub = (f"{len(owed)} açık bakiye · tahsil {tl(owed_total)} ₺"
           + (f" · {len(left)} çıkıp borçlu 🔴" if left else ""))
    return {"label": "Günlük Ödeme Kontrolü", "count": len(owed),
            "count_label": "açık bakiye", "tone": "bad" if owed else "ok",
            "sub": sub, "updated": now_str(),
            "html": PAGE("Günlük Ödeme Kontrolü", "Günlük Ödeme Kontrolü",
                         f"açık bakiyeler + güne göre giriş ödemeleri · {tr_g(today)}", body)}


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
# 20.11.2026 yeniden düzen (sahibinin isteği: "grafikler çok büyük, profesyonel olsun"):
# iç başlık yok (kabuk zaten gösteriyor), üstte KPI kutuları, grafikler ikişer yan yana
# ve sabit yükseklikte, tablo en altta.
SALES_CSS = """<style>
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(170px,100%),1fr));gap:12px;margin:2px 0 16px}
.kpi{background:var(--card);border:1px solid var(--border);border-radius:13px;padding:13px 16px}
.kpi .l{color:var(--sub);font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.3px}
.kpi .n{font-size:22px;font-weight:800;margin-top:3px;font-variant-numeric:tabular-nums;white-space:nowrap}
.kpi .d{font-size:11.5px;color:var(--sub);margin-top:3px}
.up{color:var(--statok);font-weight:700}.dn{color:var(--statbad);font-weight:700}
.g2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(340px,100%),1fr));gap:14px;margin-bottom:14px}
.g2>*,.g3>*{min-width:0}
.g3{display:grid;grid-template-columns:2fr 1fr;gap:14px;margin-bottom:14px}
@media (max-width:900px){.g3{grid-template-columns:1fr}}
.card h3{display:flex;justify-content:space-between;align-items:baseline;gap:8px;font-size:13px;margin:0 0 2px}
.card h3 small{font-weight:600;color:var(--sub);font-size:11.5px}
.sec{font-size:12px;font-weight:800;letter-spacing:.5px;text-transform:uppercase;color:var(--eyebrow);margin:22px 0 10px}
.tw{overflow-x:auto;border:1px solid var(--border);border-radius:12px}
.tw table{margin:0;border-radius:0;min-width:560px}
tr.now td{background:var(--th-bg)}
@media (max-width:600px){.kpis{grid-template-columns:1fr 1fr;gap:8px}.kpi{padding:10px 12px}
  .kpi .n{font-size:16px;white-space:normal}.kpi .d{font-size:10.5px}}
</style>"""


def _delta(cur, prev, suffix=""):
    """'▲ %12 geçen aya göre' — prev 0 ise boş."""
    if not prev:
        return ""
    p = (cur - prev) / prev * 100
    cls, ok = ("up", "▲") if p >= 0 else ("dn", "▼")
    return f"<span class='{cls}'>{ok} %{abs(p):.0f}</span> {esc(suffix)}"


def kpi(n, label, d=""):
    return (f"<div class='kpi'><div class='l'>{esc(label)}</div><div class='n'>{n}</div>"
            + (f"<div class='d'>{d}</div>" if d else "") + "</div>")


def _pm_split(env, frm, to):
    fol = E.fetch_folio(frm.isoformat(), to.isoformat(), env=env)
    pm = defaultdict(float)
    for r in fol:
        if r.get("DEPTTYPENAME") == "PAYMENT":
            pm[METHOD_TR.get(r.get("DEPNAME"), r.get("DEPNAME") or "Diğer")] += abs(num(r.get("TOTAL")))
    return sorted(pm.items(), key=lambda t: -t[1])


def _veri_aylari(monthly):
    """Elektra'ya geçiş Aralık 2025 sonunda: öncesi boş, ilk ay yarım. Baştaki doluluğu
    %15'in altındaki aylar grafikte/tabloda gösterilmez (yoksa Ocak '%800 artış' görünür)."""
    ks = list(monthly.keys())
    while len(ks) > 1 and monthly[ks[0]]["occ"] < 15:
        ks.pop(0)
    return ks


def _ay(monthly, key, gecerli):
    """Geçerli (veri olan) ayın kaydı, yoksa None."""
    return monthly[key] if key in gecerli else None


def build_stats(env):
    today = dt.date.today()
    start = month_start(today, 12)                 # 13 ay: geçen yılın aynı ayı da var
    active = active_reservations(env, start, today)
    daily = daily_occupancy(active, start, today)
    day_keys = list(daily.keys())

    last30 = day_keys[-30:]
    occ = [len(daily[d]) for d in last30]
    adr = [(sum(daily[d].values()) / len(daily[d]) if daily[d] else 0.0) for d in last30]
    occ_pct = [min(100, round(c / ROOMS_TOTAL * 100)) for c in occ]
    labels = [f"{d.day:02d}.{d.month:02d}" for d in last30]
    prev30 = day_keys[-60:-30]
    p_occ = [len(daily[d]) for d in prev30]

    today_occ = len(daily[today])
    today_pct = min(100, round(today_occ / ROOMS_TOTAL * 100))
    today_adr = (sum(daily[today].values()) / today_occ) if today_occ else 0.0
    revpar = today_adr * today_occ / ROOMS_TOTAL if ROOMS_TOTAL else 0
    avg_pct = round(sum(occ_pct) / len(occ_pct)) if occ_pct else 0
    p_avg = round(sum(p_occ) / len(p_occ) / ROOMS_TOTAL * 100) if p_occ else 0
    nz = [a for a in adr if a]
    avg_adr = sum(nz) / len(nz) if nz else 0
    rev30 = sum(sum(daily[d].values()) for d in last30)

    kpis = (kpi(f"%{today_pct}", "Bugün doluluk", f"{today_occ} / {ROOMS_TOTAL} oda dolu")
            + kpi(f"{tl(today_adr)} ₺", "Bugün ADR", "dolu oda başı ortalama gecelik")
            + kpi(f"{tl(revpar)} ₺", "Bugün RevPAR", "toplam oda başı gelir")
            + kpi(f"%{avg_pct}", "30 gün ort. doluluk",
                  _delta(avg_pct, p_avg, "önceki 30 güne göre"))
            + kpi(f"{tl(avg_adr)} ₺", "30 gün ort. ADR")
            + kpi(f"{kisa(rev30)} ₺", "30 gün oda geliri"))

    pm = _pm_split(env, today - dt.timedelta(days=7), today)
    donut = svg_donut(today_occ, ROOMS_TOTAL, f"/ {ROOMS_TOTAL} oda")
    gun30 = (
        "<div class='g2'>"
        f"<div class='card'><h3>Doluluk — son 30 gün <small>ort. %{avg_pct}</small></h3>"
        f"{svg_bars(labels, occ_pct, unit='%', height=140)}</div>"
        f"<div class='card'><h3>Ortalama oda fiyatı (ADR) — son 30 gün <small>ort. {tl(avg_adr)} ₺</small></h3>"
        f"{svg_line(labels, adr, unit=' ₺', fmt=lambda v: tl(v), height=140)}</div></div>"
        "<div class='g3'>"
        f"<div class='card'><h3>Ödeme türü dağılımı <small>son 7 gün</small></h3>"
        f"{svg_hbars(pm) or '<div class=lead>veri yok</div>'}</div>"
        f"<div class='card'><h3>Bugün doluluk <small>%{today_pct}</small></h3>"
        f"<div style='display:flex;justify-content:center;padding:6px 0'>{donut}</div></div></div>")

    # ---- aylık (son 12 ay + geçen yılın aynı ayı için 13. ay)
    monthly = monthly_aggregate(daily)
    mk_all = _veri_aylari(monthly)
    mkeys = mk_all[-12:]
    mlabels = [mlabel(k) for k in mkeys]
    ly = _ay(monthly, (today.year - 1, today.month), mk_all)
    cur = monthly[mkeys[-1]]
    aylik = (
        f"<div class='sec'>Aylık — son {len(mkeys)} ay</div><div class='g2'>"
        f"<div class='card'><h3>Aylık doluluk <small>bu ay %{cur['occ']}"
        + (f" · geçen yıl %{ly['occ']}" if ly else "") + "</small></h3>"
        f"{svg_bars(mlabels, [monthly[k]['occ'] for k in mkeys], unit='%', height=140, partial_last=True)}</div>"
        f"<div class='card'><h3>Aylık ADR <small>bu ay {tl(cur['adr'])} ₺</small></h3>"
        f"{svg_line(mlabels, [monthly[k]['adr'] for k in mkeys], unit=' ₺', fmt=lambda v: tl(v), height=140)}"
        "</div></div>")
    mrows = "".join(
        f"<tr{' class=now' if k == mkeys[-1] else ''}><td>{esc(mlabel(k, False))}"
        f"{' <span class=who>bugüne kadar</span>' if k == mkeys[-1] else ''}</td>"
        f"<td class='r'>%{monthly[k]['occ']}</td>"
        f"<td class='r money'>{tl(monthly[k]['adr'])}</td>"
        f"<td class='r'>{tl(monthly[k]['revpar'])}</td>"
        f"<td class='r'>{monthly[k]['rooms']}</td>"
        f"<td class='r money'>{tl(monthly[k]['rev'])} ₺</td></tr>"
        for k in reversed(mkeys))
    table = ("<div class='tw'><table><tr><th>Ay</th><th class='r'>Doluluk</th><th class='r'>ADR ₺</th>"
             "<th class='r'>RevPAR ₺</th><th class='r'>Oda-gecesi</th><th class='r'>Oda geliri</th></tr>"
             + mrows + "</table></div>")
    note = (f"<div class='note'>Doluluk = dolu oda / {ROOMS_TOTAL}. ADR = dolu odaların ortalama gecelik "
            "fiyatı (TL). RevPAR = oda geliri / toplam oda. Oda geliri = konaklanan oda-gecelerinin TL "
            "gecelik toplamı (ekstralar hariç). Bu ay kısmidir (bugüne kadar). Kaynak: Elektra "
            "rezervasyonları + folio ödemeleri.</div>")
    body = f"{SALES_CSS}<div class='kpis'>{kpis}</div>{gun30}{aylik}{table}{note}"
    return {"label": "İstatistikler & Grafikler", "count": today_pct,
            "count_label": "% bugün doluluk", "tone": "ok",
            "sub": f"bugün %{today_pct} · ADR {tl(today_adr)} ₺ · 30 gün ort. %{avg_pct}",
            "updated": now_str(), "html": PAGE(None, "İstatistikler & Grafikler", "", body)}


# --------------------------------------------------------------------------- 6) Aylık Satışlar
def build_satis(env):
    today = dt.date.today()
    start = month_start(today, 23)                 # 24 ay: her ayı geçen yılın aynı ayıyla kıyas
    active = active_reservations(env, start, today)
    daily = daily_occupancy(active, start, today)
    monthly = monthly_aggregate(daily)
    mk_all = _veri_aylari(monthly)
    mkeys = mk_all[-12:]
    mlabels = [mlabel(k) for k in mkeys]

    cur = monthly[mkeys[-1]]
    prev = monthly[mkeys[-2]] if len(mkeys) > 1 else {"rev": 0, "rooms": 0, "adr": 0, "occ": 0}
    ly = _ay(monthly, (today.year - 1, today.month), mk_all)
    ytd = sum(v["rev"] for k, v in monthly.items() if k[0] == today.year)

    # Geçen ayın AYNI günleri (1..bugün) — yarım ayı tam ayla kıyaslamamak için.
    pm_first = month_start(today, 1)
    same = [d for d in daily if d.year == pm_first.year and d.month == pm_first.month
            and d.day <= today.day]
    same_rev = sum(sum(daily[d].values()) for d in same)
    days_in = (month_start(today, -1) - month_start(today)).days
    proj = cur["rev"] / today.day * days_in if today.day else 0

    kpis = (kpi(f"{tl(cur['rev'])} ₺", f"{TR_MON_FULL[today.month]} oda geliri",
                _delta(cur["rev"], same_rev, f"geçen ayın ilk {today.day} gününe göre"))
            + kpi(f"≈ {kisa(proj)} ₺", "Ay sonu tahmini",
                  f"bu hızla · {TR_MON_FULL[pm_first.month]} {kisa(prev['rev'])} ₺")
            + kpi(f"{tl(prev['rev'])} ₺", f"{TR_MON_FULL[pm_first.month]} (geçen ay)",
                  (_delta(prev["rev"], (_ay(monthly, (pm_first.year - 1, pm_first.month), mk_all)
                                        or {}).get("rev", 0), "geçen yılın aynı ayına göre")))
            + kpi(f"{tl(ytd)} ₺", f"{today.year} toplamı", "yıl başından bugüne")
            + kpi(f"{cur['rooms']}", "Bu ay oda-gecesi", f"doluluk %{cur['occ']} · ADR {tl(cur['adr'])} ₺"))

    # Bu ayın günlük oda geliri
    tm = [d for d in daily if d.year == today.year and d.month == today.month]
    gunluk = svg_bars([f"{d.day}" for d in tm], [sum(daily[d].values()) for d in tm],
                      unit="₺", fmt=lambda v: tl(v) + " ", height=140)
    pm = _pm_split(env, month_start(today), today)
    pm_top = sum(v for _, v in pm)

    charts = (
        "<div class='g3'>"
        f"<div class='card'><h3>Aylık oda geliri <small>son 12 ay · açık renk = bu ay (bugüne kadar)</small></h3>"
        f"{svg_bars(mlabels, [monthly[k]['rev'] for k in mkeys], unit='₺', fmt=lambda v: tl(v) + ' ', height=150, partial_last=True)}</div>"
        f"<div class='card'><h3>Bu ay tahsilat <small>{tl(pm_top)} ₺</small></h3>"
        f"{svg_hbars(pm) or '<div class=lead>veri yok</div>'}</div></div>"
        "<div class='g2'>"
        f"<div class='card'><h3>{TR_MON_FULL[today.month]} — günlük oda geliri <small>ort. "
        f"{tl(cur['rev'] / len(tm) if tm else 0)} ₺/gün</small></h3>{gunluk}</div>"
        f"<div class='card'><h3>Aylık ADR <small>bu ay {tl(cur['adr'])} ₺"
        + (f" · geçen yıl {tl(ly['adr'])} ₺" if ly else "") + "</small></h3>"
        f"{svg_line(mlabels, [monthly[k]['adr'] for k in mkeys], unit=' ₺', fmt=lambda v: tl(v), height=140)}</div>"
        "</div>")

    # Elektra'da geçen yılın verisi olan ay yoksa (Ara 2026'ya kadar) sütun hiç çıkmaz.
    yoy = any(_ay(monthly, (k[0] - 1, k[1]), mk_all) for k in mkeys[:-1])
    rows = []
    for i, k in enumerate(reversed(mkeys)):
        v = monthly[k]
        lyv = _ay(monthly, (k[0] - 1, k[1]), mk_all)
        pv = monthly[mkeys[-2 - i]] if (len(mkeys) - 2 - i) >= 0 else None
        now = k == mkeys[-1]
        rows.append(
            f"<tr{' class=now' if now else ''}><td>{esc(mlabel(k, False))}"
            f"{' <span class=who>bugüne kadar</span>' if now else ''}</td>"
            f"<td class='r money'>{tl(v['rev'])} ₺</td>"
            f"<td class='r'>{'' if now or not pv else _delta(v['rev'], pv['rev'])}</td>"
            + (f"<td class='r'>{_delta(v['rev'], lyv['rev']) if (lyv and not now) else ''}</td>"
               if yoy else "") +
            f"<td class='r'>{v['rooms']}</td><td class='r'>%{v['occ']}</td>"
            f"<td class='r'>{tl(v['adr'])}</td></tr>")
    table = ("<div class='sec'>Aylık satış tablosu</div><div class='tw'><table><tr><th>Ay</th>"
             "<th class='r'>Oda geliri</th><th class='r'>Önceki aya göre</th>"
             + ("<th class='r'>Geçen yıla göre</th>" if yoy else "")
             + "<th class='r'>Oda-gecesi</th><th class='r'>Doluluk</th>"
             "<th class='r'>ADR ₺</th></tr>" + "".join(rows) + "</table></div>")

    body = (f"{SALES_CSS}<div class='kpis'>{kpis}</div>{charts}{table}"
            "<div class='note'>Oda geliri = konaklanan oda-gecelerinin TL gecelik toplamı (tahakkuk; "
            "ekstralar/minibar hariç). Tahsilat = bu ay folioya girilen ödemeler (TL). Ay sonu tahmini = "
            "bu ayın günlük ortalaması × ayın gün sayısı. “Geçen yıla göre” yalnızca Elektra'da geçen "
            "yılın verisi olan aylarda görünür. Kaynak: Elektra rezervasyonları + folio.</div>")
    return {"label": "Aylık Satışlar", "count": int(round(cur["rev"] / 1000)),
            "count_label": "bin ₺ · bu ay", "tone": "ok",
            "sub": f"{TR_MON_FULL[today.month]}: {tl(cur['rev'])} ₺ · {today.year} toplam {tl(ytd)} ₺",
            "updated": now_str(), "html": PAGE(None, "Aylık Satışlar", "", body)}



# --------------------------------------------------------------------------- 7) Vergi Sayfası
# KAYNAK = ELEKTRA MUHASEBE MİZANI (elektra_api.fetch_trial_balance). Muhasebecinin
# işlediği HER şey oradadır: otel satış faturaları, alış faturaları, elden girilen
# fişler, bordro, SGK. Vergiyi fatura listesinden değil MİZANDAN hesaplıyoruz — fatura
# listesi bordroyu/fişi görmez, mizan görür.
#
# TEK DÜZEN HESAP PLANI — 2 HANELİ GRUP bazında okunur. Grup, yansıtma hesabını kendi
# içinde netler (74 = 740 gider − 741 yansıtma), böylece gider iki kez sayılmaz:
#   60 Brüt satışlar · 64 Diğer faaliyet gelirleri · 67 Olağandışı gelir → GELİR (alacak)
#   61 Satıştan iade/iskonto                                            → gelirden DÜŞÜLÜR
#   62/63/65/66/68 ve 7x maliyet grupları                               → GİDER (borç)
#   689 K.K.E.G. → gidere girer, matraha GERİ EKLENİR (kanunen kabul edilmeyen)
#   391 Hesaplanan KDV (alacak) · 191 İndirilecek KDV (borç)
#   360 Ödenecek vergi ve fonlar (konaklama v., muhtasar, damga, tevkifat)
#
# KDV'de neden tek taraf? Muhasebeci ay sonunda kapanış fişi atar (391 borç / 191 alacak
# / 360 alacak). Net alırsak kapanış hareketleri kendi kendini götürür ve ay sıfırlanır.
# Bu yüzden ayın gerçek rakamı: hesaplanan = 391 ALACAK, indirilecek = 191 BORÇ.
#
# UYARI: kapanmış yılda 690/691/692 kapanış fişleri gelir/gider hesaplarının borcunu
# alacağına eşitler — bu sayfa bu yüzden YALNIZCA CARİ YILI hesaplar.
KV_RATE = 0.25          # kurumlar vergisi / geçici vergi oranı (2026)

# Geçici vergi dönemleri: 4. dönem 2024'te kaldırıldı, yıl sonu beyannameye bağlanır.
KV_PERIODS = [(3, "1. Dönem", "Oca–Mar", "17 Mayıs"),
              (6, "2. Dönem", "Oca–Haz", "17 Ağustos"),
              (9, "3. Dönem", "Oca–Eyl", "17 Kasım"),
              (12, "Yıllık beyan", "Oca–Ara", "30 Nisan")]


def _pl(rows):
    """Mizandan gelir tablosu kalemleri -> (gelir, satış indirimi, gider, kkeg).
    Yalnızca 2 haneli GRUP satırları toplanır (çift sayım olmasın diye)."""
    gelir = indirim = gider = kkeg = 0.0
    for r in rows:
        c = r["code"]
        if c.isdigit() and len(c) == 2:
            if c in ("60", "64", "67"):
                gelir += r["credit"] - r["debit"]
            elif c == "61":
                indirim += r["debit"] - r["credit"]
            elif c in ("62", "63", "65", "66", "68") or c[0] == "7":
                gider += r["debit"] - r["credit"]
        elif c == "689":                       # K.K.E.G. — matraha geri eklenecek
            kkeg += r["debit"] - r["credit"]
    return gelir, indirim, gider, kkeg


def _acc(rows, code, side):
    """3 haneli ana hesabın dönem hareketi. side: 'd' borç, 'c' alacak."""
    for r in rows:
        if r["code"] == code:
            return r["debit"] if side == "d" else r["credit"]
    return 0.0


def _leaves(rows, prefix):
    """`prefix` altındaki EN ALT (çocuğu olmayan) hesaplar — kırılım tabloları için."""
    kids = [r for r in rows if r["code"].startswith(prefix + ".")]
    codes = {r["code"] for r in kids}
    return [r for r in kids
            if not any(o != r["code"] and o.startswith(r["code"] + ".") for o in codes)]


def _month_bounds(y, m):
    first = dt.date(y, m, 1)
    last = dt.date(y + (m == 12), (m % 12) + 1, 1) - dt.timedelta(days=1)
    return first, last


def build_vergi(env):
    """Vergi Sayfası — Elektra muhasebesinden aylık KDV, konaklama vergisi ve
    dönemsel kurumlar (geçici) vergisi hesabı."""
    today = dt.date.today()
    year = today.year

    # Cari yılın her ayı için bir mizan (ay bittiyse ay sonu, bu ay ise bugüne kadar).
    months = []
    for m in range(1, today.month + 1):
        first, last = _month_bounds(year, m)
        to = min(last, today)
        rows = E.fetch_trial_balance(first.isoformat(), to.isoformat(), env=env)
        gelir, indirim, gider, kkeg = _pl(rows)
        # Yalnızca ALACAK = o ayın tahakkuku. Borç, geçen ayın vergisinin ödenmesidir;
        # netlersek tahakkuk eksiye düşer.
        kon = sum(r["credit"] for r in _leaves(rows, "360")
                  if "KONAKLAMA" in r["name"].upper())
        months.append({
            "m": m, "kismi": (m == today.month and last > today),
            "hesaplanan": _acc(rows, "391", "c"),   # ayın hesaplanan (satış) KDV'si
            "indirilecek": _acc(rows, "191", "d"),  # ayın indirilecek (alış) KDV'si
            "konaklama": kon,
            "gelir": gelir, "indirim": indirim, "gider": gider, "kkeg": kkeg,
            "rows": rows,
        })
    # Yıl başından bugüne tek mizan — kırılım tabloları ve yıllık matrah için.
    ytd = E.fetch_trial_balance(dt.date(year, 1, 1).isoformat(), today.isoformat(), env=env)
    y_gelir, y_indirim, y_gider, y_kkeg = _pl(ytd)

    # ---- KDV: ay ay devreden mahsuplu ------------------------------------
    devreden = 0.0                       # yıl başı devreden (tarayıcıdan düzeltilebilir)
    kdv_rows, kdv_json = [], []
    for mo in months:
        onceki = devreden
        fark = mo["hesaplanan"] - mo["indirilecek"] - onceki
        odenecek = max(0.0, fark)
        devreden = max(0.0, -fark)
        mo.update(onceki=onceki, odenecek=odenecek, devreden=devreden)
        kdv_json.append({"ay": mo["m"], "h": round(mo["hesaplanan"], 2),
                         "i": round(mo["indirilecek"], 2), "kismi": mo["kismi"]})
        kdv_rows.append(
            f"<tr{' class=bad' if odenecek else ''}><td>{TR_MON_FULL[mo['m']]}"
            f"{' <span class=who>bugüne kadar</span>' if mo['kismi'] else ''}</td>"
            f"<td class='r money'>{tl(mo['hesaplanan'])}</td>"
            f"<td class='r money'>{tl(mo['indirilecek'])}</td>"
            f"<td class='r'>{tl(onceki) if onceki else '—'}</td>"
            f"<td class='r money'>{tl(odenecek) + ' ₺' if odenecek else '—'}</td>"
            f"<td class='r'>{tl(devreden) if devreden else '—'}</td>"
            f"<td class='r money'>{tl(mo['konaklama'])}</td></tr>")

    kdv_yil = sum(m["odenecek"] for m in months)
    kon_yil = sum(m["konaklama"] for m in months)
    bu_ay = months[-1]
    gecen_ay = months[-2] if len(months) > 1 else None

    kdv_tbl = (
        "<h2>1) KDV — aylık</h2>"
        "<p class='lead'>Hesaplanan KDV (satış) − İndirilecek KDV (alış) − önceki aydan devreden. "
        "Beyan ve ödeme: takip eden ayın 28'i.</p>"
        "<table><tr><th>Ay</th><th class='r'>Hesaplanan<br>KDV (satış)</th>"
        "<th class='r'>İndirilecek<br>KDV (alış)</th><th class='r'>Devreden<br>(önceki ay)</th>"
        "<th class='r'>Ödenecek KDV</th><th class='r'>Sonraki aya<br>devreden</th>"
        "<th class='r'>Konaklama<br>vergisi</th></tr>"
        + "".join(kdv_rows) +
        f"<tr><td><b>{year} toplam</b></td>"
        f"<td class='r money'>{tl(sum(m['hesaplanan'] for m in months))}</td>"
        f"<td class='r money'>{tl(sum(m['indirilecek'] for m in months))}</td><td></td>"
        f"<td class='r money'>{tl(kdv_yil)} ₺</td><td></td>"
        f"<td class='r money'>{tl(kon_yil)} ₺</td></tr></table>")

    # ---- Kurumlar / geçici vergi: kümülatif dönemler ----------------------
    kv_rows, onceki_vergi, kv_bugun, kv_donemler = [], 0.0, None, []
    for son_ay, ad, aralik, vade in KV_PERIODS:
        ms = [m for m in months if m["m"] <= son_ay]
        if not ms:
            kv_rows.append(f"<tr><td>{ad}<div class='lead'>{aralik}</div></td>"
                           "<td class='r' colspan='7'>dönem başlamadı</td></tr>")
            continue
        g = sum(m["gelir"] for m in ms) - sum(m["indirim"] for m in ms)
        gd = sum(m["gider"] for m in ms)
        kk = sum(m["kkeg"] for m in ms)
        ticari = g - gd
        matrah = max(0.0, ticari + kk)
        vergi = matrah * KV_RATE
        odenecek = max(0.0, vergi - onceki_vergi)
        tamam = today.month > son_ay
        durum = "tamamlandı" if tamam else ("yıl sonunda kesinleşir" if son_ay == 12
                                            else "devam ediyor")
        # Yıl bitmeden yıllık beyan satırı 3. dönemin kopyasıdır — rakam yazmıyoruz.
        son_hucre = (f"{tl(odenecek)} ₺" if (tamam or son_ay < 12) else "yıl sonunda")
        kv_rows.append(
            f"<tr{'' if tamam else ' class=bad'}><td>{ad}<div class='lead'>{aralik} · {durum}"
            f"<br>beyan/ödeme: {vade}</div></td>"
            f"<td class='r money'>{tl(g)}</td><td class='r money'>{tl(gd)}</td>"
            f"<td class='r money'>{tl(ticari)}</td><td class='r'>{tl(kk)}</td>"
            f"<td class='r money'>{tl(matrah)}</td><td class='r money'>{tl(vergi)}</td>"
            f"<td class='r money'>{son_hucre}</td></tr>")
        if today.month <= son_ay and kv_bugun is None:
            kv_bugun = {"ad": ad, "matrah": matrah, "vergi": vergi, "odenecek": odenecek}
        kv_donemler.append({"ad": ad, "vergi": vergi, "odenecek": odenecek, "onceki": onceki_vergi,
                            "vade": (dt.date(year, son_ay + 2, 17) if son_ay < 12
                                     else dt.date(year + 1, 4, 30))})
        onceki_vergi = vergi

    kv_tbl = (
        "<h2>2) Kurumlar (geçici) vergisi — dönemsel</h2>"
        f"<p class='lead'>Dönemler <b>kümülatif</b>tir (yıl başından itibaren); her dönemde "
        f"önceki dönemde hesaplanan vergi mahsup edilir. Oran %{int(KV_RATE*100)}. "
        "4. geçici vergi dönemi 2024'te kaldırıldı — son hesap yıllık beyannamededir.</p>"
        "<table><tr><th>Dönem</th><th class='r'>Gelir</th><th class='r'>Gider</th>"
        "<th class='r'>Ticari kâr</th><th class='r'>+ K.K.E.G.</th><th class='r'>Matrah</th>"
        f"<th class='r'>Vergi %{int(KV_RATE*100)}</th><th class='r'>Bu dönem ödenecek</th></tr>"
        + "".join(kv_rows) + "</table>")

    # ---- Gelir / gider kırılımı (yıl başından bugüne) ---------------------
    gel_pairs = sorted(((r["name"][:38], r["credit"] - r["debit"])
                        for r in _leaves(ytd, "600") + _leaves(ytd, "649") + _leaves(ytd, "679")
                        if r["credit"] - r["debit"] > 0), key=lambda t: -t[1])[:8]
    gid_pairs = sorted(((r["name"][:38], r["debit"])
                        for r in _leaves(ytd, "740") + _leaves(ytd, "770") + _leaves(ytd, "780")
                        if r["debit"] > 0), key=lambda t: -t[1])[:12]
    kirilim = (
        "<h2>3) Gelir ve gider kırılımı (yıl başından bugüne)</h2>"
        "<div class='grid2'>"
        f"<div class='card'><h3>Gelir hesapları</h3>{svg_hbars(gel_pairs) or '<div class=lead>veri yok</div>'}</div>"
        f"<div class='card'><h3>En büyük gider hesapları</h3>{svg_hbars(gid_pairs) or '<div class=lead>veri yok</div>'}</div>"
        "</div>")

    # ---- 360 Ödenecek vergi ve fonlar: tahakkuk / ödenen / kalan ----------
    v360 = sorted(_leaves(ytd, "360"), key=lambda r: -(r["credit"]))
    v360_rows = "".join(
        f"<tr><td>{esc(r['name'])}</td><td class='r money'>{tl(r['credit'])}</td>"
        f"<td class='r'>{tl(r['debit'])}</td>"
        f"<td class='r money'>{tl(r['cbal'] - r['dbal'])} ₺</td></tr>"
        for r in v360 if r["credit"] or r["debit"])
    v360_tbl = (
        "<h2>4) Muhasebede tahakkuk eden vergiler (360 hesabı)</h2>"
        "<p class='lead'>Muhasebecinizin bu yıl kayda aldığı vergi tahakkukları ve ödemeleri. "
        "“Kalan” > 0 = henüz ödenmemiş; eksi = fazla/peşin ödenmiş görünüyor. "
        "Yukarıdaki KDV tablosuyla fark varsa sebebi, muhasebecinin son ayların "
        "kapanış fişini henüz atmamış olmasıdır.</p>"
        "<table><tr><th>Vergi</th><th class='r'>Tahakkuk eden</th><th class='r'>Ödenen</th>"
        "<th class='r'>Kalan (borç)</th></tr>" + (v360_rows or
        "<tr><td colspan='4'>kayıt yok</td></tr>") + "</table>")

    # ---- Tarayıcıda düzeltme: yıl başı devreden + Elektra'da olmayan fişler
    duzelt = VERGI_ADJUST_HTML.replace("__DATA__", json.dumps(
        {"aylar": kdv_json, "gelir": round(y_gelir - y_indirim, 2),
         "gider": round(y_gider, 2), "kkeg": round(y_kkeg, 2),
         "oran": KV_RATE, "buAy": today.month,
         "adlar": TR_MON_FULL}, ensure_ascii=False))

    stats = (stat(f"{tl(bu_ay['odenecek'])} ₺", f"{TR_MON_FULL[today.month]} ödenecek KDV",
                  "bad" if bu_ay["odenecek"] else "ok")
             + stat(f"{tl(gecen_ay['odenecek']) if gecen_ay else '—'} ₺", "geçen ay KDV")
             + stat(f"{tl(bu_ay['konaklama'])} ₺", "bu ay konaklama vergisi")
             + stat(f"{tl(kv_bugun['odenecek'] if kv_bugun else 0)} ₺",
                    f"{kv_bugun['ad'] if kv_bugun else 'dönem'} kurumlar vergisi", "bad"))

    note = (
        "<div class='note'><b>Bu sayfa nereden hesaplıyor?</b> Elektra muhasebe "
        "<b>mizanından</b> (Muhasebe → Mizan). Muhasebecinizin işlediği her fatura, fiş, "
        "bordro ve banka kaydı mizanda olduğu için rakamlar beyannameyle aynı mantıkta çıkar."
        "<br>• <b>KDV</b>: 391 Hesaplanan KDV (alacak) − 191 İndirilecek KDV (borç) − devreden. "
        "191'e “sorumlu sıfatıyla” (tevkifat / 2 No'lu KDV) de dâhildir."
        "<br>• <b>Kurumlar vergisi</b>: 60/64/67 gelir − 61 iade − (62/63/65/66/68 + 7x maliyet) "
        "gider = ticari kâr; üstüne 689 K.K.E.G. eklenerek matrah bulunur."
        "<br>• <b>Konaklama vergisi</b>: 360 altındaki konaklama vergisi tahakkuku."
        f"<br>• Yalnızca <b>{year}</b> hesaplanır: kapanmış yıllarda kapanış fişleri gelir-gider "
        "hesaplarını sıfırladığı için geçmiş yıl bu yöntemle hesaplanamaz."
        "<br>• Amortisman, kıdem tazminatı karşılığı, enflasyon düzeltmesi ve yıl sonu "
        "düzeltmeleri genelde <b>yıl sonunda</b> işlenir; bu yüzden kurumlar vergisi rakamı "
        "<b>tahminidir</b>. Beyanname öncesi muhasebecinize doğrulatın.</div>")

    # ---- Üst kısım: vadeli takip (16.11.2026). Geçen ayın tahakkuku bu ay ödenir.
    if gecen_ay:
        prev_rows, kdv_prev = gecen_ay["rows"], gecen_ay["odenecek"]
    else:                                   # Ocak: geçen ay = önceki yılın Aralık'ı
        prev_rows = E.fetch_trial_balance(f"{year - 1}-12-01", f"{year - 1}-12-31", env=env)
        kdv_prev = max(0.0, _acc(prev_rows, "391", "c") - _acc(prev_rows, "191", "d"))
    try:                                    # bankadan ödenen vergiler (23.11.2026)
        b_rows = _banka_6ay(env)
        banka = _vergi_odemeleri(b_rows)
        banka_son = max((str(r.get("RECEIPTDATE"))[:10] for r in b_rows), default="")
    except Exception as e:                  # banka okunamazsa sayfa eskisi gibi çıksın
        print(f"  vergi: banka hareketleri alınamadı: {e}")
        banka, banka_son = None, ""
    takip, t_stats, t_toplam, t_acil = _vergi_takip(env, prev_rows, bu_ay["rows"], kdv_prev,
                                                    kv_donemler, banka, banka_son)
    yillik = kv_donemler[-1]["vergi"] if kv_donemler else 0.0
    t_stats += stat(f"≈ {tl(yillik)} ₺", f"{year} kurumlar vergisi (tahmini, yıllık)")

    body = (f"{BV_CSS}<div class='lock'>🔒 Yalnız yönetici</div><div class='stats'>{t_stats}</div>"
            f"{takip}<h2 style='margin-top:34px'>Hesap ayrıntısı</h2>"
            f"{kdv_tbl}{kv_tbl}{kirilim}{v360_tbl}{duzelt}{note}")
    return {"label": "Vergiler", "count": int(round(t_toplam / 1000)),
            "count_label": "bin ₺ · bu ay ödenecek vergi",
            "tone": "bad" if t_acil else ("" if t_toplam else "ok"),
            "sub": (f"{TR_MON_FULL[today.month]} ödenmemiş {tl(t_toplam)} ₺ · "
                    f"{year} KDV {tl(kdv_yil)} ₺ · kurumlar v. ≈ {tl(yillik)} ₺"),
            "updated": now_str(),
            "html": PAGE("Muhasebe", "Vergiler",
                         f"{year} · ödenecek vergiler vadesiyle, KDV, konaklama vergisi ve "
                         "kurumlar (geçici) vergisi", body)}


# --------------------------------------------------------------------------- Borçlar
# Borçlar sayfası + Vergiler sayfasının "yaklaşan ödemeler" kısmı (16.11.2026, sahibin
# isteği; taslak https://claude.ai/artifact/2nNe92nPPrdEcf9CuZSeYm). İkisi de YALNIZ
# YÖNETİM (RECEPTION_SECTIONS'ta yok).
# Kaynak TÜM ZAMANLARIN mizanı: bilanço hesaplarının (3xx/4xx) bakiyesi yıl kapanışından
# etkilenmez — kapanış fişi bakiyeyi sıfırlar, açılış fişi aynısını geri yazar.
# Elle girilen borç/vergiler (Elektra'da olmayan kredi, kredi kartı, emlak vergisi, MTV)
# site_data/elle.enc.json'da YÖNETİM parolasıyla şifreli durur (depo herkese açık);
# düzenlemek için: python3 elle_kayit.py. Yönetim parolası değişirse bu dosya da yeniden
# şifrelenmeli (kart haftaları gibi).
BORC_GRUPLARI = [   # (başlık, önekler) — sıra sayfadaki sıradır
    ("Tedarikçiler", ("320", "321", "329")),
    ("Banka kredileri", ("300", "301", "303", "304", "309", "400", "401", "405", "409")),
    ("Ödenecek vergi ve fonlar", ("360", "368", "369")),
    ("Ödenecek SGK primleri", ("361",)),
    ("Dönem kârı vergi karşılığı", ("370",)),
    ("Ortaklar ve personel", ("331", "332", "333", "335", "336")),
]
TR_TATIL = {(1, 1), (4, 23), (5, 1), (5, 19), (7, 15), (8, 30), (10, 29)}  # sabit tarihli
_MIZAN_CACHE = {}
_BILSA_CACHE = {}

BV_CSS = """<style>
.st{display:inline-block;white-space:nowrap;font-size:11.5px;font-weight:700;padding:2px 9px;border-radius:999px}
.st.bad{background:#fef2f2;color:#dc2626}.st.warn{background:#fffbeb;color:#b45309}
.st.ok{background:#f0fdf4;color:#16a34a}.st.mut{background:var(--th-bg);color:var(--sub)}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .st.bad{background:#2a1416;color:#f87171}
 :root:not([data-theme=light]) .st.warn{background:#2a2210;color:#fbbf24}
 :root:not([data-theme=light]) .st.ok{background:#0f2417;color:#4ade80}}
:root[data-theme=dark] .st.bad{background:#2a1416;color:#f87171}
:root[data-theme=dark] .st.warn{background:#2a2210;color:#fbbf24}
:root[data-theme=dark] .st.ok{background:#0f2417;color:#4ade80}
.kod{display:block;font:11.5px ui-monospace,Menlo,monospace;color:var(--sub)}
.alt{display:block;font-size:12px;color:var(--sub)}
.scroll{overflow-x:auto}
.scroll table{min-width:520px}
tr.top td{font-weight:800;border-top:2px solid var(--fg)}
.lock{display:inline-block;font-size:12px;font-weight:700;color:var(--eyebrow);background:var(--th-bg);
  border-radius:999px;padding:3px 10px;margin:-8px 0 12px}
</style>"""


def _tr_up(s):
    return (s or "").replace("i", "İ").replace("ı", "I").upper()


def _mizan_all(env):
    """Yıl başı-bugün değil, TÜM zamanlar: bilanço bakiyeleri. Aynı derlemede Borçlar ve
    Vergiler ikisi de ister; tek çağrı."""
    k = dt.date.today().isoformat()
    if k not in _MIZAN_CACHE:
        _MIZAN_CACHE[k] = E.fetch_trial_balance("2000-01-01", k, env=env)
    return _MIZAN_CACHE[k]


def _bakiye(r):
    """Alacak bakiyesi pozitif = borcumuz."""
    return r["cbal"] - r["dbal"]


def _is_gunu(d):
    """Vade tatile denk gelirse ilk iş gününe kayar (VUK 18). Dini bayramlar her yıl
    değiştiği için listede yok — sayfada not var."""
    while d.weekday() >= 5 or (d.month, d.day) in TR_TATIL:
        d += dt.timedelta(days=1)
    return d


def _elle(key):
    """site_data/elle.enc.json -> liste (yoksa/açılamazsa boş). Yönetim parolasıyla şifreli."""
    p = _pathlib.Path(__file__).resolve().parent / "site_data" / "elle.enc.json"
    cfg = E.load_env()                           # .env (yerel) + ortam değişkenleri (CI)
    pw = (cfg.get("DASH_PW_MANAGER") or cfg.get("DASH_PASSWORD") or "").strip()
    if not p.exists() or not pw:
        return []
    try:
        import dashcrypto
        return json.loads(dashcrypto.decrypt_multi(json.loads(p.read_text()), pw)).get(key, [])
    except Exception as e:                       # bozuk/eski parola: sayfa yine çıksın
        print(f"  elle.enc.json okunamadı: {e}")
        return []


def _bilsa(env):
    """Bilsa carisi: yaprak hesap, ay sonu bakiyeleri (cari yıl), yıl toplamları, son
    hareketler ve bu yılki gider (KDV hariç). Hesap bulunamazsa None."""
    k = dt.date.today().isoformat()
    if k in _BILSA_CACHE:
        return _BILSA_CACHE[k]
    hes = next((r for r in _leaves(_mizan_all(env), "320")
                if "BİLSA" in _tr_up(r["name"]) or "BILSA" in _tr_up(r["name"])), None)
    if not hes:
        _BILSA_CACHE[k] = None
        return None
    today = dt.date.today()
    rows = [r for r in (E.fetch_account_statement(hes["code"], env=env) or [])
            if not any(w in _tr_up(r.get("RECEIPTNOTES")) for w in ("KAPANIŞ", "AÇILIŞ"))]

    def tarih(r):
        return str(r.get("RECEIPTDATE") or "")[:10]

    def fatura_mi(r):
        return (r.get("DOCTYPE") == "Fatura" or bool(r.get("INVOICENUMBER"))
                or "FATURA" in _tr_up(r.get("DETAILNOTES")))

    ay_sonu = []
    for m in range(1, today.month + 1):
        _, last = _month_bounds(today.year, m)
        d = min(last, today).isoformat()
        ay_sonu.append((TR_MONTHS[m], sum(num(r.get("LOCALCREDIT")) - num(r.get("LOCALDEBIT"))
                                          for r in rows if tarih(r) <= d)))
    yil = [r for r in rows if tarih(r)[:4] == str(today.year)]
    fat = [r for r in yil if fatura_mi(r)]
    diger = [r for r in yil if not fatura_mi(r)]
    # Bu yılki gider = brüt fatura − faturadaki KDV (aynı fişin 191 satırı).
    fis = {r.get("RECEIPTID") for r in fat}
    kdv = sum(num(r.get("LOCALDEBIT")) - num(r.get("LOCALCREDIT"))
              for r in (E.fetch_account_statement("191", f"{today.year}-01-01",
                                                  today.isoformat(), env=env) or [])
              if r.get("RECEIPTID") in fis)
    brut = sum(num(r.get("LOCALCREDIT")) - num(r.get("LOCALDEBIT")) for r in fat)

    def aciklama(r):
        if fatura_mi(r):
            no = r.get("INVOICENUMBER") or r.get("DOCNO") or ""
            return ("Fatura iptali " if num(r.get("LOCALDEBIT")) else "Fatura ") + no
        if num(r.get("LOCALDEBIT")):
            return "Ödeme"
        n = _tr_up(r.get("DETAILNOTES"))
        return "Bilsa'dan gelen havale" if any(w in n for w in ("FAST", "EFT", "HAV")) \
            else (r.get("DETAILNOTES") or "")[:60]

    son = sorted(rows, key=lambda r: (tarih(r), r.get("ID") or 0), reverse=True)[:8]
    faturalar = sorted((r for r in fat if num(r.get("LOCALCREDIT"))), key=tarih)
    odemeler = sorted((r for r in diger if num(r.get("LOCALDEBIT"))), key=tarih)
    out = {
        "code": hes["code"], "name": hes["name"], "bakiye": _bakiye(hes), "ay_sonu": ay_sonu,
        # Adet: farklı fatura numarası (iptal edilip yeniden kaydedilen fatura bir kez sayılır).
        "fatura": brut, "kdv": kdv, "gider": brut - kdv,
        "adet": len({r.get("INVOICENUMBER") or (r.get("DETAILNOTES") or "").split(" ")[0]
                     for r in faturalar}),
        "odenen": sum(num(r.get("LOCALDEBIT")) for r in diger),
        "gelen": sum(num(r.get("LOCALCREDIT")) for r in diger),
        "son_fatura": faturalar[-1] if faturalar else None,
        "son_odeme": odemeler[-1] if odemeler else None,
        "son": [(tarih(r), aciklama(r), num(r.get("LOCALCREDIT")) - num(r.get("LOCALDEBIT")))
                for r in son],
    }
    _BILSA_CACHE[k] = out
    return out


def _tr_d(iso):
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if iso else "—"


def build_borclar(env):
    """Borçlar — Elektra muhasebesindeki tüm borç hesapları + Bilsa carisi + elle girilenler."""
    today = dt.date.today()
    mz = _mizan_all(env)
    gruplar, toplam = [], 0.0
    for ad, onekler in BORC_GRUPLARI:
        ls = [r for p in onekler for r in (_leaves(mz, p) or [x for x in mz if x["code"] == p])]
        ls = [r for r in ls if abs(_bakiye(r)) >= 1]
        net = sum(_bakiye(r) for r in ls)
        if ls:
            gruplar.append((ad, net, sorted(ls, key=lambda r: -_bakiye(r))))
        if net > 0:
            toplam += net
    elle = _elle("borclar")
    elle_top = sum(num(b.get("tutar")) for b in elle)
    toplam += elle_top
    bilsa = _bilsa(env)

    # ---- özet kutuları
    g = dict((ad, net) for ad, net, _ in gruplar)
    vergi_sgk = sum(max(0.0, g.get(k, 0.0)) for k in
                    ("Ödenecek vergi ve fonlar", "Ödenecek SGK primleri", "Dönem kârı vergi karşılığı"))
    tedarik = g.get("Tedarikçiler", 0.0)
    stats = stat(f"{tl(toplam)} ₺", "toplam borç")
    if bilsa:
        gecen = bilsa["ay_sonu"][-2][1] if len(bilsa["ay_sonu"]) > 1 else None
        fark = f" · bu ay {'+' if bilsa['bakiye'] - gecen >= 0 else ''}{tl(bilsa['bakiye'] - gecen)}" \
            if gecen is not None else ""
        stats += stat(f"{tl(bilsa['bakiye'])} ₺", "Bilsa Bilgisayar Yazılım" + fark, "bad")
        stats += stat(f"{tl(tedarik - bilsa['bakiye'])} ₺", "diğer tedarikçiler")
    else:
        stats += stat(f"{tl(tedarik)} ₺", "tedarikçiler")
    stats += stat(f"{tl(vergi_sgk)} ₺", "vergi, SGK ve vergi karşılığı")
    if g.get("Banka kredileri"):
        stats += stat(f"{tl(g['Banka kredileri'])} ₺", "banka kredisi")

    # ---- Bilsa kartı
    bilsa_html = ""
    if bilsa:
        lbl = [a for a, _ in bilsa["ay_sonu"]]
        val = [max(0.0, v) for _, v in bilsa["ay_sonu"]]
        sf, so = bilsa["son_fatura"], bilsa["son_odeme"]
        mini = "".join(
            f"<div class='vrow'><span>{esc(a)}</span><span class='money'>{b}</span></div>" for a, b in (
                (f"{today.year} faturalar ({bilsa['adet']})", f"{tl(bilsa['fatura'])} ₺"),
                (f"{today.year} ödenen", f"{tl(bilsa['odenen'])} ₺"),
                ("Bilsa'dan gelen", f"{tl(bilsa['gelen'])} ₺"),
                ("Son fatura", f"{_tr_d(str(sf['RECEIPTDATE'])[:10])} · {tl(num(sf['LOCALCREDIT']))} ₺" if sf else "—"),
                ("Son ödeme", f"{_tr_d(str(so['RECEIPTDATE'])[:10])} · {tl(num(so['LOCALDEBIT']))} ₺" if so else "—")))
        hareket = "".join(
            f"<tr><td>{_tr_d(t)}</td><td>{esc(a)}</td>"
            f"<td class='r money'>{'+' if v > 0 else ''}{tl(v)}</td></tr>" for t, a, v in bilsa["son"])
        bilsa_html = (
            f"<h2>Bilsa — {today.year} ay sonu borç</h2>"
            "<p class='lead'>Her ay sonundaki borç (bu ay: bugüne kadar). Faturalar borcu artırır, "
            f"ödemeler azaltır. Elektra hesabı <b>{esc(bilsa['code'])}</b>.</p>"
            "<div class='grid2'>"
            f"<div class='card'>{svg_bars(lbl, val, fmt=lambda v: tl(v) + ' ₺')}{mini}</div>"
            "<div class='card'><h3>Son hareketler</h3><div class='scroll'><table>"
            "<tr><th>Tarih</th><th>Açıklama</th><th class='r'>Tutar</th></tr>"
            f"{hareket}</table></div></div></div>")

    # ---- grup tabloları
    def tablo(ad, net, ls, ilk=12):
        satir = "".join(
            f"<tr><td>{esc(r['name'])}<span class='kod'>{esc(r['code'])}</span></td>"
            f"<td class='r money'>{tl(_bakiye(r))}</td></tr>" for r in ls[:ilk])
        if len(ls) > ilk:
            kalan = sum(_bakiye(r) for r in ls[ilk:])
            satir += (f"<tr><td>Diğer {len(ls) - ilk} hesap<span class='alt'>eksi bakiyeli "
                      f"(fazla ödenmiş) hesaplar da dahil</span></td><td class='r money'>{tl(kalan)}</td></tr>")
        not_ = ("<p class='lead'>Toplam eksi: bu hesaplarda fazla ödeme/avans var; borç toplamına "
                "katılmadı.</p>" if net <= 0 else "")
        return (f"<h2>{esc(ad)}</h2>{not_}<div class='scroll'><table><tr><th>Hesap</th>"
                f"<th class='r'>Borç (₺)</th></tr>{satir}<tr class='top'><td>Toplam</td>"
                f"<td class='r'>{tl(net)}</td></tr></table></div>")
    tablolar = "".join(tablo(*x) for x in gruplar)

    if elle:
        es = "".join(f"<tr><td>{esc(b.get('ad'))}</td><td>{esc(b.get('vade') or '—')}</td>"
                     f"<td class='r money'>{tl(b.get('tutar'))}</td></tr>" for b in elle)
        elle_html = (f"<div class='scroll'><table><tr><th>Borç</th><th>Vade</th>"
                     f"<th class='r'>Tutar (₺)</th></tr>{es}<tr class='top'><td colspan='2'>Toplam</td>"
                     f"<td class='r'>{tl(elle_top)}</td></tr></table></div>")
    else:
        elle_html = ("<div class='card'><span class='alt'>Henüz eklenmedi. Şahsi kredi, kredi "
                     "kartı, elden borç gibi Elektra'da olmayan borçlarınızı Claude'a yazın, buraya "
                     "eklensin; toplam borca dahil edilir.</span></div>")

    body = (BV_CSS + "<div class='lock'>🔒 Yalnız yönetici</div>"
            f"<div class='stats'>{stats}</div>{bilsa_html}{tablolar}"
            f"<h2>Elektra dışındaki borçlar</h2>{elle_html}"
            "<div class='note'>Kaynak: Elektra muhasebe mizanı (tüm yıllar), yaprak hesap "
            "bakiyeleri. Toplam borç = tedarikçiler + banka + vergi/SGK + vergi karşılığı + "
            "elle eklenenler; toplamı eksi çıkan grup (fazla ödeme) katılmaz. Alınan avanslar "
            "(misafir ön ödemeleri) borç sayılmadı.</div>")
    return {"label": "Borçlar", "count": int(round(toplam / 1000)), "count_label": "bin ₺ · toplam borç",
            "tone": "", "updated": now_str(),
            "sub": (f"toplam {tl(toplam)} ₺" + (f" · Bilsa {tl(bilsa['bakiye'])} ₺" if bilsa else "")),
            "html": PAGE("Muhasebe", "Borçlar",
                         f"{today.day:02d}.{today.month:02d}.{today.year} · Elektra muhasebesindeki "
                         "tüm borç hesapları", body)}


def _vergi_takip(env, prev_rows, cur_rows, kdv_prev, kv_donemler, banka=None, banka_son=""):
    """Vergiler sayfasının üst kısmı: yaklaşan ödemeler (geçen ayın tahakkuku, bu ay vadeli),
    Elektra'da kapanmamış vergi bakiyeleri, yıllık takvim, Bilsa'nın vergi etkisi.
    Döner: (html, stats, en_yakin, bu_ay_odenecek, gecikmis_ya_da_yakin)."""
    today = dt.date.today()
    ay, yil = today.month, today.year
    pm = 12 if ay == 1 else ay - 1
    son_gun = _month_bounds(yil, ay)[1]

    def leaves(rows, p):
        return {r["code"]: r for r in _leaves(rows, p)}
    p360, c360 = leaves(prev_rows, "360"), leaves(cur_rows, "360")
    p361, c361 = leaves(prev_rows, "361"), leaves(cur_rows, "361")

    def sec(d, *kel, haric=()):
        return [c for c, r in d.items() if any(k in _tr_up(r["name"]) for k in kel)
                and not any(h in _tr_up(r["name"]) for h in haric)]

    def tahakkuk(d, codes):
        return sum(d[c]["credit"] for c in codes if c in d)

    def odenen(codes, d):
        return sum(d[c]["debit"] for c in codes if c in d)

    kalemler = []   # (vade, ad, alt, tutar, odendi, kaydi) — odendi: False | True | "bankada 17.11"

    def bankada(turler, bitis=None):
        """Bu ayın (tahakkuk ayı) şirket adına bankadan ödenen tutarı ve son ödeme günü."""
        ps = [p for p in (banka or []) if p["sirket"] and p["tur"] in turler and p["ay"] == (yil, ay)]
        return sum(p["tutar"] for p in ps), max((p["d"] for p in ps), default=None)

    def odeme_durumu(tutar, elektra_odenen, turler):
        b, bd = bankada(turler)
        if tutar > 0 and b >= tutar * 0.99 or (not tutar and b > 0):
            return f"bankada {bd.day:02d}.{bd.month:02d} · {tl(b)} ₺"
        if tutar > 0 and elektra_odenen >= tutar * 0.99:
            return True
        return False

    def ekle(gun, ad, alt, tutar, codes, cur, turler=()):
        vade = _is_gunu(son_gun if gun == "son" else dt.date(yil, ay, gun))
        odendi = odeme_durumu(tutar, odenen(codes, cur), turler)
        kalemler.append((vade, ad, alt, tutar, odendi, gun != "son" and vade.day != gun))

    mh = sec(p360, "GELİR VERGİSİ", "DAMGA", "SERBEST MESLEK", haric=("YILLIK",))
    ekle(26, "Muhtasar: gelir vergisi stopajı + damga", "", tahakkuk(p360, mh), mh, c360,
         ("Muhtasar (stopaj)", "Damga vergisi"))
    kdvc = sec(p360, "KDV", haric=("TEVKİFAT",))
    ekle(28, "KDV-1", "hesaplanan − indirilecek − devreden", kdv_prev, kdvc, c360, ("KDV-1",))
    tv = sec(p360, "TEVKİFAT")
    ekle(28, "KDV-2 (tevkifat, sorumlu sıfatıyla)", "", tahakkuk(p360, tv), tv, c360, ("KDV-2 (tevkifat)",))
    kon = sec(p360, "KONAKLAMA")
    ekle(28, "Konaklama vergisi", "", tahakkuk(p360, kon), kon, c360, ("Konaklama vergisi",))
    # Turizm payı: muhasebeci KDV ile aynı gün ödüyor (banka kayıtları). Mizanda ayrı
    # tahakkuk yoksa tutar = geçen ay bankadan ödenen (tahmini).
    tp = sec(p360, "TURİZM", "TURIZM")
    tp_tut, tp_alt = tahakkuk(p360, tp), ""
    if not tp_tut and banka:
        g = (yil - (ay == 1), 12 if ay == 1 else ay - 1)
        tp_tut = sum(p["tutar"] for p in banka if p["sirket"] and p["tur"] == "Turizm payı" and p["ay"] == g)
        tp_alt = "tahmini: geçen ay ödenen" if tp_tut else ""
    if tp_tut or bankada(("Turizm payı",))[0]:
        ekle(28, "Turizm payı", tp_alt, tp_tut, tp, c360, ("Turizm payı",))
    ekle("son", "SGK + işsizlik primi", "", tahakkuk(p361, list(p361)), list(p361), c361, ("SGK primi",))
    # Geçici vergi: vadesi bu ay olan dönem (Mayıs/Ağustos/Kasım 17'si).
    for d in kv_donemler:
        if d["vade"].year == yil and d["vade"].month == ay:
            kalemler.append((_is_gunu(d["vade"]), "Geçici vergi " + d["ad"],
                             f"kümülatif {tl(d['vergi'])}, önceki dönemler {tl(d['onceki'])}",
                             d["odenecek"], odeme_durumu(d["odenecek"], 0.0, ("Geçici vergi",)), False))
    for v in _elle("vergiler"):
        try:
            vd = dt.date.fromisoformat(str(v.get("vade")))
        except ValueError:
            continue
        if vd.year == yil and vd.month == ay:
            kalemler.append((_is_gunu(vd), v.get("ad", "—"), "elle girildi", num(v.get("tutar")),
                             bool(v.get("odendi")), False))
    kalemler.sort(key=lambda k: k[0])

    def durum(vade, tutar, odendi):
        if odendi:
            return ("<span class='st ok'>Ödendi</span>"
                    + (f"<span class='alt'>{esc(odendi)}</span>" if isinstance(odendi, str) else ""))
        if not tutar:
            return "<span class='st mut'>ödeme yok</span>"
        kalan = (vade - today).days
        if kalan < 0:
            return f"<span class='st bad'>{-kalan} gün geçti</span>"
        if kalan == 0:
            return "<span class='st bad'>bugün</span>"
        return f"<span class='st {'bad' if kalan <= 3 else 'warn'}'>{kalan} gün</span>"

    satir, toplam, acik = [], 0.0, []
    for vade, ad, alt, tutar, odendi, kaydi in kalemler:
        if not odendi and tutar:
            toplam += tutar
            acik.append((vade, ad, tutar))
        kayma = f"<span class='alt'>asıl gün tatile denk geldi</span>" if kaydi else ""
        satir.append(
            f"<tr{' class=bad' if (not odendi and tutar and (vade - today).days <= 3) else ''}>"
            f"<td>{vade.day:02d}.{vade.month:02d} {DAY_ABBR[vade.weekday()]}{kayma}</td>"
            f"<td>{esc(ad)}{f'<span class=alt>{esc(alt)}</span>' if alt else ''}</td>"
            f"<td class='r money'>{tl(tutar)}</td><td>{durum(vade, tutar, odendi)}</td></tr>")
    yaklasan = (
        f"<h2>{TR_MON_FULL[ay]} ödemeleri ({TR_MON_FULL[pm]} dönemi)</h2>"
        "<p class='lead'>Tutarlar geçen ayın muhasebe tahakkukundan. Vade tatile denk gelirse ilk iş "
        "gününe kayar (dini bayramlar hariç, onları kontrol edin). Bankadan ödeme (muhasebecinin "
        "işlediği banka hareketi) ya da Elektra'da ödeme kaydı görülünce satır kendiliğinden "
        "<b>Ödendi</b> olur"
        + (f"; son banka kaydı <b>{_tr_d(banka_son)}</b>, sonrasında yapılan ödeme henüz görünmez"
           if banka_son else "") + ".</p>"
        "<div class='scroll'><table><tr><th>Vade</th><th>Vergi</th><th class='r'>Tutar (₺)</th>"
        f"<th>Durum</th></tr>{''.join(satir)}<tr class='top'><td colspan='2'>Ödenmemiş toplam</td>"
        f"<td class='r'>{tl(toplam)}</td><td></td></tr></table></div>")

    # ---- Elektra'da kapanmamış vergi bakiyeleri (beklenen = geçen ay + bu ay tahakkuku)
    mz = _mizan_all(env)
    kap, kap_top = [], 0.0
    for p in ("360", "361", "370"):
        pr, cr = leaves(prev_rows, p), leaves(cur_rows, p)
        for r in _leaves(mz, p):
            bak = _bakiye(r)
            if bak < 1:
                continue
            bek = 0.0 if p == "370" else (pr.get(r["code"], {}).get("credit", 0.0)
                                          + cr.get(r["code"], {}).get("credit", 0.0))
            fark = bak - bek
            if fark >= 1:
                kap.append((r, bak, bek, fark))
                if p != "370":
                    kap_top += fark
    kap.sort(key=lambda t: -t[3])
    kap_html = (
        "<h2>Elektra'da kapanmamış vergi bakiyeleri</h2>"
        "<p class='lead'>Geçen ayın ve bu ayın tahakkukundan <b>fazla</b> duran bakiye: ya eski bir "
        "ay ödenmemiş ya da ödemesi Elektra'ya işlenmemiş. Mali müşavirinize sorun. "
        "Dönem kârı vergi karşılığı yıllık kurumlar vergisi ödenince kapanır.</p>"
        "<div class='scroll'><table><tr><th>Hesap</th><th class='r'>Bakiye</th>"
        "<th class='r'>Son 2 ay tahakkuku</th><th class='r'>Fark</th></tr>"
        + "".join(f"<tr><td>{esc(r['name'])}<span class='kod'>{esc(r['code'])}</span></td>"
                  f"<td class='r'>{tl(b)}</td><td class='r'>{tl(e) if e else '—'}</td>"
                  f"<td class='r money'>{tl(f)}</td></tr>" for r, b, e, f in kap)
        + (f"<tr class='top'><td colspan='3'>Toplam (vergi karşılığı hariç)</td>"
           f"<td class='r'>{tl(kap_top)}</td></tr>" if kap else
           "<tr><td colspan='4'>Kapanmamış eski bakiye yok ✓</td></tr>")
        + "</table></div>")

    # ---- yıllık takvim + Bilsa etkisi
    yillik = next((d for d in kv_donemler if d["ad"] == "Yıllık beyan"), None)
    gecici_odenen = max((d["vergi"] for d in kv_donemler if d["ad"] != "Yıllık beyan"
                         and d["vade"] < today), default=0.0)
    takvim = (
        "<h2>Yıllık takvim</h2><div class='scroll'><table><tr><th>Ne zaman</th><th>Ne</th></tr>"
        "<tr><td>Her ay 26'sı</td><td>Muhtasar ve prim hizmet beyannamesi</td></tr>"
        "<tr><td>Her ay 28'i</td><td>KDV-1, KDV-2, konaklama vergisi</td></tr>"
        "<tr><td>Her ay sonu</td><td>SGK primi ödemesi</td></tr>"
        "<tr><td>17 Mayıs · 17 Ağustos · 17 Kasım</td><td>Geçici vergi (3 dönem)</td></tr>"
        f"<tr><td>30 Nisan {yil + 1}</td><td>{yil} kurumlar vergisi"
        + (f"<span class='alt'>bugünkü tahmin {tl(yillik['vergi'])} − geçici vergide ödenen "
           f"{tl(gecici_odenen)} = ≈ {tl(max(0.0, yillik['vergi'] - gecici_odenen))}</span>"
           if yillik else "") + "</td></tr>"
        "<tr><td>Ocak · Temmuz sonu</td><td>Motorlu taşıtlar vergisi (Elektra'da yok, elle)</td></tr>"
        "<tr><td>Mayıs · Kasım sonu</td><td>Emlak vergisi (Elektra'da yok, elle)</td></tr>"
        "<tr><td>Her ay 28'i civarı</td><td>Turizm payı (muhasebeci KDV ile aynı gün ödüyor)</td></tr>"
        "</table></div>")
    bilsa = _bilsa(env)
    bilsa_html = ""
    if bilsa and bilsa["gider"] > 0:
        etki = bilsa["gider"] * KV_RATE
        bilsa_html = (
            f"<h2>Bilsa faturalarının {yil} kurumlar vergisine etkisi</h2>"
            f"<p class='lead'>Bu yıl Bilsa'dan {bilsa['adet']} fatura: brüt {tl(bilsa['fatura'])} ₺, "
            f"KDV {tl(bilsa['kdv'])} ₺, gider <b>{tl(bilsa['gider'])} ₺</b>. Kâr bu tutardan büyük "
            f"kaldıkça vergiyi %{int(KV_RATE * 100)} oranında, yani yaklaşık <b>{tl(etki)} ₺</b> "
            "azaltır. Hizmetin gerçek, sözleşmeyle belgeli ve piyasa fiyatında olması şarttır.</p>")

    en_yakin = min(acik, default=None)
    stats = (stat(f"{en_yakin[0].day:02d}.{en_yakin[0].month:02d}" if en_yakin else "—",
                  f"en yakın vade · {en_yakin[1]}" if en_yakin else "bu ay ödenmemiş vergi yok",
                  "bad" if en_yakin and (en_yakin[0] - today).days <= 3 else "")
             + stat(f"{tl(toplam)} ₺", f"{TR_MON_FULL[ay]} ödenmemiş", "bad" if toplam else "ok")
             + stat(f"{tl(kap_top)} ₺", "Elektra'da kapanmamış eski bakiye", "bad" if kap_top else "ok"))
    acil = any((v - today).days <= 3 for v, _, _ in acik)
    banka_html = _vergi_banka_tablo(banka, banka_son) if banka else ""
    return (yaklasan + banka_html + kap_html + takvim + bilsa_html, stats, toplam, acil)


# Tarayıcı-içi düzeltme kartı: yıl başı devreden KDV + Elektra'ya HENÜZ girilmemiş
# fiş/gider satırları. Hiçbir şey sunucuya gitmez; localStorage'da durur (parite
# sayfasındaki fiyat girişiyle aynı mantık).
VERGI_ADJUST_HTML = """
<h2>5) Elle düzeltme — Elektra'da görünmeyen fiş/gider</h2>
<p class='lead'>Muhasebeye <b>henüz girilmemiş</b> fişleri buraya yazın; KDV ve kurumlar
vergisi rakamı anında güncellensin. Girdikleriniz yalnızca bu tarayıcıda saklanır.</p>
<div class='card'>
  <div class='grid2'>
    <div><label>Yıl başından devreden KDV (₺)</label><input id='dev0' type='number' step='0.01' value='0'></div>
    <div><label>Hangi ay için hesaplansın?</label><select id='aysec'></select></div>
  </div>
  <div id='fisler'></div>
  <div class='btnrow'><button class='btn' id='ekle'>+ Fiş/gider satırı ekle</button>
    <button class='btn ghost' id='temizle'>Temizle</button></div>
  <div id='sonuc'></div>
</div>
<script>
(function(){
  var D = __DATA__;
  var KEY = 'riva_vergi_v1';
  var st = {dev0:0, ay:D.buAy, fis:[]};
  try { var s = JSON.parse(localStorage.getItem(KEY)||'null'); if (s) st = Object.assign(st, s); } catch(e){}
  var $ = function(id){ return document.getElementById(id); };
  var money = function(v){ return (v<0?'-':'') + Math.abs(v).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2}); };

  var sel = $('aysec');
  D.aylar.forEach(function(a){
    var o = document.createElement('option');
    o.value = a.ay; o.textContent = D.adlar[a.ay] + (a.kismi ? ' (bugüne kadar)' : '');
    sel.appendChild(o);
  });

  function fisRows(){
    var h = '';
    st.fis.forEach(function(f,i){
      h += "<div class='grid2' style='margin-top:8px;align-items:end'>"
        +  "<div><label>Açıklama</label><input data-i='"+i+"' data-k='ad' value='"+(f.ad||'').replace(/"/g,'&quot;')+"' placeholder='ör. market fişi'></div>"
        +  "<div style='display:flex;gap:8px'>"
        +    "<div style='flex:1'><label>Tutar (KDV dâhil ₺)</label><input data-i='"+i+"' data-k='tutar' type='number' step='0.01' value='"+(f.tutar||0)+"'></div>"
        +    "<div style='width:110px'><label>KDV oranı</label><select data-i='"+i+"' data-k='oran'>"
        +      [0,1,10,20].map(function(o){ return "<option value='"+o+"'"+((+f.oran===o)?" selected":"")+">%"+o+"</option>"; }).join('')
        +    "</select></div>"
        +    "<div style='width:44px'><label>&nbsp;</label><button class='btn ghost' data-sil='"+i+"' style='width:100%'>✕</button></div>"
        +  "</div></div>";
    });
    $('fisler').innerHTML = h;
  }

  function hesapla(){
    var ay = +sel.value || D.buAy;
    var exKdv = 0, kdv = 0;
    st.fis.forEach(function(f){
      var t = +f.tutar || 0, o = +f.oran || 0;
      var net = t / (1 + o/100);
      exKdv += net; kdv += t - net;
    });
    // KDV: yıl başı devredenden başlayarak seçilen aya kadar zincirle
    var dev = +st.dev0 || 0, satir = null;
    D.aylar.forEach(function(a){
      var ind = a.i + (a.ay === ay ? kdv : 0);
      var fark = a.h - ind - dev;
      var ode = Math.max(0, fark);
      dev = Math.max(0, -fark);
      if (a.ay === ay) satir = {h:a.h, i:ind, ode:ode, dev:dev};
    });
    // Kurumlar vergisi matrahı: yıllık gider fişlerin KDV'siz bedeli kadar artar
    var matrah = Math.max(0, D.gelir - (D.gider + exKdv) + D.kkeg);
    var vergi = matrah * D.oran;
    $('sonuc').innerHTML =
      "<div class='vrow'><span>"+D.adlar[ay]+" hesaplanan KDV</span><span class='money'>"+money(satir.h)+" ₺</span></div>"
    + "<div class='vrow'><span>"+D.adlar[ay]+" indirilecek KDV (fişler dâhil)</span><span class='money'>"+money(satir.i)+" ₺</span></div>"
    + "<div class='vrow'><span><b>"+D.adlar[ay]+" ödenecek KDV</b></span><span class='"+(satir.ode?'miss':'match')+"'>"+money(satir.ode)+" ₺</span></div>"
    + (satir.dev ? "<div class='vrow'><span>sonraki aya devreden</span><span class='money'>"+money(satir.dev)+" ₺</span></div>" : "")
    + "<div class='vrow' style='margin-top:6px'><span>Yıllık kurumlar vergisi matrahı (fişler dâhil)</span><span class='money'>"+money(matrah)+" ₺</span></div>"
    + "<div class='vrow'><span><b>Yıllık kurumlar vergisi (%"+(D.oran*100)+")</b></span><span class='miss'>"+money(vergi)+" ₺</span></div>"
    + (exKdv ? "<div class='muted' style='margin-top:8px'>Eklenen fişler: "+money(exKdv)+" ₺ KDV'siz gider + "+money(kdv)+" ₺ indirilecek KDV</div>" : "");
  }

  function kaydet(){ try { localStorage.setItem(KEY, JSON.stringify(st)); } catch(e){} }
  function ciz(){ fisRows(); hesapla(); }

  document.addEventListener('input', function(e){
    var t = e.target;
    if (t.id === 'dev0') { st.dev0 = +t.value || 0; kaydet(); hesapla(); return; }
    if (t.dataset && t.dataset.k !== undefined) {
      st.fis[+t.dataset.i][t.dataset.k] = t.value; kaydet(); hesapla();
    }
  });
  document.addEventListener('change', function(e){
    if (e.target.id === 'aysec') hesapla();
    if (e.target.dataset && e.target.dataset.k === 'oran') { st.fis[+e.target.dataset.i].oran = e.target.value; kaydet(); hesapla(); }
  });
  document.addEventListener('click', function(e){
    if (e.target.id === 'ekle') { st.fis.push({ad:'', tutar:0, oran:20}); kaydet(); ciz(); }
    else if (e.target.id === 'temizle') { st.fis = []; st.dev0 = 0; $('dev0').value = 0; kaydet(); ciz(); }
    else if (e.target.dataset && e.target.dataset.sil !== undefined) { st.fis.splice(+e.target.dataset.sil,1); kaydet(); ciz(); }
  });

  $('dev0').value = st.dev0 || 0;
  sel.value = st.ay || D.buAy;
  sel.addEventListener('change', function(){ st.ay = +sel.value; kaydet(); });
  ciz();
})();
</script>
"""


# --------------------------------------------------------------------------- Fiyat Kontrol
# Sahibin kararı (15.10.2026; fiyat listesi 27.10.2026, docs/pricelist/fiyat-listesi.md): aynı oda,
# aynı gece için misafir HER kanalda aynı fiyatı görür. Telefonda ve kapıda İNDİRİM YOK: tablo tabandır
# (eski "en fazla 300 TL" kuralı 27.10'da kaldırıldı — indirim cebe atılıyordu). Fiyatlar iade
# edilebilir, TL, 1–2 kişi, kahvaltı dahil. Her odanın üç basamağı var; gecenin basamağı tarihe (aynı
# gün mü, ileri tarih mi), Cumartesi'ye ve o gece satılmış oda sayısına bağlı → basamak().
# Elektra'da baz fiyat EUR'dur (= TL ÷ günün kuru); fiyat_bandi.py yarım saatte bir uygular.
FIYAT_ODALAR = (  # (anahtar, ad, alt yazı, (1., 2., 3., 4., 5. basamak)) — 11.11.2026 listesi
    ("eko", "Ekonomik", "balkonlu · yalnızca site, telefon, kapı", (2800, 3100, 3300, 3600, 3800)),
    ("stu", "Stüdyo", "mutfaklı", (3000, 3300, 3500, 3800, 4000)),
    ("sup", "Superior", "mutfaklı / mutfaksız", (3200, 3500, 3800, 4000, 4200)),
    ("dlx", "Deluxe", "mutfaklı / balkonlu", (3600, 3800, 4000, 4300, 4500)),
    ("sui", "1+1 Suit", "mutfaklı", (4300, 4700, 5000, 5300, 5500)),
)
# 11.11.2026 (sahibi): Pazar–Perşembe 1. basamaktan, Cuma–Cumartesi 2. basamaktan başlar; o gece 25, 30 ve
# 35 oda satılınca birer basamak çıkar (25. oda satılınca 26. oda yeni fiyattan). 35'ten sonra artış yok.
# Aynı gün kuralı yok. Eski (04.11) listenin 3 basamağı yeni listenin 1., 3. ve 5. basamağıdır.
ESIK_ODA = (25, 30, 35)
BASAMAK_ADI = ("1. basamak", "2. basamak", "3. basamak", "4. basamak", "5. basamak")
YENI_LISTE = dt.date(2026, 11, 11)     # bu tarihten önce satılanlar eski (30/40 oda, aynı gün) kuralla
# Sahibin tek gecelik kararı: o gecenin bütün oda fiyatlarından bu kadar TL düşülür (liste bozulmaz).
# Pano, kapı fiyatı, Günlük Rapor ve fiyat_bandi.py bunu okur; geçmiş geceler zararsızdır.
GECE_INDIRIM = {dt.date(2026, 10, 31): 300}
ELLE_FIYAT = {  # sahibinin elle girdiği kısa süreli fiyat: (gece, oda) → misafirin gördüğü TL; fiyat_bandi.py bu gecelere dokunmaz
    # 9–10.11 Stüdyo 40 € kaldırıldı: sahibi 09.11 sabah Elektra'da listeye döndürdü (33 oda dolu → 3.500)
    # 23–24.11 Stüdyo 40 € kaldırıldı: sahibi 18.11 12:35'te Elektra'da listeye döndürdü (GetLog)
}
# Sahibinin elle fiyat girdiği BÜTÜN gece (yılbaşı gibi): her oda tipi korunur; değer, girdiği günün
# Elektra fiyatının TL karşılığı (panel hedefi). Sahibi "fiyat güncellemesinde bunlara dokunma" (09.11.2026).
ELLE_GECE = {
    dt.date(2026, 12, 31): {"eko": 3300, "stu": 3500, "sup": 3800, "dlx": 4000, "sui": 5000},  # yılbaşı
}
ELLE_FIYAT.update({(d, k): v for d, odalar in ELLE_GECE.items() for k, v in odalar.items()})
# Uzun konaklama 27.10 listesinde değişmedi: taban = 24.10 listesinin Paz–Pzt normal fiyatı,
# 7+ / 14+ / 28+ gece −300 / −500 / −700 TL (site uzun_konaklama.py da bunu okur).
UZUN_BAZ = {"stu": 3500, "sup": 3700, "dlx": 3900, "sui": 4500}
UZUN_INDIRIM = ((28, 700), (14, 500), (7, 300))
UYESIZ_OKUMA = {"hotels": 0.10}   # bu kanalın trivago okuması üye indirimi olmadan; üye indirimi oranı
FIYAT_TOLERANS = 40     # hedeften ±40 TL "hedefte" sayılır (kanallar Euro'yu kendi kuruyla çevirir)
GUN_ADI = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
GUN_KISA = ("Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz")

# anahtar → (görünen ad, Elektra kanal adı, kanaldaki TEK indirim, etiket, açık fiyat notu).
# Elektra adı "" = otelin kendi sitesi (çarpan 1); None = Elektra'ya bağlı değil (yalnızca
# görülen fiyat gösterilir). İndirim, misafirin bulabileceği en düşük fiyata inen toplam
# orandır; Booking/Expedia/Trip'te yalnızca üye/mobil misafire uygulanır, giriş yapmayan
# çarpanlı fiyatı görür (açık fiyat).
FIYAT_KANALLAR = {
    "site":       ("Kendi siteniz", "", 0.0, "indirim yok", ""),
    "booking":    ("Booking", "Booking.com", 0.19, "Basic %10 + Genius %10 birleşik · üye değilse yalnız %10", ""),
    "hotels":     ("Hotels.com / Expedia", "Expedia", 0.19, "%10 herkese + üye %10 birleşik · üye değilse yalnız %10 (05.11)", ""),
    "trip":       ("Trip.com", "Ctrip", 0.213, "Basic %10 + mobil %10 birleşik · bilgisayarda yalnız %10 · Trip kendi %3–8 ekliyor → çarpan 1,27 (06.11)", ""),
    "etstur":     ("Etstur", "ETSTUR", 0.264, "%20 Özel indirim · Elektra'da her odaya −%8,08 satırı (13.11) · ets_duzelt.py yarım saatte bir denetler", ""),
    "tatilbudur": ("TatilBudur", "TatilBudur", 0.20, "%20 Erken rezervasyon", ""),
    "enuygun":    ("Enuygun", "Enuygun", 0.28, "%28 · Enuygun'un indirimi", ""),
    "jolly":      ("Jollytur", "JollyTur", 0.20, "%20 · Jolly'nin indirimi", ""),
    "obilet":     ("obilet", None, None, "kanal açık · çarpan 1,16 · obilet kendi %13,3 indirimi", ""),
    "zenhotels":  ("ZenHotels", None, None, "bağlı değil · toptancıdan", ""),
    "sembo":      ("sembo", None, None, "bağlı değil · Expedia ortağı", ""),
    # trivago'dan okunan diğer satıcılar (fiyat_topla.py → oku_trivago)
    "expedia":    ("Expedia", None, None, "Expedia grubu · trivago'dan", ""),
    "agoda":      ("Agoda", None, None, "bağlı değil", ""),
}


def tr_bugun():
    """İstanbul'a göre bugün (bulut UTC'de çalışıyor; 00–03 arası tarih kaymasın)."""
    from zoneinfo import ZoneInfo
    return dt.datetime.now(ZoneInfo("Europe/Istanbul")).date()


def hafta_sonu(d):
    """Cuma ve Cumartesi geceleri (11.11.2026'dan beri Cuma da)."""
    return d.weekday() in (4, 5)


def basamak(d, bugun, dolu):
    """Gecenin fiyat basamağı (0–4). Pazar–Perşembe 1.'den, Cuma–Cumartesi 2.'den başlar; 25, 30, 35 oda
    satılınca birer basamak çıkar (Paz–Per en fazla 4., Cuma–Cmt en fazla 5.). `bugun` artık
    kullanılmıyor (aynı gün kuralı 11.11.2026'da kalktı), imza aynı kaldı."""
    return (1 if hafta_sonu(d) else 0) + sum(dolu >= e for e in ESIK_ODA)


def basamak_eski(d, bugun, dolu):
    """04.11–10.11.2026 kuralı, yeni 5'li listenin indisiyle (eski 1./2./3. = yeni 0/2/4). Pazar–Cuma
    (aynı gün de) 1., 30+ oda 2., 40+ oda 3. Cumartesi: aynı gün 3.; ileri tarih 2., 30+ oda 3."""
    cmt = d.weekday() == 5
    if d <= bugun and cmt:
        return 4
    if cmt:
        return 4 if dolu >= 30 else 2
    return 4 if dolu >= 40 else (2 if dolu >= 30 else 0)


def gece_hedef(oda, d, dolu, bugun=None):
    """FIYAT_ODALAR satırı → o gecenin fiyatı (o gece `dolu` oda satılmışken, `bugun` itibarıyla)."""
    if (d, oda[0]) in ELLE_FIYAT:
        return ELLE_FIYAT[(d, oda[0])]
    return oda[3][basamak(d, bugun or tr_bugun(), dolu)] - GECE_INDIRIM.get(d, 0)


def gece_taban(oda, d, bugun=None, eski=False):
    """Gecenin en düşük meşru fiyatı (doluluk 0). Bundan ucuz satan kanal ya da resepsiyon
    gerçekten ucuzdur; doluluk yükselmeden önceki bir gözlem/satış da yanlış alarm vermez.
    eski=True: 11.11.2026 öncesi kural (o tarihten önceki satış/gözlem için)."""
    if (d, oda[0]) in ELLE_FIYAT:
        return ELLE_FIYAT[(d, oda[0])]
    b = (basamak_eski if eski else basamak)(d, bugun or tr_bugun(), 0)
    return oda[3][b] - GECE_INDIRIM.get(d, 0)


def uzun_taban(k, gece):
    """Uzun konaklamada (7+ gece) gecelik taban; uzun konaklama yoksa None."""
    for n, ind in UZUN_INDIRIM:
        if gece >= n and k in UZUN_BAZ:
            return UZUN_BAZ[k] - ind
    return None


def gece_doluluk(env, start, end):
    """date → o gece satılmış oda sayısı (fiyat bandı için). Odası henüz atanmamış ileri tarihli
    rezervasyon da sayılır; iptal / silinmiş / no-show ile NSNSNS ve T-folyo sanal odaları sayılmaz."""
    res = E.fetch_reservations(
        [{"Column": "CHECKIN", "Operator": "<=", "Value": f"{end} 23:59:59"},
         {"Column": "CHECKOUT", "Operator": ">", "Value": f"{start} 00:00:00"}], env=env,
        columns=["RESID", "ROOMNO", "RESSTATE", "CHECKIN", "CHECKOUT"])
    say, one = Counter(), dt.timedelta(days=1)
    for r in res:
        oda = str(r.get("ROOMNO") or "")
        if r.get("RESSTATE") in EXCL_STATES or (oda and not oda.isdigit()):
            continue
        ci, co = pdate(r.get("CHECKIN")), pdate(r.get("CHECKOUT"))
        d = max(ci, start) if ci and co else None
        while d and d < co and d <= end:
            say[d] += 1
            d += one
    return say


def fiyat_gozlemler():
    """site_data/fiyat/{gozlem,otomatik}.json → {(tarih, kanal, oda): en son gözlem}. Gözlem =
    herkese açık bir sayfada görülen fiyat (elle Chrome kontrolü ya da fiyat_topla.py)."""
    import pathlib
    d = pathlib.Path(__file__).resolve().parent / "site_data" / "fiyat"
    # gozlem.json: elle girilen; otomatik.json: fiyat_topla.py (fiyat-veri dalından, bulutta).
    tum = []
    for ad in ("gozlem.json", "otomatik.json"):
        if (d / ad).exists():
            tum += json.loads((d / ad).read_text(encoding="utf-8")).get("gozlemler", [])
    son = {}
    for g in tum:
        k = (g["tarih"], g["kanal"], g.get("oda", "stu"))
        if k not in son or g.get("zaman", "") >= son[k].get("zaman", ""):
            son[k] = g
    return son


def fiyat_tum_gozlemler():
    """Bütün gözlemler (yalnız en sonuncusu değil) — 'sürekli ucuz satan' istatistiği için."""
    import pathlib
    d = pathlib.Path(__file__).resolve().parent / "site_data" / "fiyat"
    tum = []
    for ad in ("gozlem.json", "otomatik.json"):
        if (d / ad).exists():
            tum += json.loads((d / ad).read_text(encoding="utf-8")).get("gozlemler", [])
    return tum


def fiyat_sorunlar():
    import pathlib
    p = pathlib.Path(__file__).resolve().parent / "site_data" / "fiyat" / "sorunlar.json"
    return json.loads(p.read_text(encoding="utf-8")).get("sorunlar", []) if p.exists() else []


def duzeltilecekler(today):
    """Kanal başına son 7 günün okumaları: kaçında hedeften ucuz, en fazla ne kadar. Elle tutulan
    sorunlar (sorunlar.json) + sürekli ucuz satan ama listede olmayan kanallar."""
    sinir = (today - dt.timedelta(days=7)).isoformat()
    ist = {}
    for g in fiyat_tum_gozlemler():
        d = pdate(g.get("tarih"))
        if not d or g.get("zaman", "") < sinir or not g.get("fiyat"):
            continue
        rk = g.get("oda", "stu")
        gordu = pdate(g.get("zaman")) or today      # gözlem günü: o gün aynı gün fiyatı geçerliydi
        hedef = dict((r[0], gece_taban(r, d, gordu, eski=gordu < YENI_LISTE)) for r in FIYAT_ODALAR).get(rk)
        if not hedef:
            continue
        fark = g["fiyat"] - hedef
        ucuz = fark < -FIYAT_TOLERANS or (rk == "eko" and g["kanal"] != "site")
        a = ist.setdefault(g["kanal"], {"n": 0, "ucuz": 0, "min": 0})
        a["n"] += 1
        if ucuz:
            a["ucuz"] += 1
            a["min"] = min(a["min"], fark)
    rows = [dict(s) for s in fiyat_sorunlar()]
    bilinen = {r["kanal"] for r in rows}
    for k, a in ist.items():
        if k not in bilinen and k != "site" and a["n"] >= 3 and a["ucuz"] * 2 >= a["n"]:
            rows.append({"kanal": k, "durum": "açık", "sorun": "Son 7 günde çoğu okumada ucuz",
                         "sebep": "—", "yapilacak": "İncele", "otomatik": True})
    for r in rows:
        r["ist"] = ist.get(r["kanal"])
    return rows


def _tl(n):
    return f"{n:,.0f}".replace(",", ".")


# Sahibinin kuralı (11.11.2026): "Expedia ve Booking mutlaka aynı fiyatı vermeli, çok ufak farklar olabilir."
# İki tarafı da denetler: Elektra'nın gönderdiği (çarpan + oda bazlı kanal çarpanı satırları) ve misafirin
# gördüğü (okumalar, üye fiyatı kıyası). Fark çıkarsa Fiyat Kontrol kırmızı olur.
PARITE_IKILI = ("Booking.com", "Expedia")   # Online Kanallar adı
PARITE_KANAL = {"Booking": 12, "Expedia": 10}
PARITE_ODA_HARIC = ("sui",)   # Booking okuması Suit'te 3 kişilik fiyatı gösteriyor (×1,05); Elektra tarafı yine denetlenir   # HOTEL_CHANNELMANAGER_PRICING CHANNELID
PARITE_TL, PARITE_ORAN = 60, 0.02       # bundan küçük fark "ufak fark" (kur, yuvarlama)
PARITE_TAZE_SAAT = 48


def booking_expedia_parite(factors, obs, today):
    """→ (sorunlar [str], bilgi [str]). Boş sorun listesi = kural tutuyor."""
    sorun, bilgi = [], []
    fb, fe = (factors.get(a) for a in PARITE_IKILI)
    if fb is None or fe is None:
        sorun.append("Elektra'da Booking ya da Expedia çarpanı okunamadı (kanal kapalı olabilir)")
    elif abs(fb - fe) > 0.001:
        sorun.append(f"Elektra çarpanı farklı: Booking {fb:g}, Expedia {fe:g} — ikisi aynı olmalı")
    else:
        bilgi.append(f"Elektra çarpanı ikisinde de {fb:g}")
    try:
        e, _ = E.connect()
        satir = {}
        for ad, kid in PARITE_KANAL.items():
            r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                        {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                         "Where": [{"Column": "CHANNELID", "Operator": "=", "Value": kid}], "Select": [],
                         "Paging": {"ItemsPerPage": 1000, "Current": 1}},   # yoksa yalnız 10 satır
                        action_name="Select")
            satir[ad] = {(str(x["ROOMTYPEID"]), str(x["FROMDATE"])[:10], str(x["TODATE"])[:10],
                          float(x.get("WEEKDAYPERCENT") or 0), float(x.get("WEEKENDPERCENT") or 0),
                          float(x.get("WEEKDAYAMOUNT") or 0), float(x.get("WEEKENDAMOUNT") or 0))
                         for x in ((r or {}).get("ResultSets") or [[]])[0]
                         if str(x["TODATE"])[:10] >= today.isoformat()
                         and any(float(x.get(c) or 0) for c in ("WEEKDAYPERCENT", "WEEKENDPERCENT",
                                                                  "WEEKDAYAMOUNT", "WEEKENDAMOUNT"))}
        if satir["Booking"] != satir["Expedia"]:
            sorun.append("Elektra 'Kanal Fiyat Çarpanları'nda Booking ile Expedia'nın oda/tarih satırları farklı "
                         f"(Booking {len(satir['Booking'])}, Expedia {len(satir['Expedia'])} satır)")
    except Exception as ex:
        bilgi.append(f"oda bazlı çarpan satırları okunamadı ({type(ex).__name__})")
    sinir = (dt.datetime.now() - dt.timedelta(hours=PARITE_TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    n, en = 0, 0
    for (t, k, rk), b in obs.items():
        d = pdate(t)
        h = obs.get((t, "hotels", rk))
        if k != "booking" or rk in PARITE_ODA_HARIC or not d or d < today or not h or not b.get("fiyat") or not h.get("fiyat"):
            continue
        if b.get("zaman", "") < sinir or h.get("zaman", "") < sinir:
            continue
        hf = h["fiyat"] * (1 - UYESIZ_OKUMA["hotels"]) if "trivago" in h.get("kaynak", "") else h["fiyat"]
        fark = hf - b["fiyat"]
        n += 1
        en = max(en, abs(fark), key=abs)
        if abs(fark) > max(PARITE_TL, PARITE_ORAN * b["fiyat"]):
            oda = dict((r[0], r[1]) for r in FIYAT_ODALAR).get(rk, rk)
            sorun.append(f"{d.day} {TR_MONTHS[d.month]} {oda}: Booking {_tl(b['fiyat'])} ₺, Expedia (üye) "
                         f"{_tl(hf)} ₺ — fark {'+' if fark > 0 else ''}{_tl(fark)} ₺")
    if n:
        bilgi.append(f"son {PARITE_TAZE_SAAT} saatte {n} gece × oda kıyaslandı, en büyük fark {_tl(abs(en))} ₺")
    else:
        bilgi.append(f"son {PARITE_TAZE_SAAT} saatte aynı gece için iki kanaldan okuma yok (yalnız Elektra tarafı denetlendi)")
    return sorun, bilgi



# Etstur kuralı (sahibi 13.11.2026: "her güncellemede kontrol et"): Etstur'da misafirin gördüğü = hedef.
# Elektra tarafı: ETSTUR çarpanı × oda satırı × (1 − %20 Etspartners indirimi) her odada ≈ 1 olmalı.
# Okuma tarafı: son ETS_TAZE_SAAT saatin Etstur okumaları ÷ hedef. Bozulursa ets_duzelt.py oda satırını
# yarım saatte bir düzeltir (3 gün sonrası okumalara bakarak); kutu bunu izlemek içindir.
ETS_INDIRIM, ETS_TAZE_SAAT, ETS_ESIK = 0.20, 6, 0.03
ETS_ODA_TIPI = {"stu": 442639, "sup": 455224, "dlx": 442634, "sui": 442636}


def etstur_kontrol(factors, obs, today):
    """→ (sorunlar [str], bilgi [str])."""
    sorun, bilgi = [], []
    adlar = dict((r[0], r[1]) for r in FIYAT_ODALAR)
    f = factors.get("ETSTUR")
    if not f:
        return ["Elektra'da ETSTUR çarpanı okunamadı (kanal kapalı olabilir)"], bilgi
    try:
        e, _ = E.connect()
        r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                    {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                     "Where": [{"Column": "CHANNELID", "Operator": "=", "Value": 147}], "Select": [],
                     "Paging": {"ItemsPerPage": 1000, "Current": 1}}, action_name="Select")
        rows = ((r or {}).get("ResultSets") or [[]])[0]
        t = today.isoformat()
        etkin = []
        for k, rt in ETS_ODA_TIPI.items():
            uzun = [x for x in rows if x["ROOMTYPEID"] == rt and str(x["FROMDATE"])[:10] <= t <= str(x["TODATE"])[:10]
                    and str(x["FROMDATE"])[:10] < str(x["TODATE"])[:10]]
            yuzde = float(uzun[0]["WEEKDAYPERCENT"]) if uzun else 0.0
            m = f * (1 + yuzde / 100) * (1 - ETS_INDIRIM)
            etkin.append(f"{adlar[k]} ×{m:.3f}")
            if abs(m - 1) > 0.01:
                sorun.append(f"Elektra: {adlar[k]} Etstur'a %{(m - 1) * 100:+.1f} farklı gidiyor "
                             f"(çarpan {f:g}, oda satırı %{yuzde:g})")
        tek = [x for x in rows if str(x["FROMDATE"])[:10] == str(x["TODATE"])[:10] >= t
               and abs(float(x["WEEKDAYPERCENT"]) - next((float(y["WEEKDAYPERCENT"]) for y in rows
                       if y["ROOMTYPEID"] == x["ROOMTYPEID"] and str(y["FROMDATE"])[:10] < str(y["TODATE"])[:10]
                       and str(y["FROMDATE"])[:10] <= str(x["FROMDATE"])[:10] <= str(y["TODATE"])[:10]), 0.0)) > 0.01]
        if tek:
            sorun.append(f"Elektra: {len(tek)} tek gecelik Etstur satırı oda satırından farklı (elle bakılmalı)")
        bilgi.append("Elektra'dan giden (%20 sonrası ÷ liste): " + ", ".join(etkin))
    except Exception as ex:
        bilgi.append(f"Etstur oda satırları okunamadı ({type(ex).__name__})")
    sinir = (dt.datetime.now() - dt.timedelta(hours=ETS_TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    say, sapma = 0, {}
    for (tt, k, rk), o in obs.items():
        d = pdate(tt)
        if k != "etstur" or not d or d < today or not o.get("fiyat") or o.get("zaman", "") < sinir:
            continue
        oda = next((r for r in FIYAT_ODALAR if r[0] == rk), None)
        if not oda or (rk == "eko"):
            continue
        say += 1
        # hedef: doluluk basamağı dahil (panel kartıyla aynı)
        dol_hedef = gece_hedef(oda, d, ETS_DOLULUK.get(d, 0), today)
        oran = o["fiyat"] / dol_hedef
        if abs(oran - 1) > ETS_ESIK:
            sapma.setdefault(rk, []).append((d, o["fiyat"], dol_hedef))
    for rk, l in sapma.items():
        l.sort()
        orn = "; ".join(f"{d.day} {TR_MONTHS[d.month]}: {_tl(p)} ₺ (hedef {_tl(h)})" for d, p, h in l[:3])
        sorun.append(f"Etstur'da görülen {adlar.get(rk, rk)}: {len(l)} gece hedeften farklı — {orn}")
    bilgi.append(f"son {ETS_TAZE_SAAT} saatte {say} Etstur okuması kıyaslandı" if say
                 else f"son {ETS_TAZE_SAAT} saatte Etstur okuması yok")
    return sorun, bilgi


ETS_DOLULUK = {}   # build_fiyat doldurur (gece → dolu oda)



# Trip.com ve obilet (sahibi 14.11.2026: "Trip Booking Expedia ile aynı fiyat olacak", "sürekli indirim yapıyor
# yapamasın"): son okumalar ÷ hedef. Bozulursa gece_duzelt.py yarım saatte bir Elektra'da o kanalın gece/oda
# çarpanını düzeltir (yakın 4 gece tek tek, sonrası tek satır). Kutu bunu izlemek içindir.
OKUMA_KURAL = (("trip", "Trip.com = Booking kuralı"), ("obilet", "obilet kuralı"))


def okuma_kontrol(anahtar, obs, today, saat=6, esik=0.03):
    """→ (sorunlar, bilgi): son `saat` saatin okumaları hedeften ±esik'ten fazla sapan geceler."""
    sorun, bilgi = [], []
    adlar = dict((r[0], r[1]) for r in FIYAT_ODALAR)
    sinir = (dt.datetime.now() - dt.timedelta(hours=saat)).strftime("%Y-%m-%d %H:%M")
    say, sapma = 0, {}
    for (tt, k, rk), o in obs.items():
        d = pdate(tt)
        oda = next((r for r in FIYAT_ODALAR if r[0] == rk), None)
        if k != anahtar or not d or d < today or not o.get("fiyat") or o.get("zaman", "") < sinir or not oda or rk == "eko":
            continue
        say += 1
        h = gece_hedef(oda, d, ETS_DOLULUK.get(d, 0), today)
        if abs(o["fiyat"] / h - 1) > esik:
            sapma.setdefault(rk, []).append((d, o["fiyat"], h))
    for rk, l in sapma.items():
        l.sort()
        orn = "; ".join(f"{d.day} {TR_MONTHS[d.month]}: {_tl(p)} ₺ (hedef {_tl(h)})" for d, p, h in l[:3])
        sorun.append(f"{adlar.get(rk, rk)}: {len(l)} gece hedeften farklı — {orn}")
    bilgi.append(f"son {saat} saatte {say} okuma kıyaslandı" if say else f"son {saat} saatte okuma yok")
    return sorun, bilgi


def kural_kutusu(baslik, sorun, bilgi, ek):
    return ("<div class='fk-fix' style='box-shadow:inset 4px 0 " + ("var(--statbad)" if sorun else "var(--statok)")
            + f"'><b>{esc(baslik)}</b> <span class='fk-diff " + ("fk-low'>FARK VAR" if sorun else "fk-ok'>hedefte")
            + "</span><div class='fk-small' style='margin-top:4px'>"
            + "".join(f"<div style='color:var(--statbad);font-weight:700'>• {esc(x)}</div>" for x in sorun)
            + " · ".join(esc(x) for x in bilgi) + " · " + esc(ek) + "</div></div>")



def build_fiyat(env):
    """Fiyat Kontrol — her kanalda misafirin gördüğü fiyat hedefle aynı mı? Görülen fiyat
    gözlem dosyasından, beklenen fiyat Elektra'daki canlı kanal çarpanından gelir; Elektra'da
    biri çarpanı değiştirirse beklenen fiyat hemen sapar. Yanda resepsiyon için kapı fiyatları."""
    today = tr_bugun()
    factors, elektra_ok = {}, True
    try:
        for c in E.fetch_channel_factors(env):
            if c["active"]:
                factors[c["name"]] = float(c["factor"] or 1)
    except Exception:
        elektra_ok = False
    obs = fiyat_gozlemler()

    days = {today, today + dt.timedelta(days=1)}
    for wd in (2, 5):  # önümüzdeki Çarşamba ve Cumartesi
        days.add(today + dt.timedelta(days=(wd - today.weekday()) % 7 or 7))
    for (t, _, _) in obs:
        d = pdate(t)
        if d and today <= d <= today + dt.timedelta(days=180):
            days.add(d)
    days = sorted(days)[:10]
    ileri = [today + dt.timedelta(days=i) for i in range(14)]
    try:
        dol = gece_doluluk(env, today, max(days[-1], ileri[-1]))
    except Exception:
        dol, elektra_ok = Counter(), False

    def bant(d):
        n = dol.get(d, 0)
        return f"o gece {n} oda dolu · {BASAMAK_ADI[basamak(d, today, n)]}"

    def grup(d):
        return "Cuma–Cumartesi" if hafta_sonu(d) else "Pazar–Perşembe"

    rooms = [{"k": r[0], "ad": r[1]} for r in FIYAT_ODALAR]
    kanallar, beklenen, gozlem = [], {}, {}
    for key, (ad, ename, ind, etiket, acik_not) in FIYAT_KANALLAR.items():
        f = None
        if ename == "":
            f = 1.0
        elif ename:
            f = factors.get(ename)
        kanallar.append({"k": key, "ad": ad, "etiket": etiket, "acikNot": acik_not,
                         "bagli": ename is not None, "kapali": bool(f and f >= 3),
                         "bilinmiyor": ename is not None and f is None})
    for d in days:
        iso = d.isoformat()
        beklenen[iso] = {}
        for key, (ad, ename, ind, etiket, acik_not) in FIYAT_KANALLAR.items():
            f = 1.0 if ename == "" else (factors.get(ename) if ename else None)
            if f is None or f >= 3:
                continue
            beklenen[iso][key] = {}
            for oda in FIYAT_ODALAR:
                rk = oda[0]
                if rk == "eko" and key != "site":
                    continue  # Ekonomik oda kanallarda satılmaz
                acik = gece_hedef(oda, d, dol.get(d, 0), today) * f
                beklenen[iso][key][rk] = [round(acik * (1 - ind)), round(acik) if ind else None]
    for (t, k, rk), o in obs.items():
        g = {"p": o["fiyat"], "acik": o.get("acik"), "et": o.get("etiket", ""),
             "src": o.get("kaynak", ""), "t": o.get("zaman", "")}
        if k in UYESIZ_OKUMA and "trivago" in g["src"]:
            # trivago Hotels.com'un ÜYE OLMAYAN fiyatını gösterir (%10); Booking okuması ise Genius'lu
            # (%10+%10). Kıyas üye fiyatıyla yapılsın, yoksa Expedia hep "+350 pahalı" görünür (11.11.2026).
            g["uyesiz"], g["p"] = o["fiyat"], round(o["fiyat"] * (1 - UYESIZ_OKUMA[k]))
        gozlem.setdefault(t, {}).setdefault(k, {})[rk] = g

    gun_list = []
    for d in days:
        lab = ("Bugün · " if d == today else "Yarın · " if d == today + dt.timedelta(days=1) else "") \
            + f"{d.day} {TR_MONTHS[d.month]} {GUN_KISA[d.weekday()]}"
        gun_list.append({"iso": d.isoformat(), "lab": lab, "grup": grup(d), "bant": bant(d),
                         "hedef": {r[0]: gece_hedef(r, d, dol.get(d, 0), today) for r in FIYAT_ODALAR}})
    data = {"tol": FIYAT_TOLERANS, "rooms": rooms, "days": gun_list, "kanallar": kanallar,
            "beklenen": beklenen, "gozlem": gozlem, "elektra": elektra_ok}

    # Özet: önümüzdeki günlerde hedeften UCUZ görülen kanal (en son gözleme göre) +
    # Elektra ayarı yüzünden beklenen fiyatı sapan kanal.
    ucuz = set()
    from zoneinfo import ZoneInfo
    taze = (dt.datetime.now(ZoneInfo("Europe/Istanbul")) - dt.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")   # 6 saatten eski okuma sayılmaz (kartlarla aynı)
    for (t, k, rk), o in obs.items():
        d = pdate(t)
        if d and d >= today and o.get("fiyat") and o.get("zaman", "") >= taze and rk != "eko":
            hedef = dict((r[0], gece_taban(r, d, today)) for r in FIYAT_ODALAR)[rk]
            if o["fiyat"] < hedef - FIYAT_TOLERANS:
                ucuz.add(FIYAT_KANALLAR.get(k, (k,))[0])
    for key, per in beklenen.get(today.isoformat(), {}).items():
        v = per.get("stu")
        hedef = gece_hedef(FIYAT_ODALAR[1], today, dol.get(today, 0), today)
        if v and abs(v[0] - hedef) > FIYAT_TOLERANS:
            ucuz.add(FIYAT_KANALLAR[key][0] + " (Elektra ayarı)")

    # Kural kutuları (Booking = Expedia, Etstur, Trip, obilet) 16.11.2026'da panelden kaldırıldı — sahibi:
    # "buraya yazmanın amacı yok, senin görevin fark olmamasını sağlamak". Eşitleme kanal_duzelt.py'de.

    # Kapı fiyatları (resepsiyon): bugünün TABAN fiyatı büyük — indirim yok (27.10.2026); yanında basamak
    # tablosu, hangi gecenin hangi basamakta olduğu ve önümüzdeki 14 gece.
    b_bugun = basamak(today, today, dol.get(today, 0))
    kapi = "".join(
        f"<div class='fk-drow'><div class='fk-room'>{esc(r[1])}<small>{esc(r[2])}</small></div>"
        f"<div class='fk-dp'><span class='fk-big'>{_tl(gece_hedef(r, today, dol.get(today, 0), today))}<i>₺</i></span></div></div>"
        for r in FIYAT_ODALAR)
    bas = "".join(f"<th class='r'>{i + 1}.</th>" for i in range(len(BASAMAK_ADI)))   # dar sütun: 5 basamak sığsın
    satir = "".join(
        f"<tr><td>{esc(r[1])}</td>" + "".join(
            f"<td class='r{' fk-now' if i == b_bugun else ''}'>{_tl(r[3][i])}</td>" for i in range(len(BASAMAK_ADI))) + "</tr>"
        for r in FIYAT_ODALAR)
    hafta = ("<div class='fk-small' style='font-weight:700;color:var(--fg);margin:8px 0 4px'>Fiyat basamakları</div>"
             f"<table class='fk-week'><thead><tr><th>Oda · basamak</th>{bas}</tr></thead><tbody>{satir}</tbody></table>"
             "<div class='fk-small' style='font-weight:700;color:var(--fg);margin:10px 0 4px'>Hangi gece hangi basamak</div>"
             "<table class='fk-week'><thead><tr><th>Gece</th><th class='r'>0–25 oda</th><th class='r'>26–30</th>"
             "<th class='r'>31–35</th><th class='r'>36+</th></tr></thead><tbody>"
             "<tr><td>Pazar–Perşembe</td><td class='r'>1.</td><td class='r'>2.</td><td class='r'>3.</td><td class='r'>4.</td></tr>"
             "<tr><td>Cuma–Cumartesi</td><td class='r'>2.</td><td class='r'>3.</td><td class='r'>4.</td><td class='r'>5.</td></tr>"
             "</tbody></table>")
    gece = "".join(
        f"<tr{' class=fk-nrm' if basamak(d, today, dol.get(d, 0)) > basamak(d, today, 0) else ''}>"
        f"<td>{d.day} {TR_MONTHS[d.month]} {GUN_KISA[d.weekday()]}</td><td class='r'>{dol.get(d, 0)}</td>"
        f"<td class='r'>{_tl(gece_hedef(FIYAT_ODALAR[1], d, dol.get(d, 0), today))}</td></tr>"
        for d in ileri)
    hafta += ("<div class='fk-small' style='font-weight:700;color:var(--fg);margin:10px 0 4px'>Önümüzdeki geceler "
              "<span style='font-weight:400'>· kalın: doluluk yüzünden yükselmiş</span></div>"
              "<table class='fk-week'><thead><tr><th>Gece</th><th class='r'>Dolu oda</th>"
              "<th class='r'>Stüdyo</th></tr></thead><tbody>" + gece + "</tbody></table>")

    duz = duzeltilecekler(today)
    if duz:
        satir = []
        for r in duz:
            ad = FIYAT_KANALLAR.get(r["kanal"], (r["kanal"].capitalize(),))[0]
            a = r.get("ist")
            if a and a["n"]:
                kanit = (f"ucuz: {a['ucuz']}/{a['n']} okuma"
                         + (f" · en fazla {_tl(a['min'])} TL" if a["ucuz"] else ""))
                ton = "fk-low" if a["ucuz"] else "fk-ok"
            else:
                kanit, ton = "son 7 günde okuma yok", "fk-none"
            rozet = " <span class='fk-diff fk-ok'>çözüldü</span>" if r.get("durum") == "çözüldü" else ""
            satir.append(
                f"<tr><td><b>{esc(ad)}</b>{rozet}"
                f"<div class='fk-small'>{esc(r.get('sorun',''))}</div></td>"
                f"<td><span class='fk-diff {ton}'>{esc(kanit)}</span></td>"
                f"<td class='fk-small'>{esc(r.get('sebep',''))}</td>"
                f"<td class='fk-small'><b style='color:var(--fg)'>{esc(r.get('yapilacak',''))}</b></td></tr>")
        acik_n = sum(1 for r in duz if r.get("durum") != "çözüldü")
        duz_html = ("<details class='fk-fix'><summary class='fk-fix-h'><b>Düzeltilecekler</b>"
                    f"<span class='fk-diff {'fk-low' if acik_n else 'fk-ok'}'>{acik_n} açık</span>"
                    "<span class='fk-small'>sürekli ucuz satan kanallar · açmak için tıklayın</span></summary>"
                    "<div style='overflow-x:auto;margin-top:8px'><table class='fk-fixt'><thead><tr><th>Kanal</th><th>Son 7 gün</th>"
                    "<th>Muhtemel sebep</th><th>Yapılacak</th></tr></thead><tbody>"
                    + "".join(satir) + "</tbody></table></div></details>")
    else:
        duz_html = ""

    body = (FIYAT_HTML.replace("__DUZ__", duz_html)
            .replace("__KAPI__", kapi).replace("__HAFTA__", hafta)
            .replace("__BANT__", esc(bant(today)[0].upper() + bant(today)[1:]))
            .replace("__BUGUN__", esc(f"{today.day} {TR_MONTHS[today.month]} {GUN_ADI[today.weekday()]}"))
            .replace("__TOL__", str(FIYAT_TOLERANS))
            .replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")))
    n = len(ucuz)
    return {"label": "Fiyat Kontrol", "count": n,
            "count_label": "kanal hedeften ucuz" if n else "kanal hedefte",
            "tone": "bad" if n else "ok",
            "sub": ("ucuz: " + ", ".join(sorted(ucuz))) if n else "her kanalda aynı fiyat · bugünün taban fiyatları",
            "updated": now_str(),
            "html": PAGE("Fiyat / Parite", "Fiyat Kontrol",
                         "her kanalda misafirin gördüğü fiyat · bugün kapıdan taban fiyatlar", body)}


FIYAT_HTML = """
<style>
:root{--fk-warn:#b45309;--fk-warnbg:#fffbeb;--fk-okbg:#ecfdf3;--fk-lowbg:#fef2f2;--fk-chip:#e0f2f6;--fk-chipfg:#0e7490;--fk-soft:#f1f5f9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--fk-warn:#fbbf24;--fk-warnbg:#2a2010;--fk-okbg:#0f2417;--fk-lowbg:#2a1215;--fk-chip:#12303a;--fk-chipfg:#67d5e6;--fk-soft:#182338}}
:root[data-theme=dark]{--fk-warn:#fbbf24;--fk-warnbg:#2a2010;--fk-okbg:#0f2417;--fk-lowbg:#2a1215;--fk-chip:#12303a;--fk-chipfg:#67d5e6;--fk-soft:#182338}
.fk-split{display:grid;grid-template-columns:minmax(0,1fr) minmax(300px,390px);gap:18px;align-items:start}
@media (max-width:900px){.fk-split{grid-template-columns:minmax(0,1fr)}.fk-door{order:-1}}
.fk-chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px}
.fk-chip{font:inherit;font-size:12.5px;cursor:pointer;border:1px solid var(--border);background:var(--card);color:var(--fg);border-radius:999px;padding:5px 12px}
.fk-chip.on{background:var(--fk-chip);color:var(--fk-chipfg);border-color:transparent;font-weight:700}
.fk-chip:focus-visible{outline:2px solid var(--eyebrow);outline-offset:2px}
.fk-hero{display:flex;flex-wrap:wrap;gap:18px;align-items:center;background:var(--card);border:1px solid var(--border);border-radius:13px;padding:14px 18px;margin-bottom:12px}
.fk-hero .big{font-size:30px;font-weight:800;font-variant-numeric:tabular-nums}
.fk-hero .l{color:var(--sub);font-size:12px}
.fk-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(215px,100%),1fr));gap:12px}
.fk-card{background:var(--card);border:1px solid var(--border);border-radius:13px;padding:13px 14px;display:grid;gap:3px;min-width:0}
.fk-card.bek{border-style:dashed}
.fk-card .top{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.fk-card .name{font-weight:700}
.fk-card .price{font-size:24px;font-weight:800;font-variant-numeric:tabular-nums}
.fk-card.bek .price{color:var(--sub)}
.fk-card .meta{color:var(--sub);font-size:11.5px}
.fk-diff{font-size:12px;font-weight:700;border-radius:6px;padding:1px 7px;white-space:nowrap}
.fk-ok{background:var(--fk-okbg);color:var(--statok)}.fk-low{background:var(--fk-lowbg);color:var(--statbad)}
.fk-high{background:var(--fk-warnbg);color:var(--fk-warn)}.fk-none{background:var(--fk-soft);color:var(--sub)}
.fk-door{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:18px;display:grid;gap:12px;min-width:0}
.fk-door h2{margin:0;font-size:24px;line-height:1.2}
.fk-door .when{color:var(--eyebrow);font-weight:700;font-size:13px}
.fk-rule{background:var(--fk-chip);color:var(--fg);border-radius:10px;padding:9px 12px;font-size:13px}
.fk-rule b{color:var(--fk-chipfg)}
.fk-drow{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--td-line)}
.fk-room{font-weight:700;font-size:18px}
.fk-room small{display:block;color:var(--sub);font-weight:400;font-size:11.5px}
.fk-dp{text-align:right;font-variant-numeric:tabular-nums}
.fk-big{display:block;font-size:36px;font-weight:800;letter-spacing:-.5px;line-height:1.05}
.fk-big i{font-style:normal;font-size:18px;color:var(--sub);margin-left:3px}
.fk-door .fk-nodisc{background:var(--fk-lowbg);color:var(--statbad);border-radius:10px;padding:9px 12px;font-size:14px;font-weight:700}
.fk-min{display:block;font-size:12px;font-weight:700;color:var(--fk-warn)}
.fk-week{font-size:12.5px;margin:0;width:100%;table-layout:fixed}
.fk-week td,.fk-week th{padding:6px 4px;overflow-wrap:anywhere}
.fk-week td:first-child,.fk-week th:first-child{width:30%;padding-left:8px}
.fk-split>*{min-width:0}
.fk-week td.fk-now{font-weight:800;background:var(--fk-chip);color:var(--fk-chipfg)}
.fk-week tr.fk-nrm td{font-weight:800}
.fk-small{color:var(--sub);font-size:11.5px;line-height:1.5}
.fk-fix{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:10px 16px;margin-bottom:16px;box-shadow:inset 4px 0 var(--statbad)}
.fk-fix-h{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline;cursor:pointer;list-style:none}
.fk-fix-h::-webkit-details-marker{display:none}
.fk-fix-h::before{content:"▸";color:var(--sub)}
.fk-fix[open] .fk-fix-h::before{content:"▾"}
.fk-fixt{margin:0;font-size:12.5px}
.fk-fixt td{vertical-align:top}
.fk-fixt td:nth-child(2){white-space:nowrap}
</style>
__DUZ__
<div class="fk-split">
  <div style="min-width:0">
    <div class="fk-chips" id="fkDays" role="group" aria-label="Tarih"></div>
    <div class="fk-chips" id="fkRooms" role="group" aria-label="Oda"></div>
    <div class="fk-hero" id="fkHero"></div>
    <div class="fk-cards" id="fkCards"></div>
    <div class="note">Görülen fiyat: herkese açık sitelerde (trivago, kanal siteleri, Booking için yurt dışı bağlantı) okunan fiyat; kartın altında ne zaman ve nerede görüldüğü yazar.
      Kesik çizgili kart: o tarih için henüz kontrol yok; gösterilen rakam Elektra'daki kanal ayarına göre <b>beklenen</b> fiyattır. Elektra'da bir kanalın ayarı değişirse beklenen fiyat burada hemen sapar.
      ±__TOL__ TL içi hedefte sayılır; kanallar Euro'yu kendi kuruyla çevirir.</div>
  </div>
  <aside class="fk-door">
    <div><div class="when">__BUGUN__ · bu gece</div><h2>Bugün kapıdan taban fiyatlar</h2></div>
    <div class="fk-nodisc">İndirim yapılmaz. Telefonda ve kapıda bu fiyatlar söylenir.</div>
    <div>__KAPI__</div>
    <div class="fk-small">__BANT__. Fiyatlar 1–2 kişi, kahvaltı dahil, iade edilebilir. Ekonomik oda yalnızca telefon, kapı ve web sitesinden satılır. Suit'te 3. kişi +%5, 4. kişi +%10. İleri tarihli rezervasyonun fiyatı için aşağıdaki tablolara bakın.</div>
    <div>__HAFTA__</div>
  </aside>
</div>
<script>
(function(){
  var D=__DATA__;
  var fmt=function(n){return Math.round(n).toLocaleString('tr-TR')};
  var esc=function(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})};
  var selDay=0,selRoom='stu';
  function kisa(t){var m=/^(\d{4})-(\d\d)-(\d\d)(?: (\d\d:\d\d))?/.exec(t||'');return m?(m[3]+'.'+m[2]+(m[4]?' '+m[4]:'')):(t||'');}
  try{var r=localStorage.getItem('fk-oda');if(r)selRoom=r;}catch(e){}
  // Varsayılan gün: bugün (liste bugünden başlar).
  selDay=0;
  var kmap={};D.kanallar.forEach(function(k){kmap[k.k]=k;});
  function st(diff){return diff<-D.tol?'low':(diff>D.tol?'high':'ok');}
  function chips(id,items,on,cb){var el=document.getElementById(id);el.innerHTML='';items.forEach(function(it,i){var b=document.createElement('button');b.type='button';b.className='fk-chip'+(it.v===on?' on':'');b.textContent=it.t;b.addEventListener('click',function(){cb(it.v)});el.appendChild(b);});}
  function render(){
    chips('fkDays',D.days.map(function(d,i){return{t:d.lab,v:i}}),selDay,function(v){selDay=v;render();});
    chips('fkRooms',D.rooms.map(function(r){return{t:r.ad,v:r.k}}),selRoom,function(v){selRoom=v;try{localStorage.setItem('fk-oda',v)}catch(e){}render();});
    var day=D.days[selDay],T=day.hedef[selRoom],iso=day.iso;
    var obs=D.gozlem[iso]||{},bek=D.beklenen[iso]||{};
    var keys=[];D.kanallar.forEach(function(k){keys.push(k.k)});Object.keys(obs).forEach(function(k){if(keys.indexOf(k)<0)keys.push(k)});
    var cards=[],cnt={ok:0,low:0,high:0,bek:0};
    keys.forEach(function(k){
      var meta=kmap[k]||{ad:k.charAt(0).toUpperCase()+k.slice(1),etiket:'bağlı değil · trivago’dan',bagli:false},o=(obs[k]||{})[selRoom],b=(bek[k]||{})[selRoom];
      if(meta.kapali&&!o){cards.push({rank:5,html:'<div class="fk-card bek"><div class="top"><span class="name">'+esc(meta.ad)+'</span><span class="fk-diff fk-none">kapalı</span></div><div class="meta">Satış durduruldu (Elektra’da kapatıldı)</div></div>'});return;}
      if(!o&&!b)return;
      var p=o?o.p:b[0],diff=p-T,s=st(diff),gor=!!o;
      // 6 saatten eski okuma "ucuz/pahalı" sayılmaz: fiyat o arada değişmiş olabilir (21.11.2026 — Trip 20.11,
      // Tatilsepeti 15.11 okumaları günler sonra kırmızı "ucuz" görünüyordu; Trip'te gerçek fiyat 4.250'ydi).
      var eski=gor&&o.t&&(Date.now()-new Date(o.t.replace(' ','T')).getTime())>6*3600e3;
      if(selRoom==='eko'&&k!=='site'&&o)s='low';
      if(gor&&!eski)cnt[s]++;else cnt.bek++;
      var acik=o&&o.acik?o.acik:(b&&b[1]?b[1]:null);
      var lines='<div class="meta">'+esc(o&&o.et?o.et:meta.etiket)+'</div>';
      if(o&&o.uyesiz)lines+='<div class="meta">üye fiyatı (yukarıda) · üye olmayan misafir: '+fmt(o.uyesiz)+' ₺ (trivago bunu gösterir)</div>';
      if(acik&&meta.acikNot)lines+='<div class="meta">'+esc(meta.acikNot)+': '+fmt(acik)+' ₺</div>';
      if(selRoom==='eko'&&k!=='site'&&o)lines+='<div class="meta" style="color:var(--statbad);font-weight:700">Ekonomik oda burada satılmamalı</div>';
      lines+='<div class="meta">'+(gor?('görüldü: '+esc(o.src)+' · '+esc(kisa(o.t))):'<b>hesaplanan</b> · gerçek fiyat henüz okunmadı')+'</div>';
      var rank=eski?4:gor?({low:0,high:1,ok:2}[s]):3;
      var chip=eski?'<span class="fk-diff fk-none">güncel değil</span>':gor?'<span class="fk-diff fk-'+s+'">'+(diff>0?'+':'')+fmt(diff)+'</span>':'<span class="fk-diff fk-none">hesap</span>';
      // sahibi (21.11): "panelde bir fiyat güncel değilse bu fiyatın aktif olmadığını belirtelim"
      if(eski)lines='<div class="meta" style="font-weight:700">Bu fiyat güncel değil — son okuma '+esc(kisa(o.t))+'. Şu an bu fiyattan satılmıyor olabilir; yeni okuma bekleniyor.</div>'+lines;
      cards.push({rank:rank,diff:diff,html:'<div class="fk-card'+(gor&&!eski?'':' bek')+'"><div class="top"><span class="name">'+esc(meta.ad)+'</span>'+chip+'</div><div class="price"'+(eski?' style="text-decoration:line-through;opacity:.45"':'')+'>'+(gor?'':'≈ ')+fmt(p)+' ₺</div>'+lines+'</div>'});
    });
    cards.sort(function(a,b){return a.rank-b.rank||(a.diff||0)-(b.diff||0)});
    document.getElementById('fkCards').innerHTML=cards.map(function(c){return c.html}).join('')||'<div class="empty">Bu oda ve tarih için veri yok.</div>';
    var room=D.rooms.filter(function(r){return r.k===selRoom})[0].ad;
    document.getElementById('fkHero').innerHTML='<div><div class="l">Hedef · '+esc(room)+' · '+esc(day.grup)+'</div><div class="big">'+fmt(T)+' ₺</div><div class="l">'+esc(day.bant)+'</div></div>'+
      '<div class="l" style="font-size:13px">Görülen fiyatlar: <b style="color:var(--statok)">'+cnt.ok+'</b> hedefte · <b style="color:var(--statbad)">'+cnt.low+'</b> ucuz · <b style="color:var(--fk-warn)">'+cnt.high+'</b> pahalı'+(cnt.bek?' · '+cnt.bek+' kanal kontrol bekliyor':'')+
      (D.elektra?'':'<br><b style="color:var(--statbad)">Elektra’ya ulaşılamadı; beklenen fiyatlar hesaplanmadı.</b>')+'</div>';
  }
  render();
})();
</script>
"""


# --------------------------------------------------------------------------- Günlük Rapor (defter)
GUNLUK_CSS = """<style>
.topbar{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:6px}
.daynav{display:inline-flex;align-items:center;gap:4px;background:var(--card);border:1px solid var(--border);
  border-radius:12px;padding:5px 6px}
.daynav button{border:0;background:none;color:var(--eyebrow);font-size:18px;font-weight:800;
  width:32px;height:32px;border-radius:8px;cursor:pointer}
.daynav button:hover{background:var(--th-bg)}
.daynav button:disabled{opacity:.35;cursor:default}
.daynav .cur{font-weight:800;font-size:14px;min-width:180px;text-align:center;padding:0 6px}
.daynav .cur small{display:block;color:var(--sub);font-weight:600;font-size:11px}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:14px 0 0}
.tab{border:1px solid var(--border);background:var(--card);color:var(--fg);font:inherit;font-weight:600;font-size:13px;
  padding:8px 14px;border-radius:999px;cursor:pointer;white-space:nowrap}
.tab:hover{border-color:var(--eyebrow)}
.tab.active{background:var(--fg);color:var(--card);border-color:var(--fg);font-weight:700}
/* Sabah notu (sahibi 20.11.2026, mockup 2) */
.sb{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:16px 20px;display:grid;gap:12px}
.sb-hd{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:10px;border-bottom:1px solid var(--border);padding-bottom:10px}
.sb-eb{font-size:11.5px;font-weight:800;letter-spacing:.7px;text-transform:uppercase;color:var(--eyebrow)}
.sb h2{margin:2px 0 0;font-family:Georgia,'Source Serif 4',serif;font-size:24px;font-weight:600}
.sb .topbar{margin:0;gap:8px}
.sb #scopeSel{font:inherit;font-size:13px;padding:8px 10px;border:1px solid var(--border);border-radius:9px;background:var(--card);color:inherit}
.sb-grid{display:flex;flex-direction:column-reverse;gap:12px}
.sb-rows{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px}
@media (max-width:900px){.sb-rows{grid-template-columns:minmax(0,1fr)}}
.sb-row{display:grid;grid-template-columns:10px 132px minmax(0,1fr);gap:8px;align-items:baseline;text-align:left;border:0;
  border-bottom:1px solid var(--border);background:none;font:inherit;font-size:13.5px;color:var(--fg);padding:7px 2px;cursor:pointer}
.sb-row:hover{background:var(--th-bg)}
.sb-row i{width:8px;height:8px;border-radius:50%;background:#16a34a;transform:translateY(-1px)}
.sb-row.warn i{background:#ea580c}.sb-row.bad i{background:#dc2626}
.sb-row b{font-weight:700;color:var(--sub);font-size:12.5px}
.sb-row.bad span{color:#991b1b;font-weight:600}.sb-row.warn span{color:#9a3412}
#sbText p{margin:0 0 8px;font-size:15.5px;line-height:1.6}
#sbText .lines{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:2px 14px;margin-top:4px}
.sb-li{display:flex;gap:8px;align-items:baseline;text-align:left;border:0;background:none;font:inherit;font-size:13.5px;
  color:var(--fg);padding:4px 0;cursor:pointer;line-height:1.45}
.sb-li:hover{color:var(--eyebrow)}
.sb-li i{flex:none;width:8px;height:8px;border-radius:50%;background:#16a34a;transform:translateY(-1px)}
.sb-li.warn i{background:#ea580c}.sb-li.bad i{background:#dc2626}
.sb-boxes{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}
@media (max-width:900px){.sb-boxes{grid-template-columns:repeat(2,minmax(0,1fr))}}
.sb-box{border:1px solid var(--border);border-radius:12px;padding:10px 12px;display:grid;gap:1px;text-align:left;
  background:var(--card);font:inherit;color:inherit;cursor:pointer}
.sb-box span{font-size:12px;color:var(--sub)}.sb-box b{font-size:20px}
.sb-box.warn{background:#fff7ed;border-color:#fed7aa}.sb-box.warn b,.sb-box.warn span{color:#9a3412}
.sb-box.bad{background:#fef2f2;border-color:#fecaca}.sb-box.bad b,.sb-box.bad span{color:#991b1b}
.sb-box.ok{background:#f0fdf4;border-color:#bbf7d0}.sb-box.ok b,.sb-box.ok span{color:#166534}
.sb .g{color:#15803d}.sb .o{color:#b45309}.sb .r{color:#b91c1c}
.tab .cnt{display:inline-block;background:var(--statbad);color:#fff;border-radius:999px;
  font-size:10.5px;padding:0 6px;margin-left:5px;font-weight:800;vertical-align:1px}
.tab .cnt.ok{background:#15803d}
.panel{display:none;padding-top:14px}.panel.active{display:block}
.mono{font-family:ui-monospace,Menlo,monospace}
.chg{font-family:ui-monospace,Menlo,monospace;font-weight:700}.chg .arw{color:var(--eyebrow);padding:0 4px}
.reason-none{color:var(--statbad);font-weight:600}
td textarea{width:100%;min-height:38px;font:inherit;font-size:12.5px;padding:7px 9px;
  border:1px solid var(--input-line);border-radius:8px;background:var(--input-bg);color:var(--fg);resize:vertical}
td textarea:focus{border-color:var(--eyebrow);outline:none}
td input[type=checkbox]{width:auto;transform:scale(1.35);cursor:pointer;accent-color:var(--eyebrow)}
td select{font:inherit;font-size:12.5px;padding:6px 8px;border:1px solid var(--input-line);border-radius:8px;background:var(--input-bg);color:var(--fg);cursor:pointer}
td select:focus{border-color:var(--eyebrow);outline:none}
.addbar{display:flex;gap:8px;align-items:center;margin:2px 0 10px;flex-wrap:wrap}
.addbar input{flex:1;min-width:120px}
.saverow{display:flex;align-items:center;gap:12px;margin:8px 0 6px}
.btn{font:inherit;font-weight:700;padding:9px 18px;border-radius:10px;border:1px solid var(--eyebrow);
  background:var(--eyebrow);color:#fff;cursor:pointer}
.btn.ghost{background:transparent;color:var(--eyebrow)}
.saved{color:var(--statok);font-weight:700;font-size:13px;opacity:0;transition:opacity .2s}
.saved.show{opacity:1}
.autosave{color:var(--sub);font-size:12px}
.filtbar{display:flex;align-items:center;gap:8px;margin:0 0 8px}
.filtbar input{max-width:220px}
.ph{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:24px;
  text-align:center;color:var(--sub);font-size:13px}
.rowdel{border:0;background:none;color:var(--statbad);cursor:pointer;font-size:15px;padding:2px 6px}
</style>"""
GUNLUK_JS = r"""<script>
(function(){
  var D = window.__GUNLUK__ || {days:{},openbal:[],cari:[],today:''};
  var alldays = Object.keys(D.days).sort();
  // Sabah açılınca DÜN (sahibi 19.11.2026: "rapor açılınca dün ne olmuş görmek istiyorum")
  var cur = (D.dun && D.days[D.dun]) ? D.dun : ((D.today && D.days[D.today]) ? D.today : (alldays[alldays.length-1] || D.today));
  var curTab = 'bal';      // ilk sekme açık gelir (sekme sırası sahibin, 28.10.2026)
  try{ var _gs=sessionStorage.getItem('gitSekme'); if(_gs){ curTab=_gs; sessionStorage.removeItem('gitSekme'); } }catch(e){}   // Anlık Durum'dan gelindi
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function money(n){return (Math.round((+n||0)*100)/100).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2});}
  var MON=['','Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
  var DOW=['Paz','Pzt','Sal','Çar','Per','Cum','Cmt'];
  function fday(iso){var p=iso.split('-');return (+p[2])+' '+MON[+p[1]]+' '+p[0];}
  function dow(iso){var p=iso.split('-');return DOW[new Date(Date.UTC(+p[0],+p[1]-1,+p[2])).getUTCDay()];}
  function fdshort(iso){if(!iso)return '—';var p=String(iso).slice(0,10).split('-');return p.length>=3?(p[2]+'.'+p[1]):String(iso);}
  function fdt(w){if(!w)return '—';var s=String(w);var p=s.slice(0,10).split('-');var t=s.slice(11,16);return (p.length>=3?(p[2]+'.'+p[1]):s)+(t?' '+t:'');}
  var PAYNAME={Cash:'Nakit','Credit Card':'Kredi Kartı',Havale:'Havale','Wire Transfer':'Havale',CityLedger:'Cari (acente)'};
  function payname(m){return PAYNAME[m]||m;}
  // ---- storage (v1: tarayıcı; sonra buluta taşınır) ----
  function sset(k,v){try{localStorage.setItem(k,v);}catch(e){}}
  function sget(k){try{return localStorage.getItem(k)||'';}catch(e){return '';}}
  function K(tab,row){return 'RG:'+cur+':'+tab+':'+row;}
  function listKeyD(day,tab){return 'RG:'+day+':'+tab;}
  function listKey(tab){return listKeyD(cur,tab);}
  function loadListD(day,tab){try{var s=localStorage.getItem(listKeyD(day,tab));return s?JSON.parse(s):[];}catch(e){return [];}}
  function loadList(tab){return loadListD(cur,tab);}
  function saveListD(day,tab,a){sset(listKeyD(day,tab),JSON.stringify(a));}
  function saveList(tab,a){saveListD(cur,tab,a);}
  // problem listeleri kapsam boyunca (gün/hafta) — her satır kendi gününü taşır
  function scopeProblems(tab){var out=[];scopeDays().forEach(function(dd){loadListD(dd,tab).forEach(function(r,i){out.push({day:dd,i:i,r:r});});});return out;}
  function note(tab,row){return "<td><textarea data-k='"+K(tab,row)+"' placeholder='(açıklama gir)'>"+esc(sget(K(tab,row)))+"</textarea></td>";}
  // ---- kapsam: 'day' (varsayılan bugün) / 'week' (cur dahil son 7 gün) ----
  // Tüm tarih-bazlı listeler (oda değişimi, yorum, satış) kapsamı takip eder. Depolama
  // anahtarları HER ZAMAN satırın KENDİ gününe göredir (Kd) — gün modunda cur ile aynı,
  // yani eski kayıtlarla birebir uyumlu; hafta modunda günler arası çakışmaz.
  var scope='day';
  var SCOPES={day:1, week:7, month:30, year:365};
  function dmin(iso,k){var p=String(iso).slice(0,10).split('-');var d=new Date(Date.UTC(+p[0],+p[1]-1,+p[2]));d.setUTCDate(d.getUTCDate()-k);return d.toISOString().slice(0,10);}
  // cur dahil geriye n gün (eski→yeni). Problemler tarayıcıda saklı olduğu için her aralığı
  // kapsar; otomatik listeler (D.days) yalnızca sunucu penceresi kadar veri içerir.
  function scopeDays(){ var n=SCOPES[scope]||1; if(n<=1) return [cur]; var out=[]; for(var k=n-1;k>=0;k--){ out.push(dmin(cur,k)); } return out; }
  function scopeRows(kind){ var out=[]; scopeDays().forEach(function(dd){ (((D.days[dd]||{})[kind])||[]).forEach(function(r,idx){ out.push({day:dd,idx:idx,r:r}); }); }); return out; }
  function scopeLabel(){ if(scope!=='week') return fday(cur); var ds=scopeDays(); return ds.length?(fday(ds[0])+' – '+fday(ds[ds.length-1])):fday(cur); }
  function Kd(day,tab,row){return 'RG:'+day+':'+tab+':'+row;}
  function noteD(day,tab,row){return "<td><textarea data-k='"+Kd(day,tab,row)+"' placeholder='(açıklama gir)'>"+esc(sget(Kd(day,tab,row)))+"</textarea></td>";}
  function savebar(tab){return "<div class='saverow'><span class='autosave'>✓ Otomatik kaydedilir</span>"
    +"<span class='saved' data-savedmsg>kaydedildi ✓</span></div>";}
  function flash(){var m=document.querySelector('[data-savedmsg]');if(m){m.classList.add('show');clearTimeout(m._t);m._t=setTimeout(function(){m.classList.remove('show');},1200);}}

  // ---- panel içerikleri ----
  function pRC(){
    var items=scopeRows('rc'); var wk=(scope==='week');
    if(!items.length) return "<h2>Oda Değişimleri — "+scopeLabel()+"</h2><div class='ph'>Bu aralıkta oda değişimi yok.</div>";
    var h="<h2>Oda Değişimleri — "+scopeLabel()+"</h2>"
      +"<p class='lead'><b>Oda Notu</b> Elektra rezervasyonundaki 'Oda Notu'ndan gelir (oda değişim nedeni). Boşsa <span class='reason-none'>oda değişim notu yazılmamış</span> — bunları resepsiyona sor, <b>müdür açıklamasını</b> sen gir. Otomatik saklanır.</p>"
      +"<div style='overflow-x:auto'><table><thead><tr>"+(wk?"<th>Gün</th>":"")+"<th>Tarih-Saat</th><th>Misafir</th><th>Konaklama</th><th>Oda Değişimi</th><th>Yapan</th><th>Oda Notu (neden)</th><th style='width:22%'>Müdür açıklaması</th></tr></thead><tbody>";
    items.forEach(function(it){ var r=it.r;
      var reason=r.reason?"<span>"+esc(r.reason)+"</span>":"<span class='reason-none'>oda değişim notu yazılmamış</span>";
      var stay=(r.gin||r.cout)?(fdshort(r.gin)+(r.cintime?" <b title='check-in saati'>"+esc(r.cintime)+"</b>":"")+"<span class='arw'>→</span>"+fdshort(r.cout)):"—";
      h+="<tr"+(r.reason?"":" style='box-shadow:inset 3px 0 var(--statbad)'")+">"+(wk?"<td class='mono'>"+fdshort(it.day)+"</td>":"")+"<td class='mono'>"+esc(fdt(r.when))+"</td><td>"+esc(r.guest)+"</td>"
        +"<td class='mono'>"+stay+"</td>"
        +"<td class='chg'>"+esc(r.from)+"<span class='arw'>→</span>"+esc(r.to)+"</td>"
        +"<td>"+esc(r.user)+"</td><td>"+reason+"</td>"+noteD(it.day,'rc','rc'+it.idx)+"</tr>";
    });
    return h+"</tbody></table></div>"+savebar('rc');
  }
  function pBal(){
    var rows=D.openbal||[];
    if(!rows.length) return "<h2>Açık Bakiyeler</h2><div class='ph'>Açık (ödenmemiş) bakiye yok.</div>";
    var h="<h2>Açık Bakiyeler — ödenmemiş rezervasyonlar</h2>"
      +"<p class='lead'>Folyosunda açık bakiye olanlar (güncel). 🔴 çıkış yaptığı hâlde borçlu. En sağda müdür açıklaması.</p>"
      +"<table><thead><tr><th>Rez No</th><th>Oda</th><th>Misafir</th><th>Acenta</th><th>Durum</th><th class='r'>Borç</th><th style='width:24%'>Müdür açıklaması</th></tr></thead><tbody>";
    rows.forEach(function(r){
      var durum=r.left?"<span class='reason-none'>🔴 ÇIKTI — borçlu</span>":"Konaklıyor";
      h+="<tr"+(r.left?" style='box-shadow:inset 3px 0 var(--statbad)'":"")+"><td class='mono'>"+esc(r.rezid)+"</td>"
        +"<td>"+esc(r.room)+"</td><td>"+esc(r.guest)+"</td><td>"+esc(r.agency)+"</td><td>"+durum+"</td>"
        +"<td class='r money'>"+money(r.borc)+" ₺</td>"+note('bal',r.rezid)+"</tr>";
    });
    return h+"</tbody></table>"+savebar('bal');
  }
  function pCari(){
    var rows=D.cari||[];
    if(!rows.length) return "<h2>Açık Cariler</h2><div class='ph'>Açık cari alacak yok.</div>";
    var h="<h2>Açık Cariler — acente / firma alacakları</h2>"
      +"<p class='lead'>Sana borçlu acente/firmalar (güncel ekstre). Otomatik kanallar hariç. En sağda müdür açıklaması.</p>"
      +"<table><thead><tr><th>Kod</th><th>Cari / Firma</th><th class='r'>Alacak</th><th style='width:28%'>Müdür açıklaması</th></tr></thead><tbody>";
    rows.forEach(function(r){
      h+="<tr><td class='mono'>"+esc(r.kod)+"</td><td>"+esc(r.name)+"</td>"
        +"<td class='r money'>"+money(r.alacak)+" ₺</td>"+note('cari',r.kod)+"</tr>";
    });
    return h+"</tbody></table>"+savebar('cari');
  }
  function agdl(rows){var s={};rows.forEach(function(r){if(r.agency)s[r.agency]=1;});
    return "<datalist id='agdl'>"+Object.keys(s).map(function(a){return "<option value='"+esc(a)+"'>";}).join('')+"</datalist>";}
  function pSales(){
    var items=scopeRows('sales'); var wk=(scope==='week');
    if(!items.length) return "<h2>Oda Satış Fiyatları — "+scopeLabel()+"</h2><div class='ph'>Bu aralıkta oda satışı (giriş) yok.</div>";
    var h="<h2>Oda Satış Fiyatları — "+scopeLabel()+"</h2>"
      +"<p class='lead'><b>Giriş yapan</b> odalar — fiyatlar <b>TL</b>. <b>Liste</b> = fiyat listesine göre o oda ve gece için en düşük fiyat (Cuma–Cumartesi ve hafta içi ayrı, 7+ gecede uzun konaklama fiyatı). <span class='reason-none'>🔴 Walk-in / Telefon</span> satışı listenin altındaysa kırmızı: <b>indirim yapılmaz</b>, fiyatı uygulamayan satış — incele. Acente kontrat fiyatları farklı olabilir, kırmızı yapılmaz. <b style='color:var(--statbad)'>💵 NAKİT</b> = folyoda nakit tahsilat; listenin altında + nakit en riskli satıştır. Açıklamayı sağa gir — otomatik saklanır.</p>"
      +agdl(items.map(function(it){return it.r;}))
      +"<div class='filtbar'>🔎 <input data-sfilt list='agdl' placeholder='Oda / acenta / misafir / rez ara'> "
      +"<label style='display:inline-flex;align-items:center;gap:5px;font-size:12.5px;color:var(--sub);cursor:pointer'><input type='checkbox' data-sflag> sadece 🔴 işaretli</label></div>"
      +"<div style='overflow-x:auto'><table><thead><tr>"+(wk?"<th>Gün</th>":"")+"<th>Rez No</th><th>Oda</th><th>Misafir</th><th>Acenta</th><th class='r'>Gece</th><th class='r'>Ort. Gece Fiyatı (₺)</th><th class='r'>Liste (₺)</th><th>Ödeme</th><th style='width:20%'>Müdür açıklaması</th></tr></thead><tbody id='salesbody'>";
    items.forEach(function(it){ var r=it.r;
      var price=r.avg>0?(money(r.avg)+" ₺"):"—";
      if(r.low) price="<span class='reason-none'>"+price+" 🔴</span>";
      var methods=(r.pay||[]).map(payname).join(', ');
      var pay=methods?(r.cash?("💵 <b style='color:var(--statbad)'>"+esc(methods)+"</b>"):esc(methods)):"<span class='reason-none'>ödeme yok</span>";
      var flag=(r.low||r.cash)?'1':'0';
      var txt=esc(((r.room||'')+' '+(r.agency||'')+' '+(r.guest||'')+' '+(r.rez||'')).toLowerCase());
      h+="<tr data-flag='"+flag+"' data-txt=\""+txt+"\""+((r.low||r.cash)?" style='box-shadow:inset 3px 0 var(--statbad)'":"")
        +">"+(wk?"<td class='mono'>"+fdshort(it.day)+"</td>":"")+"<td class='mono'>"+esc(r.rez)+"</td><td class='mono'>"+esc(r.room)+"</td><td>"+esc(r.guest)+"</td><td>"+esc(r.agency)+"</td>"
        +"<td class='r'>"+esc(r.night)+"</td><td class='r mono'>"+price+"</td><td class='r mono'>"+(r.liste?money(r.liste):"—")+"</td><td>"+pay+"</td>"+noteD(it.day,'sales','r'+r.rez)+"</tr>";
    });
    return h+"</tbody></table></div>"+savebar('sales');
  }
  function roomdl(){return "<datalist id='roomdl'>"+(D.rooms||[]).map(function(rm){return "<option value='"+esc(rm)+"'>";}).join('')+"</datalist>";}
  function pProb(tab,title){
    var items=scopeProblems(tab); var wk=(scope==='week');
    var h="<h2>"+title+" — "+scopeLabel()+"</h2>"
      +"<p class='lead'>Oda seç (yazınca aranır) + problem yaz, <b>+ Ekle</b>; açıklamayı yaz. Bitince <b>Yapıldı</b>'yı işaretle. <b>Otomatik kaydedilir.</b> (Son 1 hafta seçiliyse haftanın tüm problemleri görünür.)</p>"
      +roomdl()
      +"<div class='filtbar'>🔎 <input data-rfilt list='roomdl' placeholder='Odaya göre filtrele (ör. 204)'></div>"
      +"<table><thead><tr>"+(wk?"<th style='width:66px'>Tarih</th>":"")+"<th style='width:100px'>Oda</th><th>Problem</th><th style='width:64px;text-align:center'>Yapıldı</th><th style='width:30%'>Müdür açıklama</th><th style='width:34px'></th></tr></thead><tbody data-list='"+tab+"' id='probbody'>";
    items.forEach(function(it){ var r=it.r, dd=it.day, i=it.i;
      var dn=r.done?'checked':'';
      h+="<tr"+(r.done?" style='opacity:.5'":"")+">"
        +(wk?"<td class='mono'>"+fdshort(dd)+"</td>":"")
        +"<td><input data-day='"+dd+"' data-f='oda' data-i='"+i+"' list='roomdl' value='"+esc(r.oda)+"' style='max-width:92px'></td>"
        +"<td><input data-day='"+dd+"' data-f='problem' data-i='"+i+"' value='"+esc(r.problem)+"'></td>"
        +"<td style='text-align:center'><input type='checkbox' data-done='"+i+"' data-day='"+dd+"' data-tab='"+tab+"' "+dn+"></td>"
        +"<td><textarea data-day='"+dd+"' data-f='note' data-i='"+i+"'>"+esc(r.note||'')+"</textarea></td>"
        +"<td><button class='rowdel' data-del='"+i+"' data-day='"+dd+"' data-tab='"+tab+"' title='sil'>✕</button></td></tr>";
    });
    if(!items.length) h+="<tr><td colspan='"+(wk?6:5)+"' style='padding:14px;color:var(--sub)'>Henüz kayıt yok — alttan ekle.</td></tr>";
    h+="</tbody></table>"
      +"<div class='addbar'><input data-add='oda' list='roomdl' placeholder='Oda (seç/yaz)' style='max-width:130px'>"
      +"<input data-add='problem' placeholder='Problem'>"
      +"<button class='btn ghost' data-addbtn='"+tab+"'>+ Ekle</button></div>"+savebar(tab);
    return h;
  }
  // ---- Eksik Bilgiler: gün modunda seçilen gün + ÖNCEKİ gün girişleri (sahibin isteği, 28.10.2026),
  // diğer kapsamlarda kapsam günleri. Veri GÜNCEL durumdur: listedekiler ŞU AN hâlâ eksik.
  // Hâlâ konaklayanlar üstte — misafir otelde, hemen tamamlanabilir.
  function eksikDays(){ return scope==='day' ? [dmin(cur,1), cur] : scopeDays(); }
  function eksikRows(){ var ds=eksikDays();
    return (D.eksik||[]).filter(function(x){return ds.indexOf(x.day)>=0;}).sort(function(a,b){
      return (b.inhouse-a.inhouse) || (a.day<b.day?1:(a.day>b.day?-1:0)) || ((+a.room)-(+b.room)); }); }
  function pEksik(){
    var ds=eksikDays();
    var title="Eksik Bilgiler — "+(scope==='day'?(fday(ds[0])+' + '+fday(ds[1])):scopeLabel())+" girişleri";
    if(D.eksik==null) return "<h2>"+title+"</h2><div class='ph'>Eksik bilgi verisi bu güncellemede alınamadı; bir sonraki güncellemede gelir.</div>";
    var items=eksikRows();
    if(!items.length) return "<h2>"+title+"</h2><div class='ph'>Bu günlerde girişi yapılan kayıtlarda eksik telefon / kimlik yok. (Son 7 günün girişleri izlenir.)</div>";
    var h="<h2>"+title+"</h2>"
      +"<p class='lead'>Resepsiyonun bu günlerde girişini yaptığı ve <b>hâlâ</b> telefonu ya da kimliği eksik kayıtlar. "
      +"<b>Konaklayanlar üstte</b> (kırmızı kenar) — misafir otelde, hemen tamamlansın. Telefon: odada tek numara yeter; "
      +"kimlik: odadaki her kişi. Expedia / Tatil Budur gibi kanalların gizli numaraları burada sayılmaz — Eksik Bilgiler sayfasındaki <i>elle kontrol</i> listesine bakın.</p>"
      +"<div style='overflow-x:auto'><table><thead><tr><th>Durum</th><th>Giriş → Çıkış</th><th>Oda</th><th>Misafir</th>"
      +"<th class='r'>Kişi</th><th>Kanal</th><th>Eksik</th><th>Girişi yapan</th><th>Rez No</th></tr></thead><tbody>";
    items.forEach(function(r){
      h+="<tr"+(r.inhouse?" style='box-shadow:inset 3px 0 var(--statbad)'":"")+">"
        +"<td>"+(r.inhouse?"<b>Konaklıyor</b>":"<span style='color:var(--sub)'>Çıktı</span>")+"</td>"
        +"<td class='mono'>"+fdshort(r.ci)+"<span class='arw'>→</span>"+fdshort(r.co)+"</td>"
        +"<td class='mono'>"+esc(r.room)+"</td><td>"+esc(r.guest)+"</td><td class='r'>"+esc(r.pax||'—')+"</td>"
        +"<td>"+esc(r.agency)+"</td><td>"+(r.gaps||[]).map(esc).join('<br>')+"</td>"
        +"<td style='white-space:nowrap'>"+(r.user?"<span class='who'>"+esc(r.user)+"</span> <span style='color:var(--sub);font-size:11.5px'>"+esc(r.utime)+"</span>":"—")+"</td>"
        +"<td class='mono'>"+esc(r.rez)+"</td></tr>";
    });
    return h+"</tbody></table></div>";
  }
  var YPLAT=['','Google','Tripadvisor','Booking','Expedia','ETS','Diğer'];
  function psel(key){var v=sget(key);
    return "<select data-k='"+key+"'>"+YPLAT.map(function(o){
      return "<option value='"+esc(o)+"'"+(o===v?' selected':'')+">"+(o?esc(o):'(seç)')+"</option>";}).join('')+"</select>";}
  function yorumSay(istendi){ return scopeRows('dep').filter(function(x){
      return (sget(Kd(x.day,'yistendi',x.r.rez||(x.day+'i'+x.idx)))==='1')===istendi; }).length; }
  function pYorum(){
    var items=scopeRows('dep'); var wk=(scope==='week');
    if(!items.length) return "<h2>İstenilen Yorumlar</h2><div class='ph'>Bu aralıkta çıkış yok.</div>";
    var h="<h2>İstenilen Yorumlar — çıkış yapan misafirler ("+scopeLabel()+")</h2>"
      +"<p class='lead'>Çıkış yapan misafirler (rez no, kanal, gerçek giriş-çıkış saatiyle). <b>Yorum istenildi mi?</b> kutusunu işaretle; yorum karşılığı <b>%10 indirim</b> vereceğin misafiri işaretle, <b>platformu</b> seç, önce <b>açıklamanı</b> sonra misafirin <b>yorumunu</b> yaz. Otomatik saklanır.</p>"
      +"<div style='overflow-x:auto'><table><thead><tr>"+(wk?"<th>Gün</th>":"")+"<th>Oda</th><th>Rez No</th><th>Misafir</th><th>Kanal</th><th>Giriş–Çıkış</th>"
      +"<th style='text-align:center'>Yorum<br>istenildi mi?</th><th style='text-align:center'>%10<br>indirim</th><th>Platform</th><th style='width:19%'>Yorum açıklama</th><th style='width:21%'>Misafir yorumu</th></tr></thead><tbody>";
    items.forEach(function(it){ var r=it.r; var dk=it.day;
      var kk=r.rez||(dk+'i'+it.idx);
      var yreq=sget(Kd(dk,'yistendi',kk))==='1'?'checked':'';
      var ck=sget(Kd(dk,'yind',kk))==='1'?'checked':'';
      var stay=(fdshort(r.gin)+(r.gintime?" <b>"+esc(r.gintime)+"</b>":""))+"<span class='arw'>→</span>"+(fdshort(r.cout)+(r.couttime?" <b>"+esc(r.couttime)+"</b>":""));
      h+="<tr>"+(wk?"<td class='mono'>"+fdshort(dk)+"</td>":"")+"<td class='mono'>"+esc(r.room)+"</td><td class='mono'>"+esc(r.rez)+"</td><td>"+esc(r.guest)+"</td>"
        +"<td>"+esc(r.kanal)+"</td><td class='mono'>"+stay+"</td>"
        +"<td style='text-align:center'><input type='checkbox' data-ck='"+Kd(dk,'yistendi',kk)+"' "+yreq+"></td>"
        +"<td style='text-align:center'><input type='checkbox' data-ck='"+Kd(dk,'yind',kk)+"' "+ck+"></td>"
        +"<td>"+psel(Kd(dk,'yplat',kk))+"</td>"
        +"<td><textarea data-k='"+Kd(dk,'yaci',kk)+"'>"+esc(sget(Kd(dk,'yaci',kk)))+"</textarea></td>"
        +"<td><textarea data-k='"+Kd(dk,'yyor',kk)+"'>"+esc(sget(Kd(dk,'yyor',kk)))+"</textarea></td></tr>";
    });
    return h+"</tbody></table></div>"+savebar('yorum');
  }
  var TABS=[
    {k:'bal',  t:'Açık Bakiyeler',  cnt:function(){return (D.openbal||[]).length;}, f:pBal},
    {k:'cari', t:'Açık Cariler',    cnt:function(){return (D.cari||[]).length;}, f:pCari},
    {k:'sales',t:'Oda Satış Fiyatları', cnt:function(){return scopeRows('sales').filter(function(x){return x.r.low||x.r.cash;}).length;}, f:pSales},
    {k:'eksik',t:'Eksik Bilgiler', cnt:function(){return eksikRows().filter(function(x){return x.inhouse;}).length;}, f:pEksik},
    {k:'rc',   t:'Oda Değişimleri', cnt:function(){return scopeRows('rc').filter(function(x){return !x.r.reason;}).length;}, f:pRC},
    // yeşil = yorum istenen, kırmızı = henüz istenmeyen çıkış (sahibin isteği, 28.10.2026)
    {k:'yorum',t:'İstenilen Yorumlar', ok:function(){return yorumSay(true);}, cnt:function(){return yorumSay(false);}, f:pYorum},
    {k:'odap', t:'Oda Problemleri', cnt:function(){return scopeProblems('odap').filter(function(x){return !x.r.done;}).length;}, f:function(){return pProb('odap','Oda Problemleri');}},
    {k:'temp', t:'Temizlik Problemleri', cnt:function(){return scopeProblems('temp').filter(function(x){return !x.r.done;}).length;}, f:function(){return pProb('temp','Temizlik Problemleri');}}
  ];

  // ---- Sabah notu: sekmelerin AYNI verisinden yazılır (sahibi 20.11.2026: "tablo ne diyorsa yukarıda o
  // yazsın, bütün sekmelerden bahsetsin; dün hiç yorum istenmedi, oda problemi yoktu gibi kısa not") ----
  var MONL=['','Ocak','Şubat','Mart','Nisan','Mayıs','Haziran','Temmuz','Ağustos','Eylül','Ekim','Kasım','Aralık'];
  var DOWL=['Pazar','Pazartesi','Salı','Çarşamba','Perşembe','Cuma','Cumartesi'];
  function tl0(n){return Math.round(+n||0).toLocaleString('tr-TR');}
  function gunAdi(iso){return cur===D.dun?'Dün':(iso===D.bugun?'Bugün':fday(iso));}
  function li(cls,tab,html){return "<button class='sb-li "+cls+"' data-go='"+tab+"'><i></i><span>"+html+"</span></button>";}
  function box(cls,tab,lab,val,alt){return "<button class='sb-box "+cls+"' data-go='"+tab+"'><span>"+lab+"</span><b>"+val+"</b><span>"+alt+"</span></button>";}
  function renderOzet(){
    var t=document.getElementById('sbText'); if(!t) return;
    var p=cur.split('-'), wd=new Date(Date.UTC(+p[0],+p[1]-1,+p[2])).getUTCDay();
    document.getElementById('sbTitle').textContent=(cur===D.dun?'Dün, ':(cur===D.bugun?'Bugün, ':''))+(+p[2])+' '+MONL[+p[1]]+' '+DOWL[wd];
    var gv=(D.gunv||{})[cur]||{}, day=D.days[cur]||{}, sales=day.sales||[], deps=day.dep||[], rc=day.rc||[];
    var G=gunAdi(cur), g=G.toLowerCase();
    // tahsilat: CityLedger tahsilat değil, acenteye (cariye) aktarım → ayrı
    var tah=gv.tah||{}, tsum=0, aktar=0, parts=[];
    Object.keys(tah).sort(function(a,b){return tah[b]-tah[a];}).forEach(function(k){
      if(k==='CityLedger'){aktar+=tah[k];return;} tsum+=tah[k]; parts.push(payname(k)+' '+tl0(tah[k])); });
    var odesiz=sales.filter(function(r){return !(r.pay||[]).length;});
    var ob=D.openbal||[], obsum=ob.reduce(function(a,r){return a+(+r.borc||0);},0);
    var gitti=ob.filter(function(r){return r.left;}), bugunCik=ob.filter(function(r){return !r.left&&r.co&&r.co<=D.bugun;});
    var cari=D.cari||[], muh=cari.filter(function(r){return /MUHTEL/i.test(r.name);}), adl=cari.filter(function(r){return !/MUHTEL/i.test(r.name);});
    var csum=adl.reduce(function(a,r){return a+(+r.alacak||0);},0);
    var c7=0; for(var k=0;k<7;k++){var x=(D.gunv||{})[dmin(cur,k)]; if(x&&x.ctah) c7+=x.ctah;}
    var low=sales.filter(function(r){return r.low;}), lowSum=low.reduce(function(a,r){return a+((+r.avg||0)-(+r.liste||0));},0);
    var cash=sales.filter(function(r){return r.cash;});
    var iade=gv.iade||[], kim=[]; iade.forEach(function(r){ if(r.user&&kim.indexOf(r.user)<0) kim.push(r.user); });
    var iSum=iade.reduce(function(a,r){return a+Math.abs(+r.total||0);},0);
    var eks=eksikRows(), eksIn=eks.filter(function(x){return x.inhouse;});
    var rcNo=rc.filter(function(r){return !r.reason;});
    var yIst=yorumSay(true), op=scopeProblems('odap'), tp=scopeProblems('temp');
    var opA=op.filter(function(x){return !x.r.done;}), tpA=tp.filter(function(x){return !x.r.done;});
    if(scope!=='day'){ t.innerHTML="<p style='color:var(--sub);margin:0'>Sabah notu tek gün seçiliyken yazılır. Aşağıdaki sekmeler seçilen aralığı gösterir.</p>"; }
    else {
      // DÜZENLİ (sahibi 20.11): konu başına tek satır; GRUPLU (cari, satış kontrolü, problemler tek satır) ve
      // RENGE GÖRE SIRALI: yeşil önce, turuncu sonra, kırmızı en son. Grubun rengi en kötü parçasının rengi.
      var LV={'':0,warn:1,bad:2}, CL=['','warn','bad'], rows=[];
      function row(cls,tab,lab,txt){rows.push({lv:LV[cls]||0,h:"<button class='sb-row "+cls+"' data-go='"+tab+"'><i></i><b>"+lab+"</b><span>"+txt+"</span></button>"});}
      function worst(){var m=0;for(var a=0;a<arguments.length;a++)m=Math.max(m,LV[arguments[a]]||0);return CL[m];}
      function oda(r){var a=String(r.agency||'');return String(r.room).length>6?(esc(a.charAt(0)+a.slice(1).toLowerCase())+' folyosu'):esc(r.room);}
      row('', 'sales', 'Doluluk', (gv.dolu!=null?gv.dolu:'—')+"/55 oda"+(gv.dolu?" (%"+Math.round(gv.dolu*100/55)+")":"")+" · "+sales.length+" giriş · "+deps.length+" çıkış");
      row(odesiz.length?'bad':'', 'sales', 'Giriş ödemesi', !sales.length?"giriş yok":(odesiz.length?odesiz.length+" ödemesiz — oda "+odesiz.slice(0,4).map(oda).join(', '):"hepsi ödedi"));
      row('', 'sales', 'Tahsilat', tsum?(tl0(tsum)+" ₺ — "+esc(parts.join(' · '))):"kayıt yok");
      row(gitti.length?'bad':(ob.length?'warn':''), 'bal', 'Borçlu misafir', !ob.length?"yok, herkes ödemiş":(ob.length+" kişi · "+tl0(obsum)+" ₺"
          +(gitti.length?" · çıkıp giden: "+gitti.map(function(r){return oda(r)+" "+tl0(r.borc);}).join(', '):"")
          +(bugunCik.length?" · bugün çıkacak: "+bugunCik.map(function(r){return oda(r)+" "+tl0(r.borc);}).join(', '):"")));
      row('', 'cari', 'Cari', "açık "+tl0(csum)+" ₺ ("+adl.length+")"
          +" · tahsilat "+g+" "+(gv.ctah==null?"?":(gv.ctah>0?tl0(gv.ctah)+" ₺":"yok"))+", 7 gün "+tl0(c7)+" ₺"
          +(aktar?" · cariye aktarılan "+tl0(aktar)+" ₺":""));
      var sk=[]; if(low.length) sk.push("liste altı "+low.length+" ("+low.slice(0,3).map(function(r){return esc(r.room)+" "+tl0((+r.avg||0)-(+r.liste||0));}).join(', ')+")");
      if(cash.length) sk.push("nakit "+cash.length+" ("+cash.slice(0,3).map(function(r){return esc(r.room);}).join(', ')+")");
      row(worst(low.length?'bad':'', cash.length?'warn':''), 'sales', 'Satış kontrolü', sk.length?sk.join(' · '):"liste altı ve nakit satış yok");
      row(iade.length?'warn':'', 'sales', 'İndirim / iade', iade.length?(iade.length+" kayıt · "+tl0(iSum)+" ₺ · "+esc(kim.join(', '))):"yok");
      row(eksIn.length?'bad':(eks.length?'warn':''), 'eksik', 'Eksik bilgi', eks.length?(eks.length+" kayıt · otelde olan "+eksIn.length):"yok");
      row(rcNo.length?'warn':'', 'rc', 'Oda değişimi', rc.length?(rc.length+" · notu yazılmamış "+rcNo.length):"olmadı");
      row(deps.length&&!yIst?'warn':'', 'yorum', 'Yorum', !deps.length?"çıkış yok":(yIst?(deps.length+" çıkıştan "+yIst+" misafirden istendi"):("hiç istenmedi ("+deps.length+" çıkış)")));
      row(worst(opA.length?'warn':'', tpA.length?'warn':''), opA.length||!tpA.length?'odap':'temp', 'Problemler',
          "oda "+(op.length?op.length+(opA.length?" (açık "+opA.length+")":" (yapıldı)"):"yok")+" · temizlik "+(tp.length?tp.length+(tpA.length?" (açık "+tpA.length+")":" (yapıldı)"):"yok"));
      rows.sort(function(a,b){return a.lv-b.lv;});   // Array.sort kararlı: aynı renkte asıl sıra korunur
      var R=rows.map(function(x){return x.h;}).join('');
      t.innerHTML="<div class='sb-rows'>"+R+"</div>";
    }
    document.getElementById('sbBoxes').innerHTML=
      box('', 'sales', 'Tahsilat · '+g, tl0(tsum)+' ₺', esc(parts.slice(0,3).join(' · ')||'kayıt yok'))
     +box(gitti.length?'bad':(ob.length?'warn':'ok'), 'bal', 'Ödemeyenler (şu an)', ob.length?(ob.length+' · '+tl0(obsum)+' ₺'):'yok',
          gitti.length?(gitti.length+' kişi çıkıp gitti'):(bugunCik.length?(bugunCik.length+' kişi bugün çıkıyor'):(ob.length?'hepsi otelde':'herkes ödemiş')))
     +box('', 'cari', 'Açık cari', tl0(csum)+' ₺', adl.length+' cari'+(muh.length?' · Muhtelif hariç':''))
     +box(low.length?'bad':(iade.length?'warn':'ok'), 'sales', 'Liste altı · iade', low.length+' · '+iade.length,
          (low.length?tl0(lowSum)+' ₺':'liste altı yok')+' · '+(iade.length?tl0(iSum)+' ₺ iade':'iade yok'));
  }
  document.querySelector('.sb').addEventListener('click',function(e){var b=e.target.closest('[data-go]');if(b){curTab=b.getAttribute('data-go');renderTabs();renderPanel();
    var tt=document.getElementById('tabs'); if(tt&&tt.scrollIntoView) tt.scrollIntoView({behavior:'smooth',block:'start'});}});
  // ---- render ----
  function renderTabs(){
    document.getElementById('tabs').innerHTML=TABS.map(function(tb){
      var c=tb.cnt(), g=tb.ok?tb.ok():0;
      var b=(g>0?" <span class='cnt ok' title='yorum istendi'>"+g+"</span>":"")
           +(c>0?" <span class='cnt'"+(tb.ok?" title='yorum istenmedi'":"")+">"+c+"</span>":"");
      return "<button class='tab"+(tb.k===curTab?" active":"")+"' data-tab='"+tb.k+"'>"+tb.t+b+"</button>";
    }).join('');
    renderOzet();   // yorum/problem işaretlenince not da güncellensin
  }
  function renderPanel(){
    var tb=TABS.filter(function(x){return x.k===curTab;})[0]||TABS[0];
    document.getElementById('panels').innerHTML="<div class='panel active'>"+tb.f()+"</div>";
  }
  function renderDay(){
    var el=document.getElementById('curday');
    if(scope!=='day'){ var LBL={week:'son 1 hafta',month:'son 1 ay',year:'son 1 yıl'}; el.innerHTML=esc(scopeLabel())+"<small>"+(LBL[scope]||'')+"</small>"; }
    else { el.innerHTML=esc(fday(cur))+"<small>"+esc(dow(cur))+(cur===D.dun?' · DÜN':(cur===D.today?' · BUGÜN':''))+"</small>"; }
    var i=alldays.indexOf(cur);
    document.getElementById('dprev').disabled=(i<=0);
    document.getElementById('dnext').disabled=(i>=alldays.length-1);
    var sel=document.getElementById('scopeSel'); if(sel) sel.value=scope;
  }
  function full(){renderDay();renderTabs();renderPanel();}
  // ---- events ----
  document.getElementById('dprev').onclick=function(){var i=alldays.indexOf(cur);if(i>0){cur=alldays[i-1];full();}};
  document.getElementById('dnext').onclick=function(){var i=alldays.indexOf(cur);if(i<alldays.length-1){cur=alldays[i+1];full();}};
  var _ss=document.getElementById('scopeSel'); if(_ss) _ss.onchange=function(){scope=this.value; full();};
  document.getElementById('tabs').addEventListener('click',function(e){var b=e.target.closest('[data-tab]');if(b){curTab=b.getAttribute('data-tab');renderTabs();renderPanel();}});
  // otomatik kayıt (textarea[data-k], checkbox[data-ck]) + problem listeleri
  document.getElementById('panels').addEventListener('input',function(e){
    var t=e.target, did=false;
    if(t.hasAttribute&&t.hasAttribute('data-k')){ sset(t.getAttribute('data-k'),t.value); did=true; }
    var f=t.getAttribute&&t.getAttribute('data-f');
    if(f){ var tbody=t.closest('[data-list]'); if(tbody){var tab=tbody.getAttribute('data-list');var day=t.getAttribute('data-day')||cur;var a=loadListD(day,tab);var i=+t.getAttribute('data-i');if(a[i]){a[i][f]=t.value;saveListD(day,tab,a);did=true;}} }
    if(t.getAttribute&&t.getAttribute('data-rfilt')!=null){ applyFilter(t); }
    if(t.getAttribute&&t.getAttribute('data-sfilt')!=null){ applySalesFilter(); }
    if(did) flash();
  });
  document.getElementById('panels').addEventListener('change',function(e){
    var t=e.target; if(t.hasAttribute&&t.hasAttribute('data-ck')){ sset(t.getAttribute('data-ck'),t.checked?'1':'0'); if(t.getAttribute('data-ck').indexOf(':yistendi:')>0) renderTabs(); flash(); }
    if(t.hasAttribute&&t.hasAttribute('data-done')){ var dday=t.getAttribute('data-day')||cur, dtab=t.getAttribute('data-tab'), da=loadListD(dday,dtab), di=+t.getAttribute('data-done'); if(da[di]){da[di].done=t.checked; saveListD(dday,dtab,da);} renderTabs(); renderPanel(); flash(); }
    if(t.tagName==='SELECT'&&t.hasAttribute&&t.hasAttribute('data-k')){ sset(t.getAttribute('data-k'),t.value); flash(); }
    if(t.getAttribute&&t.getAttribute('data-rfilt')!=null){ applyFilter(t); }
    if(t.getAttribute&&t.getAttribute('data-sflag')!=null){ applySalesFilter(); }
  });
  document.getElementById('panels').addEventListener('click',function(e){
    var add=e.target.closest('[data-addbtn]');
    if(add){var tab=add.getAttribute('data-addbtn');var box=add.parentNode;
      var oda=box.querySelector("[data-add='oda']").value.trim(), prob=box.querySelector("[data-add='problem']").value.trim();
      if(!oda&&!prob)return; var a=loadList(tab);a.push({oda:oda,problem:prob,note:''});saveList(tab,a);renderTabs();renderPanel();flash();return;}
    var del=e.target.closest('[data-del]');
    if(del){var tab=del.getAttribute('data-tab')||del.closest('[data-list]').getAttribute('data-list');var day=del.getAttribute('data-day')||cur;var a=loadListD(day,tab);a.splice(+del.getAttribute('data-del'),1);saveListD(day,tab,a);renderPanel();renderTabs();flash();return;}
  });
  function applyFilter(inp){
    var q=(inp.value||'').trim(); var tbody=document.querySelector('#probbody');
    if(!tbody)return; [].slice.call(tbody.rows).forEach(function(tr){
      var oda=(tr.querySelector("[data-f='oda']")||{}).value||'';
      tr.style.display=(!q||String(oda).indexOf(q)>=0)?'':'none';
    });
  }
  function applySalesFilter(){
    var body=document.querySelector('#salesbody'); if(!body)return;
    var qi=document.querySelector('[data-sfilt]'), fi=document.querySelector('[data-sflag]');
    var q=((qi&&qi.value)||'').trim().toLowerCase(), onlyFlag=!!(fi&&fi.checked);
    [].slice.call(body.rows).forEach(function(tr){
      var txt=tr.getAttribute('data-txt')||'', flag=tr.getAttribute('data-flag')==='1';
      tr.style.display=((!q||txt.indexOf(q)>=0)&&(!onlyFlag||flag))?'':'none';
    });
  }
  full();
})();
</script>"""


SATIS_MIN_FIYAT = 3500     # oda tipi bilinmeyen satışta yedek sınır
ODA_KOD = {"EKOBALK": "eko", "STUDMUT": "stu", "SPROOM": "sup", "SPMUT": "sup",
           "DLXMUT": "dlx", "DLXBALK": "dlx", "SUITMUT": "sui"}   # Elektra ROOMTYPE → FIYAT_ODALAR
SATIS_PAYI = 30            # TL — kur yuvarlaması; listenin bundan fazla altı "düşük"
LISTE_TARIHI = dt.date(2026, 10, 27)   # bu tarihten önce satılanlar eski kuralla (SATIS_MIN_FIYAT) değerlendirilir
ILK_BASAMAK_04_11 = dt.date(2026, 11, 4)   # 1. basamak 200 TL indi; bundan önceki satışlar eski 1. basamakla
ILK_BASAMAK_ESKI = {"eko": 3000, "stu": 3200, "sup": 3400, "dlx": 3800, "sui": 4500}


def satis_liste_fiyati(a):
    """Rezervasyonun gecelik liste (taban) fiyatı, TL — fiyat listesine göre olması gereken en düşük.
    Satış günü (CREATEDATE) gecenin kendisiyse aynı gün fiyatı, önceyse ileri tarih fiyatı; doluluk
    hesaba katılmaz (taban). 7+ gecede uzun konaklama fiyatı. Oda tipi bilinmiyorsa None."""
    k = ODA_KOD.get(str(a.get("ROOMTYPE") or "").strip().upper())
    oda = next((r for r in FIYAT_ODALAR if r[0] == k), None)
    ci, co = pdate(a.get("CHECKIN")), pdate(a.get("CHECKOUT"))
    if not oda or not ci:
        return None
    gece = int(num(a.get("NIGHT")) or ((co - ci).days if co else 1) or 1)
    ut = uzun_taban(k, gece)
    if ut:
        return ut
    satis = pdate(a.get("CREATEDATE")) or ci
    if satis < LISTE_TARIHI:
        return None            # 27.10 listesinden önceki satış: o günkü kural farklıydı (indirim serbestti)
    if satis < ILK_BASAMAK_04_11:
        # 04.11'den önceki satış: eski 1. basamak, aynı gün Pazar–Cuma en az 2. basamak
        oda = oda[:3] + ((ILK_BASAMAK_ESKI[k],) + tuple(oda[3][1:]),)
        geceler = [ci + dt.timedelta(days=i) for i in range(max(1, min(gece, 31)))]
        return round(sum(oda[3][2] - GECE_INDIRIM.get(d, 0) if d <= satis and d.weekday() != 5
                         else gece_taban(oda, d, satis, eski=True) for d in geceler) / len(geceler))
    geceler = [ci + dt.timedelta(days=i) for i in range(max(1, min(gece, 31)))]
    return round(sum(gece_taban(oda, d, satis, eski=satis < YENI_LISTE) for d in geceler) / len(geceler))


def _is_direct_agency(agency):
    """Resepsiyonun kendi fiyatladığı satış mı (Walk-in / Telefon / acentasız)? Acente
    rezervasyonları (Booking, Expedia, Setur…) kontrat fiyatıyla gelir — düşük olması normal,
    kırmızı işaretlenmez. Kırmızı SADECE resepsiyon fiyatı düşükse."""
    a = str(agency or "").strip().upper()
    return (not a) or ("WALK" in a) or ("TELEFON" in a) or ("PHONE" in a)


# ---------------------------------------------------------------------------
# TV Kullanım Kartları — odalara konan "Next uydu alıcısı + TV kumandası" kartları.
# Elektra'ya ihtiyaç yok: kartlar/tv-kumanda/uret.py'nin yazdığı kartlar.json'ı okur.
# Kart dosyaları (PDF/PNG) şifresiz statik dosya olarak yayınlanır (dashboard.py
# kopyalar) — misafir odasına konmak için basılan kartlar, gizli bilgi içermez. Bu
# sayfa ise her bölüm gibi şifreli; resepsiyon + yönetim ikisi de açar.
# ---------------------------------------------------------------------------
# DİKKAT: "_pl" adı bu dosyada vergi hesabının gelir-tablosu fonksiyonu; pathlib'i o adla
# içe aktarmak onu ezdi ve Vergi Sayfası 08–14.10.2026 arası üretilemedi.
import pathlib as _pathlib
TVKART_DIR = _pathlib.Path(__file__).resolve().parent / "kartlar" / "tv-kumanda"
TVKART_URL = "kartlar/tv-kumanda/"

TVKART_CSS = """
<style>
.tvk{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:16px;margin:14px 0 4px}
.tvk .card{display:flex;flex-direction:column;gap:11px;padding:14px}
.tvk .thumb{display:block;background:#fff;border:1px solid var(--border);border-radius:10px;overflow:hidden}
.tvk .thumb img{display:block;width:100%;height:auto}
.tvk h3{margin:0;font-size:14px;display:flex;align-items:center;gap:8px}
.kod{display:inline-flex;align-items:center;justify-content:center;width:22px;height:22px;flex:none;
  border-radius:6px;background:var(--eyebrow);color:var(--card);font-size:12px;font-weight:800}
.btns{display:flex;flex-wrap:wrap;gap:6px}
.dl{display:inline-flex;align-items:center;gap:6px;padding:8px 12px;border-radius:9px;
  border:1px solid var(--border);background:var(--bg);color:var(--fg);text-decoration:none;
  font-size:12.5px;font-weight:600;line-height:1.2}
.dl:hover{border-color:var(--eyebrow)}
.dl:focus-visible{outline:2px solid var(--eyebrow);outline-offset:2px}
.dl.main{background:var(--eyebrow);border-color:var(--eyebrow);color:var(--card)}
.dl small{font-weight:500;opacity:.75}
.howto{margin:8px 0 0;padding-left:18px;color:var(--sub);font-size:12.5px;line-height:1.7}
.spec{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;margin:6px 0 10px;font-size:13px}
.spec dt{color:var(--sub)}.spec dd{margin:0;font-weight:600}
</style>"""


def build_tvkart(env=None):
    m = json.loads((TVKART_DIR / "kartlar.json").read_text(encoding="utf-8"))
    kartlar = m["kartlar"]
    u = lambda f: esc(TVKART_URL + f)

    def isim(k, uz):
        return esc(f"TV-karti-{k['kod']}-{k['ad'].replace(' · ', '-').replace(' ', '-')}{uz}")

    cards = "".join(
        f"<div class='card'>"
        f"<a class='thumb' href='{u(k['png'])}' target='_blank' rel='noopener' "
        f"title='Büyük görmek için tıklayın'><img src='{u(k['onizleme'])}' "
        f"alt='TV kartı {esc(k['kod'])} — {esc(k['ad'])} kumandası' loading='lazy'></a>"
        f"<h3><span class='kod'>{esc(k['kod'])}</span>{esc(k['ad'].replace(' · ', ' '))} kumandası</h3>"
        f"<div class='btns'>"
        f"<a class='dl main' href='{u(k['pdf'])}' download='{isim(k, '.pdf')}'>⤓ PDF</a>"
        f"<a class='dl' href='{u(k['png'])}' download='{isim(k, '.png')}'>⤓ PNG <small>WhatsApp</small></a>"
        f"<a class='dl' href='{u(k['matbaa'])}' download='{isim(k, '-matbaa.pdf')}'>⤓ Matbaa PDF</a>"
        f"</div></div>" for k in kartlar)

    body = (
        TVKART_CSS +
        "<p class='lead'>Odadaki <b>TV kumandasına</b> bakın, aynı kumandanın olduğu kartı seçin. "
        "Kartın sağ alt köşesindeki küçük harf (A–D) da hangi kumanda için olduğunu gösterir. "
        "Görsele tıklayınca kart büyük açılır.</p>"
        f"<div class='tvk'>{cards}</div>"
        "<div class='grid2' style='margin-top:18px'>"
        "<div class='card'><h3>Ofis yazıcısında basmak</h3>"
        f"<div class='btns'><a class='dl main' href='{u(m['a4'])}' download='TV-kartlari-4u-bir-A4.pdf'>"
        "⤓ 4 kart tek A4 · PDF</a></div>"
        "<ol class='howto'><li>Yazdırırken ölçeği <b>%100 / Gerçek boyut</b> seçin "
        "(<i>Sayfaya sığdır</i> kapalı olsun).</li>"
        "<li>Kesik çizgilerden kesin — bir A4'ten dört kart (A, B, C, D) çıkar.</li>"
        "<li>Tek bir kumanda için çok kart gerekiyorsa o kartın kendi PDF'ini basın.</li></ol></div>"
        "<div class='card'><h3>Matbaaya göndermek</h3>"
        "<p class='lead' style='margin-bottom:4px'>Her kartın <b>Matbaa PDF</b> düğmesindeki dosyayı "
        "gönderin; her karttan kaç adet istediğinizi yazın.</p>"
        "<dl class='spec'>"
        "<dt>Kesim boyu</dt><dd>A6 · 105 × 148 mm</dd>"
        "<dt>Dosya</dt><dd>her yanda 3 mm taşma payı + kesim işaretli</dd>"
        "<dt>Baskı</dt><dd>tek yüz, 4 renk</dd>"
        "<dt>Kâğıt önerisi</dt><dd>300–350 g kuşe + mat selefon</dd>"
        "<dt>Renk</dt><dd>RGB — matbaa CMYK'ya kendisi çevirir</dd>"
        "</dl></div></div>"
        "<div class='note'>Kartlar misafir odasına konmak için hazırlandı; içlerinde gizli bilgi yoktur. "
        "Yeni bir TV modeli gelirse ya da metin değişirse kartlar yeniden üretilip burada güncellenir.</div>")
    return {"label": "TV Kullanım Kartları", "count": len(kartlar), "count_label": "kart",
            "tone": "ok", "sub": "Next + TV kumandası · indir, yazdır, matbaaya gönder",
            "updated": now_str(),
            "html": PAGE("Oda hazırlığı", "TV Kullanım Kartları",
                         "Misafirin uydu yayınını açabilmesi için her TV kumandasına ayrı kart",
                         body)}



# ---------------------------------------------------------------------------
# Google Yorum Kartları (16.11.2026) — çıkışta her misafire verilen QR'lı A6 kart.
# Üretici: kartlar/yorum/uret.py (5 renk, ön TR / arka EN, matbaa + A4). dashboard.py dosyaları
# public/kartlar/yorum/'a şifresiz kopyalar (basılı kart, gizli değil). QR → rivaalsancak.com/yorum.html
# → Google "yorum yaz"; hedef değişirse sitedeki yorum.html güncellenir, basılı kart değişmez.
# ---------------------------------------------------------------------------
YORUMKART_DIR = _pathlib.Path(__file__).resolve().parent / "kartlar" / "yorum"
YORUMKART_URL = "kartlar/yorum/"
YORUMKART_CSS = """
<style>
.ykr{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin:14px 0 4px}
.ykr .card{display:flex;flex-direction:column;gap:10px;padding:14px}
.ykr .yuz{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.ykr .thumb{display:block;border:1px solid var(--border);border-radius:8px;overflow:hidden;background:#fff}
.ykr .thumb img{display:block;width:100%;height:auto}
.ykr h3{margin:0;font-size:14px;display:flex;align-items:center;gap:8px}
.ykr .sw{width:16px;height:16px;border-radius:5px;border:1px solid var(--border);flex:none}
.ykr .cap{font-size:11.5px;color:var(--sub);text-align:center;margin-top:3px}
</style>"""


def build_yorumkart(env=None):
    m = json.loads((YORUMKART_DIR / "kartlar.json").read_text(encoding="utf-8"))
    kartlar = m["kartlar"]
    u = lambda f: esc(YORUMKART_URL + f)
    isim = lambda k, uz: esc(f"Riva-yorum-karti-{k['kod']}{uz}")
    cards = "".join(
        f"<div class='card'>"
        f"<h3><span class='sw' style='background:{esc(k['renk'])}'></span>{esc(k['ad'])}</h3>"
        f"<div class='yuz'>"
        f"<div><a class='thumb' href='{u(k['png_on'])}' target='_blank' rel='noopener' title='Büyük görmek için tıklayın'>"
        f"<img src='{u(k['onizleme'])}' alt='{esc(k['ad'])} yorum kartı ön yüz' loading='lazy'></a><div class='cap'>Ön · Türkçe</div></div>"
        f"<div><a class='thumb' href='{u(k['png_arka'])}' target='_blank' rel='noopener' title='Büyük görmek için tıklayın'>"
        f"<img src='{u(k['onizleme_arka'])}' alt='{esc(k['ad'])} yorum kartı arka yüz' loading='lazy'></a><div class='cap'>Arka · İngilizce</div></div>"
        f"</div><div class='btns'>"
        f"<a class='dl main' href='{u(k['matbaa'])}' download='{isim(k, '-matbaa.pdf')}'>⤓ Matbaa PDF</a>"
        f"<a class='dl' href='{u(k['pdf'])}' download='{isim(k, '.pdf')}'>⤓ PDF</a>"
        f"<a class='dl' href='{u(k['a4'])}' download='{isim(k, '-A4-4lu.pdf')}'>⤓ A4 · 4'lü</a>"
        f"<a class='dl' href='{u(k['png_on'])}' download='{isim(k, '-on.png')}'>⤓ PNG <small>ön</small></a>"
        f"<a class='dl' href='{u(k['png_arka'])}' download='{isim(k, '-arka.png')}'>⤓ PNG <small>arka</small></a>"
        f"</div></div>" for k in kartlar)
    body = (
        TVKART_CSS + YORUMKART_CSS +
        "<p class='lead'>Çıkışta <b>her misafire</b> verilen kart. Misafir QR'ı telefon kamerasıyla okutunca "
        "doğrudan Google'da otelimize yorum yazma ekranı açılır. Beş renk var; birini seçip basın. "
        "Görsele tıklayınca kart büyük açılır.</p>"
        f"<div class='ykr'>{cards}</div>"
        "<div class='grid2' style='margin-top:18px'>"
        "<div class='card'><h3>Matbaaya göndermek</h3>"
        "<p class='lead' style='margin-bottom:4px'>Seçtiğiniz rengin <b>Matbaa PDF</b> dosyasını gönderin; "
        "adedi yazın (öneri: 1.000 adet, ~2–3 aylık çıkış).</p>"
        "<dl class='spec'>"
        "<dt>Kesim boyu</dt><dd>A6 yatay · 148 × 105 mm</dd>"
        "<dt>Dosya</dt><dd>2 sayfa: ön (Türkçe) + arka (İngilizce); her yanda 3 mm taşma, kesim işaretli</dd>"
        "<dt>Baskı</dt><dd>çift yüz, 4 renk</dd>"
        "<dt>Kâğıt önerisi</dt><dd>350 g kuşe + mat selefon (QR parlamaz)</dd>"
        "<dt>Renk</dt><dd>RGB — matbaa CMYK'ya kendisi çevirir</dd>"
        "</dl></div>"
        "<div class='card'><h3>Ofis yazıcısında basmak</h3>"
        "<ol class='howto'><li><b>A4 · 4'lü</b> dosyasını açın; ölçek <b>%100 / Gerçek boyut</b>.</li>"
        "<li>Çift yüz (dupleks) seçin, <b>uzun kenardan çevir</b>.</li>"
        "<li>Kesik çizgilerden kesin — bir A4'ten dört kart çıkar.</li></ol></div></div>"
        "<div class='note'><b>Google kuralı:</b> yorum karşılığında indirim ya da hediye verilmez ve kart yalnız "
        "memnun misafire değil <b>herkese</b> verilir; aksi hâlde Google yorumları silebilir. QR, "
        "<b>rivaalsancak.com/yorum.html</b> adresine gider; Google bağlantısı değişirse yalnız o sayfa "
        "güncellenir, basılı kartlar geçerli kalır.</div>")
    return {"label": "Yorum Kartları", "count": len(kartlar), "count_label": "renk",
            "tone": "ok", "sub": "Google yorum kartı · QR · matbaa ve A4 PDF",
            "updated": now_str(),
            "html": PAGE("Pazarlama", "Google Yorum Kartları",
                         "Çıkışta her misafire: QR'ı okutan doğrudan Google'da yorum yazar", body)}

# ---------------------------------------------------------------- Günlük Rapor: Sabah notu verisi
# Sahibi (19–20.11.2026): rapor açılınca DÜN; en üstte "sabah notu" (mockup 2). Not sayfada JS ile, sekmelerin
# AYNI verisinden yazılır (tablo ne diyorsa not da onu der; gün değişince not da değişir). Sunucu yalnız
# sekmelerde olmayan gün bazlı rakamları verir: doluluk, tahsilat (ödeme türüne göre), indirim/iade, cari tahsilatı.
def gunluk_gun_verisi(env, start, today, fol):
    out = {}
    d = start
    while d <= today:
        out[d.isoformat()] = {"dolu": None, "tah": {}, "iade": [], "ctah": 0.0, "ctahn": 0}
        d += dt.timedelta(days=1)
    try:
        dol = gece_doluluk(env, start, today)
        for k in out:
            out[k]["dolu"] = dol.get(dt.date.fromisoformat(k), 0)
    except Exception:
        pass
    for r in fol:
        k = str(r.get("FOLIODATE") or "")[:10]
        if k not in out:
            continue
        if r.get("DEPTTYPENAME") == "PAYMENT":
            m = (r.get("DEPNAME") or "Diğer").strip()
            out[k]["tah"][m] = round(out[k]["tah"].get(m, 0) + abs(num(r.get("TOTAL"))), 2)
        if r.get("TYPE") in ("Discount", "Rebate"):
            out[k]["iade"].append({"room": r.get("ROOMNO") or "", "guest": (r.get("GUESTNAMES") or "")[:28],
                                   "type": r.get("TYPE"), "total": round(num(r.get("TOTAL")), 2),
                                   "user": r.get("USERFULLNAME") or ""})
    try:   # cari tahsilatı: 120 alıcılar hesabına alacak (fatura hariç)
        for r in E.fetch_account_statement("120", start.isoformat(), today.isoformat(), env=env):
            k = str(r.get("RECEIPTDATE") or "")[:10]
            if k in out and num(r.get("LOCALCREDIT")) > 0 and str(r.get("DOCTYPE") or "") != "Fatura":
                out[k]["ctah"] = round(out[k]["ctah"] + num(r.get("LOCALCREDIT")), 2)
                out[k]["ctahn"] += 1
    except Exception:
        for k in out:
            out[k]["ctah"] = None
    return out


def build_gunluk(env):
    today = dt.date.today()
    start = today - dt.timedelta(days=30)          # son 31 gün (gün/hafta/ay kapsamı için)
    changes = E.fetch_room_changes(start.isoformat(), today.isoformat(), env=env)
    rez_ids = {c["rez_id"] for c in changes if c["rez_id"]}
    # NEDEN = sadece "Oda Notu" (RES_NOTE tür 1005) — ALLNOTES DEĞİL (o Channel/Checkin
    # notlarını karıştırıp yanlış gösteriyordu). Boşsa müdür açıklaması beklenir.
    notes = E.fetch_room_notes(rez_ids, env=env) if rez_ids else {}
    resdates = E.fetch_res_dates(rez_ids, env=env) if rez_ids else {}
    deps = E.fetch_departed_range(start.isoformat(), today.isoformat(), env=env)
    owed = open_balances(env)
    cari = cari_receivables(env)

    days = OrderedDict()
    d = start
    while d <= today:
        days[d.isoformat()] = {"rc": [], "dep": [], "sales": []}
        d += dt.timedelta(days=1)
    for c in changes:
        day = c["when"][:10]
        if day not in days:
            continue
        gin, cout, cintime = resdates.get(c["rez_id"], ("", "", ""))
        # Check-in'den ÖNCE yapılan oda değişimi = resepsiyonun oda ATAMASI (sorun değil) →
        # gösterme. Sadece misafir giriş yaptıktan SONRA (konaklamanın ortası) yapılanları
        # göster — asıl incelenecekler bunlar. cintime yoksa (giriş yapılmamış) = atama → gizle.
        if not cintime or c["when"] < f"{gin} {cintime}":
            continue
        days[day]["rc"].append({"when": c["when"], "guest": c["guest"],
                                "from": c["from_room"], "to": c["to_room"],
                                "user": c["user"], "reason": notes.get(c["rez_id"], ""),
                                "gin": gin, "cout": cout, "cintime": cintime, "rez": c["rez_id"]})
    dep_ids = {r.get("rez_id") for r in deps if r.get("rez_id")}
    deptimes = E.fetch_res_times(dep_ids, env=env) if dep_ids else {}
    for r in deps:
        if is_internal_folio(r.get("guest")):          # BOARD/CASH FOLIO iç kayıt — gösterme
            continue
        day = str(r.get("checkout") or "")[:10]
        if day in days:
            rez = str(r.get("rez_id") or "")
            gin, gintime, cout, couttime = deptimes.get(rez, ("", "", "", ""))
            days[day]["dep"].append({"room": r.get("room") or "",
                                     "guest": (r.get("guest") or "")[:40],
                                     "kanal": (r.get("agency") or "")[:22], "rez": rez,
                                     "gin": gin, "gintime": gintime,
                                     "cout": cout, "couttime": couttime})

    # --- Oda Satış Fiyatları: o gün GİRİŞ yapan odalar, ort. gece fiyatı (TL) + ödeme türü ---
    # Fiyat = AVERAGENIGHTPRICE × CURRENCYRATE (rezervasyon parası → TL). Ödeme türü folyodan
    # (PAYMENTTYPENAME hep boş); folyoda 'Cash' varsa nakit. T-folyo/sanal odalar (numerik değil) elenir.
    arr = E.fetch_reservations_between("CHECKIN", start.isoformat(), today.isoformat(), env=env)
    fol = E.fetch_folio(start.isoformat(), today.isoformat(), env=env)
    pay_map = {}
    for r in fol:
        if r.get("DEPTTYPENAME") == "PAYMENT":
            m = (r.get("DEPNAME") or "").strip()
            if m:
                pay_map.setdefault(str(r.get("RESID")), set()).add(m)
    SKIP_STATES = {"Cancelled", "Deleted", "No Show", "Option"}
    for a in arr:
        if str(a.get("RESSTATE")) in SKIP_STATES:
            continue
        room = str(a.get("ROOMNO") or "").strip()
        if not room[:1].isdigit():                 # T-folyo/sanal oda → ele
            continue
        day = str(a.get("CHECKIN") or "")[:10]
        if day not in days:
            continue
        kur = num(a.get("CURRENCYRATE")) or 1
        avg = round(num(a.get("AVERAGENIGHTPRICE")) * kur, 2)   # TL (rezervasyon parası × kur)
        methods = sorted(pay_map.get(str(a.get("RESID")), set()))
        cash = any(("cash" in m.lower() or "nakit" in m.lower()) for m in methods)
        agency = (a.get("AGENCY") or "").strip()
        direct = _is_direct_agency(agency)        # kırmızı sadece Walk-in/Telefon/acentasız
        liste = satis_liste_fiyati(a)             # fiyat listesine göre olması gereken (27.10.2026)
        alt = (liste - SATIS_PAYI) if liste else SATIS_MIN_FIYAT
        days[day]["sales"].append({
            "room": room, "guest": (a.get("GUESTNAMES") or "")[:34], "agency": agency[:22],
            "night": a.get("NIGHT") or "", "avg": avg, "pay": methods, "cash": cash, "liste": liste,
            "low": (0 < avg < alt) and direct, "rez": str(a.get("RESID") or "")})
    for dd in days.values():
        # en üstte listenin altında + NAKİT (en riskli), sonra diğer işaretliler, sonra ucuzdan pahalıya
        dd["sales"].sort(key=lambda s: (not (s["low"] and s["cash"]), not (s["low"] or s["cash"]), s["avg"]))
    ob = [{"rezid": str(r.get("RESID") or ""), "room": r.get("ROOMNO") or "",
           "guest": (r.get("GUESTNAMES") or "")[:34], "agency": (r.get("AGENCY") or "")[:16],
           "left": bool(r.get("_left")), "borc": round(fbal(r), 2),
           "ci": str(r.get("CHECKINDATE") or "")[:10], "co": str(r.get("CHECKOUTDATE") or "")[:10]} for r in owed]
    cr = [{"kod": r.get("CODE") or "", "name": (r.get("NAME") or "")[:36],
           "alacak": round(num(r.get("LOCALBALANCE")), 2)} for r in cari]

    # oda listesi (problem panelinde aramalı seçim için) — son 45 günün doluluğundaki
    # fiziksel (numerik) odalar + oda değişimlerindeki odalar.
    rooms = set()
    try:
        for x in E.fetch_room_calendar((today - dt.timedelta(days=45)).isoformat(),
                                       today.isoformat(), env=env, raw=True):
            rn = str(x.get("ROOMNO") or "").strip()
            if rn.isdigit():
                rooms.add(rn)
    except Exception:
        pass
    for c in changes:
        for rm in (c["from_room"], c["to_room"]):
            if str(rm).isdigit():
                rooms.add(str(rm))
    rooms = sorted(rooms, key=lambda s: int(s))

    # --- Eksik Bilgiler sekmesi: son EKSIK_GUNLUK_GUN günde girişi yapılmış ve telefonu/kimliği
    # ŞU AN hâlâ eksik kayıtlar (kurallar guest_gaps'te). Sekme seçilen gün + önceki günü gösterir.
    # Bu ek veri alınamazsa Günlük Rapor yine çıkar; sekme "alınamadı" der (eksik=None).
    try:
        eks_frm = today - dt.timedelta(days=EKSIK_GUNLUK_GUN)
        eks_rows = [r for r in E.fetch_res_guests(
            [{"Column": "CHECKIN", "Operator": ">=", "Value": f"{eks_frm} 00:00:00"},
             {"Column": "CHECKIN", "Operator": "<=", "Value": f"{today} 23:59:59.999"}], env=env)
            if r.get("RESSTATE") in ("InHouse", "CheckOut")]
        eks = [x for x in guest_gaps(eks_rows)[0] if x["phone"] is not None or x["ident"]]
        eks_who = E.fetch_checkin_users([x["rez"] for x in eks], env=env)
        eksik = [{"day": x["ci"].isoformat() if x["ci"] else "",
                  "ci": x["ci"].isoformat() if x["ci"] else "",
                  "co": x["co"].isoformat() if x["co"] else "",
                  "room": x["room"], "guest": x["guest"][:40], "pax": x["pax"],
                  "agency": x["agency"][:16], "inhouse": x["state"] == "InHouse",
                  "gaps": gap_texts(x), "user": eks_who.get(x["rez"], ("", ""))[0],
                  "utime": eks_who.get(x["rez"], ("", ""))[1], "rez": x["rez"]} for x in eks]
    except Exception:
        eksik = None

    dun = tr_bugun() - dt.timedelta(days=1)      # sabah açılınca DÜN (sahibi 19.11.2026)
    try:
        gunv = gunluk_gun_verisi(env, start, today, fol)
    except Exception:
        gunv = {}
    data = {"today": today.isoformat(), "dun": dun.isoformat(), "bugun": tr_bugun().isoformat(), "gunv": gunv,
            "days": days, "openbal": ob, "cari": cr,
            "rooms": rooms, "pricemin": SATIS_MIN_FIYAT, "eksik": eksik}
    skeleton = (
        "<section class='sb'><div class='sb-hd'><div><div class='sb-eb' id='sbEb'>Günlük rapor · sabah notu</div>"
        "<h2 id='sbTitle'>—</h2></div>"
        "<div class='topbar'><div class='daynav'>"
        "<button id='dprev' title='önceki gün' aria-label='önceki gün'>‹</button>"
        "<div class='cur' id='curday'>—</div>"
        "<button id='dnext' title='sonraki gün' aria-label='sonraki gün'>›</button></div>"
        "<select id='scopeSel' title='tarih kapsamı' aria-label='tarih kapsamı'>"
        "<option value='day'>Bu gün</option><option value='week'>Son 1 hafta</option>"
        "<option value='month'>Son 1 ay</option><option value='year'>Son 1 yıl</option></select>"
        "</div></div>"
        "<div class='sb-grid'><div id='sbText'></div><div class='sb-boxes' id='sbBoxes'></div></div></section>"
        "<div class='tabs' id='tabs'></div>"
        "<div id='panels'></div>")
    body = (GUNLUK_CSS + skeleton + "<script>window.__GUNLUK__="
            + json.dumps(data, ensure_ascii=False, default=str) + ";</script>" + GUNLUK_JS)
    n_open = len(ob)
    left = sum(1 for r in ob if r["left"])
    return {"label": "Günlük Rapor", "count": n_open, "count_label": "açık bakiye",
            "tone": "bad" if (n_open or left) else "ok",
            "sub": f"günlük defter · {tr_g(today)} · {len(changes)} oda değişimi (31g)",
            "updated": now_str(),
            "html": PAGE(None, "Günlük Rapor",
                         f"gün seçici + oda değişimleri, açık bakiye/cari, problemler, yorumlar", body)}


# --------------------------------------------------------------------------- Eksik Bilgiler
EKSIK_CIKIS_GUN = 3     # "eksik bilgiyle çıkanlar" listesi: son kaç gün (hafta sonu da kapsansın)
EKSIK_GUNLUK_GUN = 7    # Günlük Rapor "Eksik Bilgiler" sekmesi: son kaç günün girişleri gömülür


# Bu kanallar telefon yerine yer tutucu gönderiyor: Expedia '111111111111', Tatil Budur '0',
# Jolly Tur '+' (20.10.2026 verisi). Maskeli numarada gerçeği ayırt edilemez (masked_phone).
FAKE_PHONE_CHANNELS = ("EXPEDIA", "TATIL BUDUR", "JOLLY")


def masked_phone(p):
    """Elektra ~21–27.10.2026 arası telefon/e-postayı API'de MASKELEMEYE başladı: dolu her
    değer (eski kayıtlar dahil) aynı '***0X***' olarak geliyor, boş olan boş. Yani "girilmiş
    mi" görülür, numaranın gerçek mi kanal yer tutucusu mu olduğu GÖRÜLMEZ."""
    s = str(p or "").strip()
    return len(s) > 6 and s.startswith("***") and s.endswith("***")


def phone_ok(p):
    """Görülebilen gerçek bir telefon numarası mı? Kanal yer tutucuları SAYILMAZ (bkz.
    FAKE_PHONE_CHANNELS). Kural: en az 7 rakam ve hepsi aynı rakam değil. Maskeli değer
    burada False — onu guest_gaps ayrıca değerlendirir."""
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    return len(d) >= 7 and len(set(d)) > 1


# Elektra ~09.11.2026'dan beri TC/pasaport no'yu da telefon gibi '***0X***' maskeliyor: maskeli =
# "girilmiş" sayılır (kontrol hanesi artık doğrulanamaz). Asıl açık — odada kaydı HİÇ olmayan kişi —
# kayıt sayısından çıktığı için maskeden etkilenmez.
def tckn_ok(s):
    """Geçerli TC kimlik no mu: 11 hane, 0 ile başlamaz, iki kontrol hanesi tutar
    (yabancılara verilen 99… YKN de aynı algoritmayla geçer)."""
    s = str(s or "").strip()
    if len(s) != 11 or not s.isdigit() or s[0] == "0":
        return False
    d = [int(c) for c in s]
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def passport_ok(s):
    """Pasaport / yabancı kimlik no: en az 5 harf-rakam ve hepsi aynı karakter değil."""
    a = "".join(ch for ch in str(s or "") if ch.isalnum()).upper()
    return len(a) >= 5 and len(set(a)) > 1


def _guest_name(g):
    return f"{g.get('GUESTNAME') or ''} {g.get('GUESTSURNAME') or ''}".strip() or "isimsiz misafir"


def guest_gaps(rows):
    """Misafir-başı satırları (E.fetch_res_guests) rezervasyona toplar ve her birinin
    telefon / kimlik eksiğini çıkarır. Sanal folyo (T…), no-show (NSNSNS…) ve BOARD/CASH
    FOLIO iç kayıtları elenir. Dönüş: (kayıtlar, toplam_rezervasyon). Her kayıtta:
      phone — None = tamam; yoksa bulunan sahte numaralar ([] = hiç girilmemiş). Odada kaç
              kişi olursa olsun TEK numara yeter: rezervasyon sahibinin (CONTACTPHONE) ya da
              odadaki herhangi bir misafirin (GUESTPHONE) — sahibin kuralı (20.10.2026).
              Maskeli numara "girilmiş" sayılır; ama tek kanıt maskeli numaraysa ve kanal yer
              tutucu gönderenlerdense (FAKE_PHONE_CHANNELS) phone_unsure=True: elle bakılmalı.
      ident — kimlik sorunları ([] = tamam). Kimlik HER KİŞİ için gerekir (polise kimlik
              bildirimi): her misafir kaydında geçerli TC ya da pasaport no olmalı VE kayıt
              sayısı odadaki kişi sayısına (yetişkin + çocuk + bebek) yetmeli. Asıl açık
              ikincisi: 14 günde 9 odada bir kişi hiç kaydedilmemişti (27.10.2026)."""
    groups = OrderedDict()
    for r in rows:
        if not str(r.get("ROOMNO") or "").isdigit() or is_internal_folio(r.get("GUESTNAMES")):
            continue
        groups.setdefault(str(r.get("RESID")), []).append(r)
    out = []
    for rid, gs in groups.items():
        first = min(gs, key=lambda g: g.get("GUESTNO") or 99)
        vals = [v for g in gs for v in (g.get("CONTACTPHONE"), g.get("GUESTPHONE")) if str(v or "").strip()]
        agency = (first.get("AGENCY") or "").strip()
        phone, unsure = None, False
        if not any(phone_ok(v) for v in vals):
            if any(masked_phone(v) for v in vals):
                unsure = any(c in agency.upper().replace("İ", "I") for c in FAKE_PHONE_CHANNELS)
            else:
                phone = sorted({str(v).strip() for v in vals})
        # Misafir kaydı hiç olmayan rezervasyon da GUESTID'si boş TEK satır döner → sayma.
        recs = list({g["GUESTID"]: g for g in gs if g.get("GUESTID")}.values())
        ident = [f"{_guest_name(g)}: " + ("TC no hatalı" if str(g.get("GUESTTCKN") or "").strip()
                                          else "kimlik no yok")
                 for g in recs if not (tckn_ok(g.get("GUESTTCKN")) or passport_ok(g.get("GUESTPASSPORT"))
                                       or masked_phone(g.get("GUESTTCKN")) or masked_phone(g.get("GUESTPASSPORT")))]
        pax = int(num(first.get("ADULT")) + num(first.get("TCHD")) + num(first.get("BABY")))
        if len(recs) < pax:
            ident.insert(0, f"{pax - len(recs)} kişinin misafir kaydı yok ({pax} kişi, {len(recs)} kayıt)")
        names = first.get("GUESTNAMES") or " / ".join(_guest_name(g) for g in recs)
        out.append({"rez": rid, "room": str(first.get("ROOMNO")), "guest": names, "pax": pax,
                    "agency": agency, "ci": pdate(first.get("CHECKIN")), "co": pdate(first.get("CHECKOUT")),
                    "phone": phone, "phone_unsure": unsure, "ident": ident,
                    "state": first.get("RESSTATE")})
    return out, len(groups)


def gap_texts(x):
    """Bir guest_gaps kaydının eksikleri düz metin satırları olarak (📞 telefon, 🪪 kimlik).
    Eksik Bilgiler sayfası ve Günlük Rapor sekmesi aynı metni kullanır."""
    g = []
    if x["phone"] is not None:
        g.append("📞 telefon yok" + (f" (gerçek numara değil: {', '.join(x['phone'])[:30]})"
                                     if x["phone"] else ""))
    return g + [f"🪪 {s}" for s in x["ident"]]


def build_eksik(env):
    """Eksik Bilgiler — resepsiyonun Elektra'ya girmeyi unuttuğu bilgiler; otel müdürü
    kontrol eder. İki kontrol (sahibin isteği: e-posta GEREKMEZ): TELEFON (odada tek numara
    yeter) ve KİMLİK (her kişi) — kurallar guest_gaps'te. Üstte konaklayanlar (misafir hâlâ
    otelde → hemen tamamlanabilir), altta son EKSIK_CIKIS_GUN günde eksik bilgiyle çıkanlar.
    Her kayıtta girişi yapan personel (rezervasyon log'undaki Check-In) gösterilir."""
    today = dt.date.today()
    inhouse, n_in = guest_gaps(E.fetch_res_guests(
        [{"Column": "RESSTATE", "Operator": "=", "Value": "InHouse"}], env=env))
    frm = today - dt.timedelta(days=EKSIK_CIKIS_GUN)
    departed, _ = guest_gaps(E.fetch_res_guests(
        [{"Column": "CHECKOUT", "Operator": ">=", "Value": f"{frm} 00:00:00"},
         {"Column": "CHECKOUT", "Operator": "<=", "Value": f"{today} 23:59:59.999"},
         {"Column": "RESSTATE", "Operator": "=", "Value": "CheckOut"}], env=env))
    tel = [x for x in inhouse if x["phone"] is not None]
    kim = [x for x in inhouse if x["ident"]]
    unsure = sorted((x for x in inhouse if x["phone_unsure"]), key=lambda x: int(x["room"]))
    left = [x for x in departed if x["phone"] is not None or x["ident"]]
    who = E.fetch_checkin_users([x["rez"] for x in tel + kim + left], env=env)
    tel.sort(key=lambda x: (x["ci"] or today, int(x["room"])))
    kim.sort(key=lambda x: (x["ci"] or today, int(x["room"])))
    left.sort(key=lambda x: (-(x["co"] or today).toordinal(), int(x["room"])))   # en yeni çıkış üstte

    def stay(x):
        return f"{tr_g(x['ci'])} → {tr_g(x['co'])}"

    def who_cell(x):
        u, t = who.get(x["rez"], ("", ""))
        if not u:
            return "<td>—</td>"
        return (f"<td style='white-space:nowrap'><span class='who'>{esc(u)}</span> "
                f"<span style='color:var(--sub);font-size:11.5px'>{esc(t)}</span></td>")

    def fake_note(x):
        return f"gerçek numara değil: {', '.join(x['phone'])[:30]}" if x["phone"] else ""

    def since(x):
        d = (today - x["ci"]).days if x["ci"] else 0
        if d <= 0:
            return "<td>bugün geldi</td>"
        return f"<td class='{'miss' if d >= 2 else ''}'>{d} gündür</td>"

    def head(x):
        return (f"<td><b>{esc(x['room'])}</b></td><td>{esc(x['guest'][:40])}</td>"
                f"<td class='r'>{esc(x['pax'] or '—')}</td><td>{esc(x['agency'][:16])}</td>"
                f"<td style='white-space:nowrap'>{stay(x)}</td>")

    def table(rows, last_th):
        last = f"<th>{last_th}</th>" if last_th else ""
        return ("<div style='overflow-x:auto'><table><tr><th>Oda</th><th>Misafir</th>"
                "<th class='r'>Kişi</th><th>Kanal</th><th>Giriş → Çıkış</th><th>Eksik</th>"
                f"<th>Girişi yapan</th>{last}<th>Rez No</th></tr>{rows}</table></div>")

    eksik_oda = {x["rez"] for x in tel + kim}
    stats = (stat(len(tel), "konaklayan odada telefon yok", "bad" if tel else "ok")
             + stat(len(kim), "konaklayan odada kimlik eksik", "bad" if kim else "ok")
             + stat(n_in, "konaklayan oda")
             + stat(len(left), f"son {EKSIK_CIKIS_GUN} günde eksik bilgiyle çıkış",
                    "bad" if left else "ok"))
    fresh = ("<div style='background:#fef3c7;border:1px solid #fde68a;color:#92400e;"
             "padding:9px 13px;border-radius:9px;margin:0 0 12px;font-size:12.5px'>"
             f"⏱ Bu sayfadaki veriler <b>{now_str()}</b> itibarıyladır. Bu saatten sonra "
             "tamamlanan bilgiler bir sonraki güncellemede listeden düşer.</div>")
    how = ("Rez No'ya tıkla → Elektra açılır (numara kopyalanır, Rez Id kutusuna yapıştır, "
           "satıra çift tıkla).")

    tel_html = "<h2>📞 Telefonu girilmemiş konaklayan misafirler</h2>"
    if tel:
        notes = any(x["phone"] for x in tel)      # görülebilen sahte numara yoksa sütun gizli
        tel_html += ("<p class='lead'>Bu odalarda kalanların <b>hiçbirinin</b> telefonu Elektra'da yok. "
                     "Odada 2–3 kişi kalıyorsa <b>tek numara yeterli</b>: rezervasyonu yapan kişinin ya da "
                     "odadaki misafirlerden birinin. Misafir hâlâ otelde — numarasını alıp misafir kartına "
                     f"girin. {how}</p>"
                     + table("".join(f"<tr>{head(x)}{since(x)}{who_cell(x)}"
                                     + (f"<td style='color:var(--sub);font-size:12px'>{esc(fake_note(x))}</td>"
                                        if notes else "")
                                     + f"<td>{rez_link(x['rez'])}</td></tr>" for x in tel),
                             "Not" if notes else None))
    else:
        tel_html += empty_ok("Konaklayan her odada en az bir telefon numarası kayıtlı.")
    if unsure:
        tel_html += ("<details style='margin:-8px 0 18px'><summary style='cursor:pointer;font-weight:700'>"
                     f"Elle kontrol edin: kanal numarası doğrulanamıyor ({len(unsure)})</summary>"
                     "<p class='lead' style='margin-top:8px'>Bu kanallar telefon yerine sahte numara "
                     "gönderiyor (Expedia <i>111111111111</i>, Tatil Budur <i>0</i>). Elektra numaraları "
                     "artık gizli (<i>***0X***</i>) gönderdiği için gerçek mi sahte mi buradan ayırt "
                     f"edilemiyor — Elektra'da açıp bakın; sahteyse misafirin numarasını girin. {how}</p>"
                     "<div style='overflow-x:auto'><table><tr><th>Oda</th><th>Misafir</th><th>Kanal</th>"
                     "<th>Giriş → Çıkış</th><th>Rez No</th></tr>"
                     + "".join(f"<tr><td><b>{esc(x['room'])}</b></td><td>{esc(x['guest'][:40])}</td>"
                               f"<td>{esc(x['agency'][:16])}</td><td style='white-space:nowrap'>{stay(x)}</td>"
                               f"<td>{rez_link(x['rez'])}</td></tr>" for x in unsure)
                     + "</table></div></details>")

    kim_html = "<h2>🪪 Kimlik bilgisi eksik konaklayan misafirler</h2>"
    if kim:
        kim_html += ("<p class='lead'>Polise kimlik bildirimi için odada kalan <b>her kişinin</b> (çocuklar "
                     "dahil) Elektra'da misafir kaydı ve geçerli <b>TC kimlik</b> ya da <b>pasaport</b> numarası "
                     "olmalı. <i>“Kaydı yok”</i> = odadaki kişi sayısı kayıtlı misafirden fazla: eksik kişiyi "
                     f"kaydedin, kişi sayısı yanlışsa rezervasyonda düzeltin. {how}</p>"
                     + table("".join(f"<tr>{head(x)}{since(x)}{who_cell(x)}"
                                     f"<td>{'<br>'.join(esc(s) for s in x['ident'])}</td>"
                                     f"<td>{rez_link(x['rez'])}</td></tr>" for x in kim), "Sorun"))
    else:
        kim_html += empty_ok("Konaklayan herkesin kimlik kaydı tam.")

    t_tel, t_kim = Counter(), Counter()
    for x in tel + [x for x in left if x["phone"] is not None]:
        t_tel[who.get(x["rez"], ("", ""))[0] or "bilinmiyor"] += 1
    for x in kim + [x for x in left if x["ident"]]:
        t_kim[who.get(x["rez"], ("", ""))[0] or "bilinmiyor"] += 1
    users = sorted(set(t_tel) | set(t_kim), key=lambda u: -(t_tel[u] + t_kim[u]))
    if users:
        chips = " ".join(
            f"<span class='who' style='margin:0 6px 6px 0'>{esc(u)}: "
            + " · ".join(p for p in ((f"📞 {t_tel[u]}" if t_tel[u] else ""),
                                     (f"🪪 {t_kim[u]}" if t_kim[u] else "")) if p)
            + "</span>" for u in users)
        tally_html = ("<h2>Girişinde eksik bırakılan kayıtlar — personele göre</h2>"
                      f"<p class='lead'>Konaklayanlar + son {EKSIK_CIKIS_GUN} günde çıkanlar; girişi "
                      "(check-in) kim yaptıysa ona yazılır. 📞 telefon · 🪪 kimlik.</p>"
                      f"<div style='display:flex;flex-wrap:wrap'>{chips}</div>")
    else:
        tally_html = ""

    if left:
        def gaps(x):
            return "<br>".join(esc(s) for s in gap_texts(x))
        ltrs = "".join(
            f"<tr><td><b>{esc(x['room'])}</b></td><td>{esc(x['guest'][:40])}</td>"
            f"<td>{esc(x['agency'][:16])}</td><td style='white-space:nowrap'>{stay(x)}</td>"
            f"<td>{gaps(x)}</td>{who_cell(x)}<td>{rez_link(x['rez'])}</td></tr>" for x in left)
        left_html = ("<details style='margin-top:22px'><summary style='cursor:pointer;font-weight:700'>"
                     f"Son {EKSIK_CIKIS_GUN} günde bilgisi eksik çıkış yapanlar ({len(left)})"
                     "</summary><p class='lead' style='margin-top:8px'>Misafir gitti; kimlik bilgisi "
                     "giriş belgesinden, telefon kanal ya da rezervasyon belgesinden bulunursa yine de "
                     "girilebilir. Asıl amaç hangi girişlerde bilginin alınmadığını görmek.</p>"
                     "<div style='overflow-x:auto'><table><tr><th>Oda</th><th>Misafir</th><th>Kanal</th>"
                     "<th>Giriş → Çıkış</th><th>Eksik</th><th>Girişi yapan</th><th>Rez No</th></tr>"
                     + ltrs + "</table></div></details>")
    else:
        left_html = ""

    note = ("<div class='note'>Kaynak: Elektra <b>QA_HOTEL_RESERVATION_GUEST</b> (her misafir ayrı "
            "satır). <b>Telefon:</b> misafirin kendi telefonu + rezervasyonun iletişim telefonu. Elektra "
            "Ekim 2026 sonundan beri numaraları gizli (<i>***0X***</i>) gönderiyor: gizli numara "
            "\"girilmiş\" sayılır; sahte numara gönderen kanallarda (Expedia, Tatil Budur, Jolly) ise "
            "\"elle kontrol\" listesine düşer. "
            "<b>Kimlik:</b> Elektra Kasım 2026'dan beri TC / pasaport numaralarını da gizli gönderiyor: gizli "
            "numara \"girilmiş\" sayılır, boş olan eksiktir; açıktaki TC kontrol haneleriyle doğrulanır, pasaport "
            "(en az 5 karakter). Kişi sayısı = yetişkin + çocuk + bebek. Girişi yapan = rezervasyon "
            "geçmişindeki Check-In işlemini yapan kullanıcı. No-show ve sanal folyolar hariç.</div>")
    sub = (f"{len(tel)} odada telefon, {len(kim)} odada kimlik eksik · {n_in} konaklayan oda"
           + (f" · son {EKSIK_CIKIS_GUN} günde {len(left)} eksik çıkış" if left else ""))
    return {"label": "Eksik Bilgiler", "count": len(eksik_oda), "count_label": "eksik oda",
            "tone": "bad" if eksik_oda else "ok", "sub": sub, "updated": now_str(),
            "html": PAGE("Resepsiyon — Veri Kontrolü", "Eksik Bilgiler",
                         "Elektra'ya girilmemiş misafir bilgileri · telefon + kimlik",
                         f"<div class='stats'>{stats}</div>{fresh}{tel_html}{kim_html}{tally_html}"
                         f"{left_html}{note}{REZ_COPY_JS}")}


# --------------------------------------------------------------------------- Gelir-Gider
# 20.11.2026 (sahibin isteği): "satışlardan bu ay bankaya ne girmiş, neye para harcanmış".
# KAYNAK: Elektra MUHASEBE — 102 Bankalar altındaki her fiş satırı (hesap ekstresi proc'u).
# Muhasebeci banka hareketlerini her gün "DD.MM.YYYY Günlük Banka İşlemleri" fişiyle
# işliyor; her satırın KARŞI HESABI (CROSSACCOUNT) paranın nereden geldiğini / nereye
# gittiğini söyler (108 POS, 120 acenta, 335 maaş, 361 SGK, 320 tedarikçi …).
# Tuzaklar (canlı veride görüldü):
#  • Proc tek çağrıda EN FAZLA 1000 satır döner → 10 günlük parçalar, dolarsa ikiye böl.
#  • Kendi hesaplarımız arası virman (Akbank → Ziraat vergi için) iki bacaklıdır: ATLA.
#  • "Para Yatırma" (kasadan bankaya nakit) muhasebede Akbank EURO hesabı karşılık
#    gösterilerek işleniyor; "Para Çekme" (ATM) Akbank DOLAR karşılığıyla. Bunlarda yalnız
#    TL hesabındaki bacağı say (EUR/USD bacağı aynı paranın öbür yüzü).
#  • 195 "İş avansı" = sahibin banka kartıyla yapılan harcamalar (Google Ads, yakıt,
#    market…) — açıklamadan kalemlendirilir.
#  • Ters işlem (TERS İŞLEM) aynı kalemde netleşir; kalem toplamları NET'tir.
GG_AY = 6                                    # sayfada kaç ay


def _banka_satirlari(env, frm, to):
    """102 altındaki fiş satırları [frm, to]. 1000 satır sınırına takılmasın diye böler."""
    out, d = [], frm
    while d <= to:
        e = min(to, d + dt.timedelta(days=9))
        rows = E.fetch_account_statement("102", d.isoformat(), e.isoformat(), env=env) or []
        if len(rows) >= 1000 and e > d:          # sınır doldu: aralığı küçült
            mid = d + (e - d) // 2
            out += _banka_satirlari(env, d, mid) + _banka_satirlari(env, mid + dt.timedelta(days=1), e)
        else:
            out += rows
        d = e + dt.timedelta(days=1)
    return out


# (anahtar kelimeler, kalem) — ilk eşleşen kazanır. Açıklamalar banka ekstresinden
# geldiği için kısaltmalı/ASCII olabilir; _tr_has büyük harf + Türkçe İ/I ile karşılaştırır.
GG_TEDARIK = [  # 320/329 tedarikçi adı ya da açıklaması
    (("BOOKING", "EXPEDIA", "AGODA", "HOTELBEDS", "TRIVAGO", "TRIP.COM", "TRIPADVISOR"), "OTA komisyonları"),
    (("GEDİZ", "GEDIZ", "ELKT. PERK"), "Elektrik"),
    (("DOĞALGAZ", "DOGALGAZ", "İZMİRGAZ", "IZMIRGAZ"), "Doğalgaz"),
    (("İZSU", "IZSU"), "Su"),
    (("TTNET", "TURKCELL", "TELEKOM", "VODAFONE", "TELSAM", "SUPERONLINE"), "Telefon & internet"),
    (("BİLSA", "BILSA"), "Bilsa"),
    (("ÇAMAŞIR", "CAMASIR", "YIKAMA", "ÜTÜLEME"), "Çamaşırhane"),
    (("SİGORTA", "SIGORTA"), "Sigorta"),
    (("TAMİR", "TAMIR", "TADİLAT", "TADILAT", "KLİMA", "KLIMA", "KOMBİ", "KOMBI", "KAZAN", "SERAMİK",
      "SERAMIK", "YAPI", "BOYA", "TESİSAT", "TESISAT", "ASANSÖR", "ASANSOR", "ELEKTRİK ELEKTRONİK",
      "ELEKTRIK ELEKTRONIK", "UYDU", "REMOTE", "İLAÇLAMA", "ILACLAMA", "BAKIM", "KİLİT", "KILIT",
      "HIRDAVAT", "NALBUR", "YANGIN", "ARITMA", "REÇİNE", "JENERATÖR", "JENERATOR"), "Bakım & onarım"),
    (("İŞ SAĞLIĞI", "IS SAGLIGI", "DESTEK HİZMET", "DESTEK HIZMET", "DANIŞMANLIK", "DANISMANLIK",
      "MÜŞAVİR", "MUSAVIR", "HUKUK", "AVUKAT", "NOTER", "PROJE BEDEL", "NAKLİYE", "NAKLIYE", "HAMAL",
      "İŞLETME DESTEK", "ISLETME DESTEK", "LOJİSTİK", "KARGO"),
     "Hizmet alımı (İSG, danışman…)"),
    (("TEKSTİL", "TEKSTIL", "HOTELLIFE", "MOBİLYA", "MOBILYA", "AVANSAS", "OFİS", "OFIS"),
     "Otel malzemesi & demirbaş"),
    (("MÜZİK", "MUZIK", "MESAM", "MSG", "BİRLİĞİ", "BIRLIGI", "ODASI", "ÜYELİK", "UYELIK", "DERNEĞİ"),
     "Aidat, lisans & üyelik"),
    (("METRO", "GIDA", "NESTLE", "MARKET", "MANDIRA", "KASAP", "FIRIN", "MANAV", "SÜT ", "BALIK",
      "ŞARKÜTERİ", "SARKUTERI", "YUMURTA", "KAHVALTI", "KAHVATILIK", "KAHVATLIK", "KAHVE", "PEYNİR"),
     "Gıda & market"),
    (("TEMZ", "TEMİZLİK", "TEMIZLIK", "AMBALAJ", "KİMYA", "KIMYA", "KALIPSO"), "Temizlik malzemesi"),
]
# 195 İş avansı = sahibin banka kartı / avans hesabı. İşletme gideri olduğu açık olanlar
# (reklam, yazılım, bakım-onarım faturası…) kendi kalemine; geri kalanı tek kalemde,
# alt kırılımla ("Sahip kartı & iş avansı").
GG_KART_ISLETME = [
    (("GOOGLE*ADS", "GOOGLE ADS", "FACEBK", "FACEBOOK", "META PLATF", "INSTAGRAM"), "Reklam"),
    (("ANTHROPIC", "GOOGLE CLOUD", "GOOGLE*ONE", "GOOGLE *GOOGLE", "LOKIPROXY", "OPENAI", "MICROSOFT",
      "ADOBE", "GITHUB", "CANVA", "ZOHO", "NATRO", "CLOUDFLARE", "DEFREITAS"), "Yazılım & abonelik"),
]
GG_KART_ALT = [
    (("PARA ÇEKME", "PARA CEKME"), "nakit çekim"),
    (("VERGI-", "VERGİ", "HARÇ", "HARC"), "vergi & harç (şahsi)"),
    (("TANKAR", "OPET", "SHELL", "PETROL", "AKARYAKIT", "TOTALENERGIES", "AYTEMIZ", "OTOYOL", "HGS"),
     "araç & yakıt"),
    (("MIGROS", "MİGROS", "CARREFOUR", "MARKET", "MANDIRA", "MANAV", "KASAP", "BALIK", "GIDA", "FIRIN"),
     "market & gıda"),
    (("HEPSIPAY", "HEPSİPAY", "TRENDYOL", "N11", "IDEFIX", "AMAZON", "PAYTR", "BOYNER", "GANT", "MASSIMO",
      "ZARA", "MACFIT", "TURNA", "OBILET", "OBİLET", "PEGASUS", "THY"), "alışveriş & seyahat"),
    (("RESIDENCE", "RESİDENCE", "AİDAT", "AIDAT"), "konut aidatı"),
    (("HAV.", "/KİŞ-", "/KIS-", "/MBL-", "FAST", "EFT"), "havale / EFT"),
]


_FOLD = str.maketrans("İŞĞÜÖÇ", "ISGUOC")


def _fold(text):
    """Karşılaştırma için: büyük harf + Türkçe harfler ASCII'ye ('Booking'/'BOOKİNG' aynı)."""
    return _tr_up(text).translate(_FOLD)


def _tr_has(text, keys):
    t = _fold(text)
    return any(_fold(k) in t for k in keys)


def _ilk(text, kurallar):
    for keys, kalem in kurallar:
        if _tr_has(text, keys):
            return kalem
    return None


def _gg_kalem(r):
    """Bir banka satırı -> (kalem, alt kalem|None) ya da None (sayılmaz: iç virman /
    döviz hesabındaki öbür bacak). Kalemin giren mi çıkan mı olduğu ayın NET tutarının
    işaretinden çıkar (borç − alacak > 0 = bankaya giren)."""
    cross = str(r.get("CROSSACCOUNT") or "")
    kod = cross.split(" ")[0]
    ad = cross[len(kod):].strip()
    notu = r.get("DETAILNOTES") or ""
    tl_bacak = (r.get("CURRENCYCODE") or "TRY").upper() in ("TRY", "TL")
    if not kod:                                       # çok satırlı fiş: açıklamadan
        if r.get("_ic"):
            return None
        if _tr_has(notu, ("AKPOS", "POS PES ODE")):
            return ("Kredi kartı (POS)", None)
        if _tr_has(notu, ("PARA YATIRMA",)):
            return ("Nakit yatırılan (kasadan)", None)
        if _tr_has(notu, ("MASRAF", "UFTM", "KOMİSYON", "KOMISYON")):
            return ("Banka masraf & komisyon", None)
        k = _ilk(notu, GG_TEDARIK)
        if k:
            return (k, None)
        return ("Diğer", None)
    if notu.upper().startswith("VERGI-") and not kod.startswith("195"):
        return ("Vergiler", None)       # çok satırlı fişte karşı hesap 102 görünse de dış ödeme
    if _tr_has(notu, ("SGK(", "SGK (")) and not kod.startswith("195"):
        return ("SGK primleri", None)
    if kod.startswith("102"):
        borc = num(r.get("LOCALDEBIT")) > 0
        if _tr_has(notu, ("PARA YATIRMA",)) and tl_bacak and borc:
            return ("Nakit yatırılan (kasadan)", None)     # TL hesabına giren nakit
        if _tr_has(notu, ("ATM",)) and tl_bacak and not borc:
            return ("Nakit çekilen (ATM)", None)           # TL hesabından çekilen nakit
        return None        # kendi hesaplarımız arası virman / döviz bozdurma (iki bacak)
    if notu.upper().startswith("VERGI-") and not kod.startswith("195") or kod.startswith(("360", "193")):
        return ("Vergiler", None)
    if kod.startswith("108"):
        return ("Kredi kartı (POS)", None)
    if kod.startswith(("120", "126", "127", "136")):
        return ("Misafir havale / EFT" if "MUHTELIF" in _fold(ad) else "Acenta ödemeleri",
                None if "MUHTELIF" in _fold(ad) else ad.title()[:40])
    if kod.startswith("100"):
        return ("Nakit yatırılan (kasadan)", None)
    if kod.startswith(("131", "231", "331", "431")):
        return ("Ortaklar", ad.title()[:40])
    if kod.startswith("335"):
        return ("Personel maaşları" if "MAAS" in _fold(ad) else "Hakkı huzur / ücret", None)
    if kod.startswith("361"):
        return ("SGK primleri", None)
    if kod.startswith("195"):
        k = _ilk(notu, GG_KART_ISLETME) or _ilk(notu, [x for x in GG_TEDARIK if x[1] in (
            "Bakım & onarım", "Elektrik", "Doğalgaz", "Su", "Çamaşırhane", "Hizmet alımı (İSG, danışman…)")])
        if k:
            return (k, None)
        return ("Sahip kartı & iş avansı", _ilk(notu, GG_KART_ALT) or "diğer kart harcamaları")
    if kod.startswith(("320", "329", "340", "336")):
        k = _ilk(ad, GG_TEDARIK) or ("MUHTELIF" in _fold(ad) and _ilk(notu, GG_TEDARIK))
        return (k or "Diğer tedarikçiler", None if k else ad.title()[:40])
    if kod.startswith(("300", "301", "303", "400", "401")):
        return ("Kredi ödemeleri", ad.title()[:40])
    if kod.startswith(("770", "780", "653", "656")):
        return ("Banka masraf & komisyon", None)
    if kod.startswith("689"):
        return ("Diğer", ad.title()[:40])
    if kod.startswith(("60", "64", "67")):
        return ("Diğer gelirler (faiz vb.)", ad.title()[:40])
    if kod.startswith("7"):
        if _tr_has(ad, ("TURİZM", "VERGİ", "HARÇ", "KATKI PAY")):
            return ("Vergiler", None)
        return ((ad or "Diğer giderler")[:40].title(), None)
    return ("Diğer", (ad or kod).title()[:40])


def _ic_virman_isaretle(rows):
    """Karşı hesabı boş satırlarda: aynı fişte BAŞKA bir 102 hesabında aynı tutarın ters
    bacağı varsa bu kendi hesaplarımız arası virmandır (ör. 'NKT Para ÇEKME ZİRAAT
    BANKASINA YATAN' / 'NKT Para Yatırma ZİRAAT BANKASI')."""
    idx = defaultdict(list)
    for r in rows:
        v = round(num(r.get("LOCALDEBIT")) - num(r.get("LOCALCREDIT")), 2)
        idx[(r.get("RECEIPTID"), v)].append(r)
    for r in rows:
        if r.get("CROSSACCOUNT"):
            continue
        v = round(num(r.get("LOCALDEBIT")) - num(r.get("LOCALCREDIT")), 2)
        if any(o is not r and o.get("ACCOUNTCODE") != r.get("ACCOUNTCODE")
               for o in idx.get((r.get("RECEIPTID"), -v), [])):
            r["_ic"] = True
    return rows


def _gg_aciklama(notu):
    """Banka açıklamasını sadeleştir: işlem kodları, kart no, uzun numaralar (TC, VKN,
    tahakkuk no) çıkar."""
    import re
    t = str(notu or "")
    t = re.sub(r"^\s*\d{2,5}/(KİŞ|KIS|MBL|ATM)-(\d+-)?", "", t)
    t = re.sub(r"^\s*0?\d{2,3}\s+", "", t)
    t = re.sub(r"XXXX\s*\d{4}", "", t)
    t = re.sub(r"\b(TC|VN|VKN|İM|IM|THN|VD|ID|ŞU|SU):\s*[\w]+", "", t)
    t = re.sub(r"\d{8,}", "…", t)
    t = re.sub(r"\s{2,}", " ", t).strip(" -/|")
    return t[:90] or "—"


GG_CSS = """<style>
.mtabs{display:flex;gap:6px;flex-wrap:wrap;margin:0 0 14px}
.mtabs button{font:inherit;font-size:13px;font-weight:700;padding:7px 14px;border-radius:999px;cursor:pointer;
  border:1px solid var(--border);background:var(--card);color:var(--sub)}
.mtabs button.on{background:var(--eyebrow);border-color:var(--eyebrow);color:#fff}
.gg-m{display:none}.gg-m.on{display:block}
.fresh{border-radius:11px;padding:10px 14px;font-size:13px;margin:0 0 14px;background:var(--th-bg);color:var(--sub)}
.fresh.old{background:#fffbeb;color:#92400e;border:1px solid #fde68a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]) .fresh.old{background:#2a2210;color:#fbbf24;border-color:#4a3a10}}
:root[data-theme=dark] .fresh.old{background:#2a2210;color:#fbbf24;border-color:#4a3a10}
.kl details{border-top:1px solid var(--td-line)}
.kl details:first-of-type{border-top:0}
.kl summary{list-style:none;cursor:pointer;padding:8px 2px}
.kl summary::-webkit-details-marker{display:none}
.kl .r1{display:flex;justify-content:space-between;gap:10px;font-size:13px}
.kl .r1>span:first-child::before{content:"▸";display:inline-block;width:14px;color:var(--sub);transition:transform .15s}
.kl details[open] .r1>span:first-child::before{transform:rotate(90deg)}
.gg-m .g2{align-items:start}
.kl .pc{color:var(--sub);font-weight:600;font-size:11.5px;margin-left:6px}
.kl .tr{height:6px;background:var(--th-bg);border-radius:4px;margin:5px 0 0 14px}
.kl .tr i{display:block;height:6px;border-radius:4px}
.kl .in i{background:#16a34a}.kl .out i{background:#dc2626}
.kl table{font-size:12px;margin:4px 0 10px 14px;width:calc(100% - 14px)}
.kl td{padding:5px 8px}
.kl .alt{font-size:11.5px;color:var(--sub);margin:2px 0 6px 14px}
.tot{display:flex;justify-content:space-between;font-weight:800;border-top:2px solid var(--border);
  padding-top:8px;margin-top:6px;font-size:14px}
.pos{color:var(--statok)}.neg{color:var(--statbad)}
.mx td,.mx th{white-space:nowrap}
.mx td:first-child{position:sticky;left:0;background:var(--tbl)}
</style>"""

GG_JS = """<script>
document.querySelectorAll('.mtabs button').forEach(function(b){b.addEventListener('click',function(){
  document.querySelectorAll('.mtabs button').forEach(function(x){x.classList.toggle('on',x===b)});
  document.querySelectorAll('.gg-m').forEach(function(m){m.classList.toggle('on',m.id===b.dataset.m)});
});});
</script>"""


def anlik_odalar(env):
    """Otelin 55 odasının numarası (QA_HOTEL_ROOM). Okunamazsa boş liste."""
    try:
        e, env = E.connect(env)
        hid = int(env.get("ELEKTRA_HOTELID", E.DEFAULT_TENANT))
        rows = e.select("QA_HOTEL_ROOM", ["ROOMNO"],
                        where=[{"Column": "HOTELID", "Operator": "=", "Value": hid}])
        return sorted({str(r["ROOMNO"]) for r in rows if str(r.get("ROOMNO") or "").isdigit()}, key=int)
    except Exception:
        return []


def build_anlik(env):
    """Anlık Durum — Günlük İşler'in en üstü (sahibi, 22.11.2026: "anlık dolu oda sayısı, eksik
    bilgiler ve gün sonu hazırlık sayfasındaki bilgileri ve senin gerekli gördüğün bilgileri").
    Tek sayfada: özet rakamlar, 'Şimdi yapılacaklar' (Gün Sonu + Eksik Bilgiler + Ödeme +
    kapı satışı + İstenilen Yorumlar), 55 odanın durumu, eksik bilgi tablosu, gün sonu
    maddeleri ve ek bilgiler (son 3 saatin rezervasyonları, kanal fiyatı, yarın, sistem).
    İstenilen Yorumlar ve oda/temizlik problemleri Günlük Rapor'un tarayıcıda tuttuğu
    kayıtlardan (localStorage) okunur — aynı cihazda işaretleneni görür."""
    import audit
    import nightaudit as NA
    today = tr_bugun()
    yarin = today + dt.timedelta(days=1)
    now = dt.datetime.now(ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
    iso = today.isoformat()

    inhouse = E.fetch_inhouse(env=env)
    arr_today = E.fetch_arrivals(iso, env=env)
    co_today = E.fetch_checkouts(iso, env=env)
    arr_yarin = E.fetch_arrivals(yarin.isoformat(), env=env)
    co_yarin = E.fetch_checkouts(yarin.isoformat(), env=env)
    gercek = lambda r: str(r.get("room") or "").isdigit() and not NA.is_virtual_folio(r)
    canli = lambda r: str(r.get("durum")) not in EXCL_STATES | {"Option"}
    inhouse = [r for r in inhouse if gercek(r)]

    # gün sonu maddeleri (nightaudit.generate ile aynı hesap, dosya yazmadan)
    cats = audit.categorise(inhouse, today)
    gelmedi = NA.not_checked_in([r for r in arr_today if canli(r)], now)
    cikmadi = NA.overstays(inhouse, today)
    sifir = NA.zero_rate(inhouse)
    borclu = cats["inhouse_owes"]

    # eksik bilgiler (konaklayanlar)
    gaps, _ = guest_gaps(E.fetch_res_guests(
        [{"Column": "RESSTATE", "Operator": "=", "Value": "InHouse"}], env=env))
    tel = [x for x in gaps if x["phone"] is not None]
    kim = [x for x in gaps if x["ident"]]
    eksik = sorted({x["rez"]: x for x in tel + kim}.values(), key=lambda x: int(x["room"]))
    try:
        who = E.fetch_checkin_users([x["rez"] for x in eksik] + [r.get("rez_id") for r in cikmadi], env=env)
    except Exception:
        who = {}

    # bugün satışlar (kapı/telefon), tahsilat, son 3 saatin rezervasyonları
    arr_ext = E.fetch_reservations_between("CHECKIN", iso, iso, env=env)
    dusuk = []
    kapi = []
    for a in arr_ext:
        if str(a.get("RESSTATE")) in EXCL_STATES | {"Option"} or not str(a.get("ROOMNO") or "")[:1].isdigit():
            continue
        if not _is_direct_agency((a.get("AGENCY") or "").strip()):
            continue
        avg = round(num(a.get("AVERAGENIGHTPRICE")) * (num(a.get("CURRENCYRATE")) or 1))
        kapi.append(avg)
        liste = satis_liste_fiyati(a)
        alt = (liste - SATIS_PAYI) if liste else SATIS_MIN_FIYAT
        if 0 < avg < alt:
            dusuk.append({"room": str(a.get("ROOMNO")), "agency": (a.get("AGENCY") or "").strip(),
                          "avg": avg, "liste": liste, "user": (a.get("CREATORUSER") or "").strip()})
    tahsil = Counter()
    try:
        for r in E.fetch_folio(iso, iso, env=env):
            if r.get("DEPTTYPENAME") == "PAYMENT":
                m = (r.get("DEPNAME") or "").lower()
                k = "nakit" if ("cash" in m or "nakit" in m) else "kart" if "card" in m or "kart" in m \
                    else "havale" if "havale" in m or "eft" in m else "diğer"
                tahsil[k] += abs(num(r.get("TOTAL")))
    except Exception:
        tahsil = None
    son3 = Counter()
    sinir3 = (now - dt.timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
    try:
        for r in E.fetch_reservations_between(
                "CREATEDATE", (now - dt.timedelta(hours=3)).date().isoformat(), iso, env=env,
                columns=["RESID", "AGENCY", "CREATEDATE", "RESSTATE"]):
            if str(r.get("CREATEDATE") or "")[:16].replace("T", " ") >= sinir3 and str(r.get("RESSTATE")) not in EXCL_STATES:
                son3[(r.get("AGENCY") or "?").strip().title()] += 1
    except Exception:
        son3 = None

    # doluluk ve fiyat
    try:
        dol = gece_doluluk(env, today, yarin)
    except Exception:
        dol = Counter()
    stu = FIYAT_ODALAR[1]
    fiyat_bu = gece_hedef(stu, today, dol.get(today, 0), today)
    fiyat_yarin = gece_hedef(stu, yarin, dol.get(yarin, 0), today)

    # kanallarda ucuz (son 6 saatin okumaları, bugün … +14)
    ucuz = Counter()
    try:
        taze = (now - dt.timedelta(hours=6)).strftime("%Y-%m-%d %H:%M")
        for (t, k, rk), o in fiyat_gozlemler().items():
            d = pdate(t)
            if k in ("booking", "hotels", "site") or rk == "eko" or not d or not (today <= d <= today + dt.timedelta(days=14)):
                continue
            if not o.get("fiyat") or o.get("zaman", "") < taze:
                continue
            hedef = dict((r[0], gece_taban(r, d, today)) for r in FIYAT_ODALAR)[rk]
            if o["fiyat"] < hedef - FIYAT_TOLERANS:
                ucuz[FIYAT_KANALLAR.get(k, (k,))[0]] = max(ucuz[FIYAT_KANALLAR.get(k, (k,))[0]], hedef - o["fiyat"])
    except Exception:
        ucuz = None

    # odalar
    odalar = anlik_odalar(env) or sorted({str(r["room"]) for r in inhouse}, key=int)
    by_room = {}
    for r in inhouse:
        by_room[str(r["room"])] = r
    bekleyen = {str(r.get("room")): r for r in gelmedi if str(r.get("room") or "").isdigit()}
    borc_oda = {str(r["room"]): r["_guest"] for r in borclu}
    eksik_oda = {x["room"]: gap_texts(x) for x in eksik}
    rooms = []
    for no in odalar:
        r = by_room.get(no)
        info = {"no": no}
        if r:
            co = pdate(r.get("checkout"))
            info.update(st="cik" if co and co <= today else "dolu", g=(r.get("guest") or "")[:40],
                        ag=(r.get("agency") or "").strip()[:24], ci=tr_g(pdate(r.get("checkin"))), co=tr_g(co))
        elif no in bekleyen:
            b = bekleyen[no]
            info.update(st="bek", g=(b.get("guest") or "")[:40], ag=(b.get("agency") or "").strip()[:24],
                        ci=tr_g(pdate(b.get("checkin"))), co=tr_g(pdate(b.get("checkout"))))
        else:
            info["st"] = "bos"
        if no in borc_oda:
            info["borc"] = round(borc_oda[no])
        if no in eksik_oda:
            info["eksik"] = eksik_oda[no]
        rooms.append(info)
    dolu_n = sum(1 for x in rooms if x["st"] in ("dolu", "cik"))

    # Şimdi yapılacaklar (sunucu tarafı; yorum ve problemler sayfada eklenir)
    todo = []
    def ekle(seviye, tag, baslik, detay, kim="", git="", sekme=""):
        # git/sekme: tıklayınca açılacak bölüm (ve Günlük Rapor sekmesi) — sahibi 23.11
        todo.append({"s": seviye, "tag": tag, "t": baslik, "d": detay, "w": kim, "g": git, "k": sekme})
    for r in cikmadi:
        u = who.get(str(r.get("rez_id")))
        ekle(0, "ÇIKMADI", f"Oda {r.get('room')} — çıkış tarihi geçti ({tr_g(pdate(r.get('checkout')))}), hâlâ konaklıyor görünüyor",
             "Misafir uzattıysa tarihi düzeltin, çıktıysa Elektra'da çıkış yapın.", f"giriş: {u[0]}" if u else "", "gunsonu")
    if borclu:
        top = sum(r["_guest"] for r in borclu)
        ekle(0, "BORÇ", f"{len(borclu)} konaklayan misafirin açık bakiyesi var — toplam {_tl(top)} ₺",
             " · ".join(f"Oda {r['room']} {_tl(r['_guest'])} ₺" for r in borclu[:6]), "Ödeme Kontrolü", "odeme")
    for r in sifir:
        ekle(0, "FİYATSIZ", f"Oda {r.get('room')} fiyatsız (0 ₺) satılmış", (r.get("agency") or "").strip(), "Gün Sonu", "gunsonu")
    # Giriş saati (14:00) geçti diye öğleden sonra uyarmak yanlış alarm: misafir akşam gelir.
    # 22:00'den sonra ya da önceki günden kalan rezervasyon "GELMEDİ" olur; öncesinde sadece "bekleniyor".
    gec = [r for r in gelmedi if now.hour >= 22 or (pdate(r.get("checkin")) or today) < today]
    if gec:
        ekle(1, "GELMEDİ", f"{len(gec)} rezervasyon hâlâ gelmedi (“Rezervasyon” durumunda)",
             " · ".join(f"{('Oda ' + str(r.get('room'))) if str(r.get('room') or '').isdigit() else 'oda atanmamış'} ({(r.get('agency') or '').strip()})"
                        for r in gec[:6]) + " — geldi mi, no-show mu?", "Gün Sonu", "gunsonu")
    if kim:
        ekle(1, "KİMLİK", f"{len(kim)} odada kimlik bilgisi eksik",
             " · ".join(f"Oda {x['room']}" for x in sorted(kim, key=lambda x: int(x['room']))[:10]) + " — KBS bildirimi için gerekli.", "Eksik Bilgiler", "eksik")
    if tel:
        ekle(1, "TELEFON", f"{len(tel)} odada telefon numarası yok",
             " · ".join(f"Oda {x['room']}" for x in sorted(tel, key=lambda x: int(x['room']))[:10]), "Eksik Bilgiler", "eksik")
    for x in dusuk:
        ekle(1, "FİYAT", f"Oda {x['room']} {x['agency'] or 'kapı'} satışı {_tl(x['avg'])} ₺ — listenin altında",
             f"Bu odanın liste fiyatı {_tl(x['liste'])} ₺." if x["liste"] else f"Sınır {_tl(SATIS_MIN_FIYAT)} ₺.",
             f"satış: {x['user']}" if x["user"] else "", "gunluk", "sales")
    if ucuz:
        # sahibi (21.11): "kesinlikle ucuza satmalarına izin verme". Bağlı kanalları kanal_duzelt.py
        # yarım saatte bir düzeltir; burada kalan, düzeltilemeyen (toptancı/son dakika) ucuzluktur.
        ekle(1, "UCUZ SATIŞ", f"{len(ucuz)} kanal/satıcı son 6 saatte hedefin altında görüldü",
             " · ".join(f"{k} −{_tl(v)} ₺" for k, v in ucuz.most_common(5))
             + " — bağlı kanallar otomatik düzeltiliyor; düzelmezse Fiyat Kontrol'e bakın.", "Fiyat Kontrol", "fiyat")
    ekle(3, "KBS", "KBS bildirimi otomatik kontrol edilemiyor", "Gün sonundan önce elle kontrol edin.", "Gün Sonu", "gunsonu")

    gunsonu = [   # (başlık, açıklama, ton, tıklayınca açılacak bölüm, Günlük Rapor sekmesi)
        ("Ödemeler", f"{len(borclu)} konaklayan borçlu" if borclu else "konaklayan borçlu yok", "bad" if borclu else "ok", "odeme", ""),
        ("Gelmeyenler", f"{len(gelmedi)} misafir henüz gelmedi" if gelmedi else "bekleyen yok", "warn" if gec else ("bek" if gelmedi else "ok"), "gunsonu", ""),
        ("Çıkmayanlar", f"{len(cikmadi)} oda çıkış tarihini geçti" if cikmadi else "yok", "bad" if cikmadi else "ok", "gunsonu", ""),
        ("Fiyatsız satış", f"{len(sifir)} oda 0 ₺" if sifir else "0 ₺ ya da fiyatsız rezervasyon yok", "bad" if sifir else "ok", "gunluk", "sales"),
        ("Eksik bilgi", f"{len(eksik)} odada kimlik/telefon eksik" if eksik else "eksik yok", "warn" if eksik else "ok", "eksik", ""),
        ("KBS", "otomatik kontrol yok — elle bakın", "man", "gunsonu", ""),
    ]
    hazir = not (borclu or gec or cikmadi or sifir)

    gelen = [r for r in arr_today if canli(r)]
    giren = [r for r in gelen if str(r.get("durum")) in ("InHouse", "CheckOut")]
    cikis = [r for r in co_today if canli(r) and gercek(r)]
    cikan = [r for r in cikis if str(r.get("durum")) == "CheckOut"]
    deps = [{"rez": str(r.get("rez_id") or ""), "room": str(r.get("room") or "")} for r in cikan]

    data = {"day": iso, "rooms": rooms, "todo": sorted(todo, key=lambda x: x["s"]), "deps": deps}

    # ---- HTML
    def kpi(baslik, deger, alt, ek=""):
        return (f"<div class='ak'><div class='l'>{esc(baslik)}</div><div class='n'>{deger}</div>{ek}"
                f"<div class='s'>{alt}</div></div>")
    yuzde = round(100 * dolu_n / (len(odalar) or ROOMS_TOTAL))
    kp = (kpi("Dolu oda", f"{dolu_n} <small>/ {len(odalar) or ROOMS_TOTAL}</small>", f"%{yuzde} doluluk · {len(odalar) - dolu_n} boş",
              f"<div class='bar'><i style='width:{yuzde}%'></i></div>")
          + kpi("Bugün giriş", str(len(gelen)), f"{len(giren)} geldi" + (f" · <b class='w'>{len(gelen) - len(giren)} bekleniyor</b>" if len(gelen) > len(giren) else ""))
          + kpi("Bugün çıkış", str(len(cikis)), f"{len(cikan)} çıktı" + (f" · <b class='b'>{len(cikis) - len(cikan)} çıkmadı</b>" if len(cikis) > len(cikan) else ""))
          + kpi("Bu gece kapı fiyatı", f"{_tl(fiyat_bu)} ₺", f"Stüdyo · {BASAMAK_ADI[basamak(today, today, dol.get(today, 0))]} · indirim yok")
          + (kpi("Bugün tahsilat", f"{_tl(sum(tahsil.values()))} ₺",
                 " · ".join(f"{k} {_tl(v)}" for k, v in tahsil.most_common()) or "henüz tahsilat yok") if tahsil is not None else ""))

    def satir_eksik(x):
        u = who.get(x["rez"])
        return (f"<tr class='go' data-go='eksik' title='Eksik Bilgiler sayfasında aç'><td class='mono'><b>{esc(x['room'])}</b></td><td>{esc(x['guest'][:30])}</td>"
                f"<td>{'<br>'.join(esc(t) for t in gap_texts(x))}</td><td>{esc(tr_g(x['ci']))}</td>"
                f"<td>{('<span class=who>' + esc(u[0]) + '</span>') if u else '—'}</td></tr>")
    eksik_html = (("<div style='overflow-x:auto'><table><thead><tr><th>Oda</th><th>Misafir</th><th>Eksik</th>"
                   "<th>Giriş</th><th>Girişi yapan</th></tr></thead><tbody>" + "".join(satir_eksik(x) for x in eksik)
                   + "</tbody></table></div>") if eksik else empty_ok("Konaklayanların bilgileri tam."))
    ton = {"ok": ("TAMAM", "ok"), "warn": ("DİKKAT", "warn"), "bad": ("DİKKAT", "bad"), "man": ("ELLE", "man"), "bek": ("BEKLENİYOR", "man")}
    gs_html = "".join(f"<button type='button' class='gs go' data-go='{g}' data-sk='{k}'><div><b>{esc(a)}</b><div class='s'>{esc(n)}</div></div>"
                      f"<span class='pill {ton[t][1]}'>{ton[t][0]}</span></button>" for a, n, t, g, k in gunsonu)

    ek = []
    if son3 is not None:
        ek.append(("Son 3 saatte yeni rezervasyon", str(sum(son3.values())),
                   " · ".join(f"{k} {v}" for k, v in son3.most_common(5)) or "yeni rezervasyon yok", ""))
    if ucuz is not None:
        ek.append(("Kanallarda fiyat (14 gün)", f"{len(ucuz)} ucuz" if ucuz else "hepsi hedefte",
                   " · ".join(f"{k} −{_tl(v)} ₺" for k, v in ucuz.most_common(4)) or "Booking/Expedia hariç bütün okumalar hedefte",
                   "b" if ucuz else "o"))
    if kapi:
        ek.append(("Bugün kapıdan / telefondan giriş", f"{len(kapi)} oda",
                   f"ort. {_tl(sum(kapi) / len(kapi))} ₺" + (f" · <b class='b'>{len(dusuk)} tanesi listenin altında</b>" if dusuk else ""), ""))
    ek.append(("Yarın", f"{len([r for r in arr_yarin if canli(r)])} giriş · {len([r for r in co_yarin if canli(r) and gercek(r)])} çıkış",
               f"yarın gece {dol.get(yarin, 0)} dolu · Stüdyo {_tl(fiyat_yarin)} ₺", ""))
    ek_html = "".join(f"<div class='ex'><div class='l'>{esc(a)}</div><div class='n {c}'>{b}</div><div class='s'>{d}</div></div>"
                      for a, b, d, c in ek)
    ek_html += "<div class='ex' id='axProb'></div>"

    body = (AN_CSS
            + f"<div class='fresh'>Elektra'dan · pano her saat ve 30 dakikada bir yenilenir · bu sayfa: <b>{now.strftime('%d.%m %H:%M')}</b></div>"
            + f"<div class='aks'>{kp}</div>"
            + "<div class='card'><div class='hd'><h2>Şimdi yapılacaklar <span id='axN' class='b'></span></h2>"
              "<span class='s'>Gün Sonu + Eksik Bilgiler + Ödeme + Yorumlar · en acil üstte</span></div><div id='axTodo'></div></div>"
            + "<div class='card'><div class='hd'><h2>Oda durumu</h2><div class='lg'>"
              "<span><i class='sw dolu'></i>Dolu</span><span><i class='sw bek'></i>Giriş bekleniyor</span>"
              "<span><i class='sw cik'></i>Bugün çıkacak</span><span><i class='sw bos'></i>Boş</span>"
              "<span><b class='b'>!</b> Eksik bilgi / borç</span></div></div>"
              "<div id='axRooms' class='rooms'></div><div id='axRoom' class='rinfo'>Bir odaya dokunun: misafir, tarih, bakiye ve eksik bilgi burada görünür.</div></div>"
            + f"<div class='g2'><div class='card'><div class='hd'><h2><button type='button' class='hlink go' data-go='eksik'>Eksik bilgiler <span class='b'>({len(eksik)} oda)</span> ›</button></h2>"
              f"<span class='s'>misafir otelde, hemen tamamlanabilir</span></div>{eksik_html}</div>"
              f"<div class='card'><div class='hd'><h2><button type='button' class='hlink go' data-go='gunsonu'>Gün sonu hazırlık ›</button></h2><span class='pill {'ok' if hazir else 'warn'}'>"
              f"{'HAZIR (KBS elle)' if hazir else 'HENÜZ HAZIR DEĞİL'}</span></div>{gs_html}</div></div>"
            + f"<div class='card'><div class='hd'><h2>Ayrıca bilinmesi gerekenler</h2></div><div class='exs'>{ek_html}</div></div>"
            + "<script>var AD=" + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";</script>" + AN_JS)
    n = len([t for t in todo if t["s"] < 3])
    return {"label": "Anlık Durum", "count": n, "count_label": "yapılacak", "tone": "bad" if n else "ok",
            "sub": f"{dolu_n}/{len(odalar) or ROOMS_TOTAL} dolu · {len(eksik)} eksik bilgi · gün sonu {'hazır' if hazir else 'hazır değil'}",
            "updated": now.strftime("%d.%m.%Y %H:%M"),
            "html": PAGE(None, "Anlık Durum", "", body)}   # başlık shell'de; içeride tekrarlanmaz (sahibi 22.11)


AN_CSS = """<style>
.aks{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:0 0 16px}
.ak{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:14px 16px}
.ak .l,.ex .l{color:var(--sub);font-size:12.5px;font-weight:600}
.ak .n{font-size:28px;font-weight:800;margin-top:2px}.ak .n small{font-size:15px;color:var(--sub);font-weight:600}
.ak .s,.ex .s,.gs .s,.card .s{color:var(--sub);font-size:12px;margin-top:3px}
.ak .bar{height:7px;background:var(--th-bg);border-radius:9px;overflow:hidden;margin-top:6px}.ak .bar i{display:block;height:7px;background:var(--eyebrow)}
.b{color:var(--statbad)}.w{color:#b45309}.o{color:var(--statok)}
.card{margin:0 0 16px}.card .hd{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.card .hd h2{margin:0;font-size:16px}
.td{display:flex;gap:12px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--td-line)}
.td:first-child{border-top:0}
.tg{flex:0 0 auto;min-width:70px;text-align:center;font-size:10.5px;font-weight:800;padding:4px 7px;border-radius:6px}
.tg.s0{background:#fde8e8;color:#991b1b}.tg.s1{background:#fef3c7;color:#92400e}.tg.s2{background:#e0e7ff;color:#3730a3}.tg.s3{background:var(--th-bg);color:var(--th-fg)}
.td .t{font-weight:700}.td .d{color:var(--sub);font-size:12.5px;margin-top:1px}.td .wh{margin-left:auto;color:var(--sub);font-size:12px;white-space:nowrap}
.lg{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--sub)}.lg span{display:flex;align-items:center;gap:5px}
.sw{display:inline-block;width:12px;height:12px;border-radius:3px}
.rooms{display:grid;grid-template-columns:repeat(auto-fill,minmax(62px,1fr));gap:7px;margin-top:6px}
.rm{position:relative;height:50px;border-radius:9px;border:0;font:inherit;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center}
.rm b{font-size:14.5px}.rm span{font-size:10px;opacity:.85}
.rm .x{position:absolute;top:2px;right:6px;color:#dc2626;font-weight:900;font-size:13px}
.dolu{background:#1d4ed8;color:#fff}.bek{background:#f59e0b;color:#111827}.cik{background:var(--card);color:#991b1b;box-shadow:inset 0 0 0 2px #dc2626}
.bos{background:var(--th-bg);color:var(--th-fg)}
.sw.cik{box-shadow:inset 0 0 0 2px #dc2626}
.rm.sel{outline:3px solid var(--fg);outline-offset:1px}
.rinfo{margin-top:10px;font-size:13px;color:var(--sub);background:var(--th-bg);border-radius:10px;padding:10px 12px}
.g2{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:16px}.g2 .card{margin:0 0 16px}
.gs{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:9px 0;border-top:1px solid var(--td-line)}
.pill{font-size:11px;font-weight:800;padding:4px 10px;border-radius:999px;white-space:nowrap}
.pill.ok{background:#dcfce7;color:#166534}.pill.warn{background:#fef3c7;color:#92400e}.pill.bad{background:#fde8e8;color:#991b1b}.pill.man{background:var(--th-bg);color:var(--th-fg)}
.exs{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.ex{border:1px solid var(--border);border-radius:12px;padding:12px 14px}.ex:empty{display:none}
.ex .n{font-size:21px;font-weight:800;margin-top:2px}
.mono{font-variant-numeric:tabular-nums}
/* tıklanınca ilgili bölüme git (sahibi 23.11) */
button.td,button.gs{width:100%;border:0;border-top:1px solid var(--td-line);background:none;font:inherit;color:inherit;text-align:left;cursor:pointer}
button.td:first-child{border-top:0}
.go{cursor:pointer}.go:hover{background:var(--th-bg)}
button.td:hover,button.gs:hover{background:var(--th-bg)}
.td .wh{color:var(--eyebrow)!important;font-weight:700}
.hlink{border:0;background:none;font:inherit;color:inherit;padding:0;cursor:pointer}.hlink:hover{color:var(--eyebrow)}
</style>"""

AN_JS = """<script>
(function(){
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});}
  function sget(k){try{return localStorage.getItem(k)||'';}catch(e){return '';}}
  function lst(k){try{var s=localStorage.getItem(k);return s?JSON.parse(s):[];}catch(e){return [];}}
  var todo=AD.todo.slice();
  // İstenilen Yorumlar (Günlük Rapor'un kaydı: 'RG:<gün>:yistendi:<rez>' = '1'). İşaretlenmeyen çıkış = yapılacak.
  var yok=AD.deps.filter(function(d){return d.rez && sget('RG:'+AD.day+':yistendi:'+d.rez)!=='1';});
  if(yok.length) todo.push({s:2,tag:'YORUM',t:yok.length+' çıkış yapan misafirden yorum istendiği not edilmedi',
    d:yok.slice(0,10).map(function(d){return 'Oda '+d.room;}).join(' · ')+' — Günlük Rapor › İstenilen Yorumlar’da işaretleyin.',w:'Günlük Rapor',g:'gunluk',k:'yorum'});
  // Oda / temizlik problemleri (Günlük Rapor'da girilen, bitmemiş olanlar)
  // son 7 gün: önceki günlerde girilip hâlâ "Yapıldı" işaretlenmemiş problemler de açık sayılır
  var pr=[],d0=new Date(AD.day+'T12:00:00');
  for(var g=0;g<7;g++){var dd=new Date(d0.getTime()-g*864e5).toISOString().slice(0,10);
    ['odap','temp'].forEach(function(t){lst('RG:'+dd+':'+t).forEach(function(r){if(r&&!r.done&&(r.oda||r.problem))pr.push({t:t,r:r});});});}
  var pe=document.getElementById('axProb');
  if(pe) pe.innerHTML="<div class='l'>Açık oda / temizlik problemi</div><div class='n "+(pr.length?'b':'o')+"'>"+(pr.length?pr.length+' açık':'yok')+"</div>"
    +"<div class='s'>"+(pr.length?pr.slice(0,4).map(function(x){return esc((x.r.oda?('Oda '+x.r.oda+' '):'')+(x.r.problem||''));}).join(' · '):'Günlük Rapor’da kayıtlı açık problem yok')+"</div>";
  todo.sort(function(a,b){return a.s-b.s;});
  var n=todo.filter(function(x){return x.s<3;}).length;
  document.getElementById('axN').textContent=n?'('+n+')':'';
  document.getElementById('axTodo').innerHTML=todo.length?todo.map(function(x){
    var tag=x.g?"button type='button' class='td' data-go='"+esc(x.g)+"' data-sk='"+esc(x.k||'')+"'":"div class='td'";
    return "<"+tag+"><span class='tg s"+x.s+"'>"+esc(x.tag)+"</span><div><div class='t'>"+esc(x.t)+"</div><div class='d'>"+esc(x.d)+"</div></div>"
      +(x.w?"<span class='wh'>"+esc(x.w)+(x.g?" ›":"")+"</span>":"")+"</"+(x.g?"button":"div")+">";}).join(''):"<div class='empty'>✓ Şu an yapılacak bir şey yok.</div>";
  // tıklayınca ilgili bölüm (panel çerçevesine istek; sekme Günlük Rapor içindir)
  document.addEventListener('click',function(ev){var b=ev.target.closest('[data-go]'); if(!b)return;
    try{parent.postMessage({git:b.getAttribute('data-go'),sekme:b.getAttribute('data-sk')||''},'*');}catch(e){}});
  var ad={dolu:'dolu',bek:'bekleniyor',cik:'çıkacak',bos:'boş'};
  var box=document.getElementById('axRooms'), info=document.getElementById('axRoom');
  box.innerHTML=AD.rooms.map(function(r,i){
    return "<button type='button' class='rm "+r.st+"' data-i='"+i+"' aria-label='Oda "+esc(r.no)+" "+ad[r.st]+"'><b>"+esc(r.no)+"</b><span>"+ad[r.st]+"</span>"
      +((r.eksik||r.borc)?"<i class='x'>!</i>":"")+"</button>";}).join('');
  box.addEventListener('click',function(ev){var b=ev.target.closest('.rm'); if(!b)return;
    box.querySelectorAll('.rm.sel').forEach(function(x){x.classList.remove('sel');}); b.classList.add('sel');
    var r=AD.rooms[+b.dataset.i];
    info.innerHTML="<b style='color:var(--fg)'>Oda "+esc(r.no)+"</b> · "+ad[r.st]
      +(r.g?" · "+esc(r.g):"")+(r.ag?" · "+esc(r.ag):"")+(r.ci?" · "+esc(r.ci)+" → "+esc(r.co):"")
      +(r.borc?" · <b class='b'>borç "+r.borc.toLocaleString('tr-TR')+" ₺</b>":"")
      +(r.eksik?"<br><span class='b'>"+r.eksik.map(esc).join(' · ')+"</span>":"");
  });
})();
</script>"""


def build_gelirgider(env):
    """Gelir-Gider — bankaya giren / bankadan çıkan para, Elektra muhasebesinden."""
    today = dt.date.today()
    bas = month_start(today, GG_AY - 1)
    rows = _banka_6ay(env)
    son_gun = max((str(r.get("RECEIPTDATE"))[:10] for r in rows), default="")

    aylar = [month_start(today, GG_AY - 1 - i) for i in range(GG_AY)]
    akey = lambda d: (d.year, d.month)
    veri = {akey(a): defaultdict(lambda: {"net": 0.0, "n": 0, "rows": [], "alt": defaultdict(float)})
            for a in aylar}
    for r in rows:
        k = _gg_kalem(r)
        if not k:
            continue
        d = pdate(r.get("RECEIPTDATE"))
        if not d or akey(d) not in veri:
            continue
        v = num(r.get("LOCALDEBIT")) - num(r.get("LOCALCREDIT"))
        c = veri[akey(d)][k[0]]
        c["net"] += v
        c["n"] += 1
        c["rows"].append((d, _gg_aciklama(r.get("DETAILNOTES")), v, k[1]))
        if k[1]:
            c["alt"][k[1]] += v

    # Aynı ayların oda satışı (tahakkuk) — "satışın ne kadarı bankaya girdi" kıyası için.
    try:
        act = active_reservations(env, bas, today)
        satis = monthly_aggregate(daily_occupancy(act, bas, today))
    except Exception as e:                      # satış alınamazsa sayfa yine çıksın
        print(f"  gelirgider: oda satışı alınamadı: {e}")
        satis = {}

    def ozet(a):
        v = veri[akey(a)]
        g = sum(c["net"] for c in v.values() if c["net"] > 0)
        c_ = -sum(c["net"] for c in v.values() if c["net"] < 0)
        return g, c_

    def liste(v, giren):
        its = sorted(((ad, c) for ad, c in v.items() if (c["net"] > 0) == giren and abs(c["net"]) >= 1),
                     key=lambda t: -abs(t[1]["net"]))
        top = sum(abs(c["net"]) for _, c in its) or 1
        mx = max([abs(c["net"]) for _, c in its] + [1])
        out = []
        for ad, c in its:
            val = abs(c["net"])
            alt = ""
            if c["alt"]:
                alt = "<div class='alt'>" + " · ".join(
                    f"{esc(k)} {tl(abs(x))}" for k, x in sorted(c["alt"].items(), key=lambda t: t[1] if not giren else -t[1])
                    if abs(x) >= 1) + "</div>"
            satir = "".join(
                f"<tr><td>{d.day:02d}.{d.month:02d}</td><td>{esc(a)}"
                + (f" <span class='who'>{esc(al)}</span>" if al and ad != 'Acenta ödemeleri' else "")
                + f"</td><td class='r money {'pos' if x > 0 else 'neg'}'>{'+' if x > 0 else '−'}{tl(abs(x))}</td></tr>"
                for d, a, x, al in sorted(c["rows"], key=lambda t: -abs(t[2]))[:80])
            fazla = (f"<tr><td colspan='3' class='lead'>… ve {len(c['rows']) - 80} küçük işlem daha</td></tr>"
                     if len(c["rows"]) > 80 else "")
            out.append(
                f"<details><summary><div class='r1'><span>{esc(ad)}<span class='pc'>%{val / top * 100:.0f}"
                f" · {c['n']} işlem</span></span><span class='money'>{tl(val)} ₺</span></div>"
                f"<div class='tr {'in' if giren else 'out'}'><i style='width:{val / mx * 100:.1f}%'></i></div>"
                f"</summary>{alt}<div class='scroll'><table>{satir}{fazla}</table></div></details>")
        return "".join(out) or "<div class='lead'>kayıt yok</div>", sum(abs(c["net"]) for _, c in its)

    tabs, bolumler = [], []
    for i, a in enumerate(reversed(aylar)):
        k = akey(a)
        mid = f"m{a.year}{a.month:02d}"
        on = " on" if i == 0 else ""
        tabs.append(f"<button class='{on.strip()}' data-m='{mid}'>{TR_MON_FULL[a.month]}"
                    f"{'' if a.year == today.year else ' ' + str(a.year)}</button>")
        v = veri[k]
        gl, gt = liste(v, True)
        cl, ct = liste(v, False)
        fark = gt - ct
        oda = satis.get(k, {}).get("rev", 0.0)
        bu = (a.year, a.month) == (today.year, today.month)
        kpis = (kpi(f"{tl(gt)} ₺", "Bankaya giren", "satış tahsilatı + yatırılan nakit + diğer")
                + kpi(f"{tl(ct)} ₺", "Bankadan çıkan", "giderler, maaş, vergi, ödemeler")
                + kpi(f"<span class='{'pos' if fark >= 0 else 'neg'}'>{'+' if fark >= 0 else '−'}{tl(abs(fark))} ₺</span>",
                      "Fark", "giren − çıkan")
                + kpi(f"{tl(oda)} ₺", "Aynı ay oda satışı",
                      "Elektra rezervasyonları" + (" · bugüne kadar" if bu else "")))
        bolumler.append(
            f"<div class='gg-m{on}' id='{mid}'><div class='kpis'>{kpis}</div><div class='g2'>"
            f"<div class='card kl'><h3>Para nereden geldi <small>tıklayın: işlemler</small></h3>{gl}"
            f"<div class='tot'><span>Toplam giren</span><span class='pos'>{tl(gt)} ₺</span></div></div>"
            f"<div class='card kl'><h3>Para nereye gitti <small>tıklayın: işlemler</small></h3>{cl}"
            f"<div class='tot'><span>Toplam çıkan</span><span class='neg'>{tl(ct)} ₺</span></div></div>"
            "</div></div>")

    # ---- 6 aylık eğilim + kalem × ay tablosu
    lbl = [mlabel(akey(a)) for a in aylar]
    oz = [ozet(a) for a in aylar]
    trend = (f"<div class='sec'>Son {GG_AY} ay</div><div class='g2'>"
             "<div class='card'><h3>Bankaya giren / çıkan <small><span class='pos'>■</span> giren · "
             "<span class='neg'>■</span> çıkan</small></h3>"
             f"{ch_bars2(lbl, [g for g, _ in oz], [c for _, c in oz], height=150)}</div>"
             "<div class='card'><h3>Oda satışı ve bankaya giren <small>■ satış · ■ giren</small></h3>"
             f"{ch_bars2(lbl, [satis.get(akey(a), {}).get('rev', 0.0) for a in aylar], [g for g, _ in oz], height=150, renk=('var(--bar)', '#16a34a'))}"
             "</div></div>")
    kalemler = defaultdict(lambda: [0.0] * len(aylar))
    for j, a in enumerate(aylar):
        for ad, c in veri[akey(a)].items():
            kalemler[ad][j] += c["net"]
    sira = sorted(kalemler.items(), key=lambda t: sum(t[1]))           # en büyük gider üstte
    gid = [(ad, xs) for ad, xs in sira if sum(xs) < 0]
    gir = [(ad, xs) for ad, xs in reversed(sira) if sum(xs) >= 0]

    def satirlar(ls, isaret):
        return "".join(
            f"<tr><td>{esc(ad)}</td>" + "".join(
                f"<td class='r'>{tl(x * isaret) if abs(x) >= 1 else '—'}</td>" for x in xs) + "</tr>"
            for ad, xs in ls)
    bas_ = "".join(f"<th class='r'>{esc(l)}</th>" for l in lbl)
    matris = (
        "<div class='sec'>Kalem kalem, ay ay</div><div class='tw mx'><table>"
        f"<tr><th>Bankaya giren</th>{bas_}</tr>{satirlar(gir, 1)}"
        "<tr class='top'><td>Toplam giren</td>" + "".join(f"<td class='r money'>{tl(g)}</td>" for g, _ in oz) + "</tr>"
        f"<tr><th>Bankadan çıkan</th>{bas_}</tr>{satirlar(gid, -1)}"
        "<tr class='top'><td>Toplam çıkan</td>" + "".join(f"<td class='r money'>{tl(c)}</td>" for _, c in oz) + "</tr>"
        "<tr class='top'><td>Fark</td>" + "".join(
            f"<td class='r money {'pos' if g - c >= 0 else 'neg'}'>{tl(g - c)}</td>" for g, c in oz) + "</tr>"
        "</table></div>")

    try:
        gecik = (today - dt.date.fromisoformat(son_gun)).days if son_gun else 99
    except ValueError:
        gecik = 99
    fresh = (f"<div class='fresh{' old' if gecik > 4 else ''}'>📒 Muhasebeci banka hareketlerini en son "
             f"<b>{_tr_d(son_gun)}</b> tarihine kadar Elektra'ya işlemiş"
             + (f" ({gecik} gün önce). Sonraki günlerin hareketleri burada henüz yok." if gecik > 1 else ".")
             + "</div>")
    note = ("<div class='note'><b>Nasıl hesaplanıyor?</b> Elektra muhasebesindeki tüm banka hesaplarının "
            "(102) hareketleri; her hareketin karşı hesabına ve açıklamasına göre kaleme ayrılır. "
            "<b>Kredi kartı (POS)</b> = bankanın yatırdığı POS tutarı (komisyon düşülmüş). "
            "<b>Nakit yatırılan</b> = kasadan bankaya yatırılan para. Kendi hesaplarınız arası virman ve "
            "döviz bozdurma sayılmaz. <b>Sahip kartı & iş avansı</b> = muhasebede “İş avansı” hesabına "
            "işlenen banka kartı harcamaları ve havaleler; işletme gideri olduğu açık olanlar (Google reklamı, "
            "yazılım, bakım-onarım) kendi kalemine alındı. Oda satışı ile bankaya giren aynı olmaz: POS ertesi "
            "gün, acentalar haftalar sonra öder; nakit kasada bekleyebilir. Kalemlerin içindeki işlem listesi "
            "muhasebecinin girdiği banka açıklamasıdır.</div>")
    body = (f"{SALES_CSS}{GG_CSS}<div class='lock'>🔒 Yalnız yönetici</div>{fresh}"
            f"<div class='mtabs'>{''.join(tabs)}</div>{''.join(bolumler)}{trend}{matris}{note}{GG_JS}")
    g0, c0 = oz[-1]
    return {"label": "Gelir-Gider", "count": int(round(g0 / 1000)),
            "count_label": "bin ₺ · bu ay bankaya giren", "tone": "ok",
            "sub": (f"{TR_MON_FULL[today.month]}: giren {tl(g0)} ₺ · çıkan {tl(c0)} ₺ · "
                    f"son muhasebe kaydı {_tr_d(son_gun)}"),
            "updated": now_str(),
            "html": PAGE(None, "Gelir-Gider", "", BV_CSS + body)}


# ---------------------------------------------------------------------------
# Nakit Tahsilat Kontrol (Denetim) — sahibi 23.11.2026: "geçen haftanın nakit tahsilatları,
# özellikle liste fiyatı altında kalanlar; teker teker KAMERADAN kontrol ediyorum, o saatte
# gerçekten o miktarı almışlar mı diye. İlk 5'e bakacağım, sen daha fazla şüpheli getirebilirsin."
# Veri: nakit_kontrol.analiz (yerel nakit_supheli.py yönteminin aynısı). Yalnız yönetim.
def build_nakit(env):
    import nakit_kontrol as NK
    gun = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
    bugun = (dt.datetime.utcnow() + dt.timedelta(hours=3)).date()
    bu_pzt = bugun - dt.timedelta(days=bugun.weekday())
    haftalar = [("gecen", "Geçen hafta", bu_pzt - dt.timedelta(days=7), bu_pzt - dt.timedelta(days=1)),
                ("bu", "Bu hafta (bugüne kadar)", bu_pzt, bugun),
                ("onceki", "Önceki hafta", bu_pzt - dt.timedelta(days=14), bu_pzt - dt.timedelta(days=8))]
    veri = NK.analiz(haftalar[2][2], bugun, env)
    if not veri["satirlar"]:
        raise RuntimeError("3 haftada hiç nakit tahsilat dönmedi — boş liste 'temiz' sayılmaz (API sorunu olabilir).")

    def an_s(t):
        return f"{t:%d.%m} {gun[t.weekday()]} <b>{t:%H:%M}</b>"

    def para(n):
        return f"{tl(n)[:-3]} ₺"

    def tag(s, renk):
        return (f"<span style='display:inline-block;background:{renk};color:#fff;border-radius:6px;"
                f"padding:1px 7px;font-size:11px;font-weight:700;margin:1px 4px 1px 0'>{esc(s)}</span>")

    def tahsilatlar_html(ps):
        return "<br>".join(
            f"{an_s(p['an'])} <span class='lead'>({p['vardiya']})</span> · <span class='who'>{esc(p['kim'])}</span>"
            f" · <span class='money'>{para(p['tutar'])}</span>"
            + (f" <span class='lead'>({esc(p['doviz'])})</span>" if p["doviz"] not in ("TRY", "TL") else "")
            for p in ps)

    def hafta_paneli(anahtar, ad, bas, bit):
        sat = [s for s in veri["satirlar"] if bas <= s["an"].date() <= bit]
        toplam = sum(s["tutar"] for s in sat if s["tutar"] > 0)
        # 1) Liste altı — rezervasyon başına bir satır, o haftadaki tüm nakit tahsilatlarıyla
        rez = OrderedDict()
        for s in sat:
            if s["fiyat"] and s["fiyat"]["liste_alti"]:
                rez.setdefault(s["rid"], []).append(s)
        la = sorted(rez.values(), key=lambda ps: ps[0]["fiyat"]["fark"] * ps[0]["fiyat"]["n"])
        la_fark = sum(ps[0]["fiyat"]["fark"] * ps[0]["fiyat"]["n"] for ps in la)
        la_ids = set(rez)
        # 2) Diğer dikkat — liste altı olmayan ama bir nedeni olan tahsilatlar
        diger = [s for s in sat if s["nedenler"] and s["rid"] not in la_ids]

        st = (stat(len(sat), "nakit tahsilat") + stat(para(toplam), "toplam nakit")
              + stat(len(la), "liste fiyatı altında", "bad" if la else "ok")
              + stat(para(la_fark) if la else "0 ₺", "liste altı toplam fark", "bad" if la else "ok")
              + stat(len(diger), "diğer dikkat", "bad" if diger else "ok"))

        if la:
            trs = ""
            for i, ps in enumerate(la, 1):
                s0, f = ps[0], ps[0]["fiyat"]
                gece = (f"{s0['giris']:%d.%m} {gun[s0['giris'].weekday()]}" if s0["giris"] else "—") \
                    + (f" <span class='lead'>+{f['n'] - 1} gece</span>" if f["n"] > 1 else "")
                hedef = para(f["hedef"]) + (f" <span class='lead'>({f['d0']} oda dolu)</span>"
                                             if f["d0"] is not None else " <span class='lead'>(taban)</span>")
                acan = esc(f["acan"] or "?") + (f" <span class='lead'>{f['acan_t']:%d.%m %H:%M}</span>"
                                                 if f["acan_t"] else "")
                ek = "".join(tag(n, "#b45309") for n in ps[0]["nedenler"])
                ilk5 = tag(f"ÖNCE BAK #{i}", "#dc2626") if i <= 5 else f"<b>{i}</b>"
                trs += (f"<tr class='{'bad' if i <= 5 else ''}'><td>{ilk5}</td>"
                        f"<td>{tahsilatlar_html(ps)}{('<br>' + ek) if ek else ''}</td>"
                        f"<td><b>{esc(s0['oda'] or '—')}</b> <span class='lead'>{esc(s0['oda_tipi'])}</span><br>"
                        f"{esc(s0['misafir'][:32])}</td>"
                        f"<td>{rez_link(s0['rid'])}<br><span class='lead'>{esc(s0['kanal'] or 'acentasız')}</span></td>"
                        f"<td>{gece}</td><td>{acan}</td>"
                        f"<td class='r money'>{para(f['gecelik'])}</td><td class='r'>{hedef}</td>"
                        f"<td class='r money miss'>{para(f['fark'])}"
                        + (f"<br><span class='lead'>toplam {para(f['fark'] * f['n'])}</span>" if f["n"] > 1 else "")
                        + "</td></tr>")
            bol1 = ("<h2>🎥 Önce bunlara bakın — liste fiyatının altındaki nakit satışlar</h2>"
                    "<p class='lead'>Resepsiyonun kendi fiyatladığı (walk-in / telefon / acentasız) ve <b>nakit</b> "
                    "ödenen satışlardan gecelik fiyatı listenin altında kalanlar, <b>en büyük farktan başlayarak</b>. "
                    "Kamerada kontrol için her tahsilatın <b>gerçek tarihi-saati</b> ve kasada alan kişi ilk sütunda. "
                    "“Olması gereken” = satış anındaki doluluğa göre liste basamağı.</p>"
                    "<table><tr><th>#</th><th>Tahsilat (tarih · saat · alan · tutar)</th><th>Oda / misafir</th>"
                    "<th>Rez No</th><th>Gece</th><th>Rezervasyonu açan</th><th class='r'>Alınan (gecelik)</th>"
                    "<th class='r'>Olması gereken</th><th class='r'>Fark</th></tr>" + trs + "</table>")
        else:
            bol1 = "<h2>🎥 Liste fiyatının altındaki nakit satışlar</h2>" + empty_ok(
                "Bu hafta liste fiyatının altında nakit satış yok.")

        if diger:
            trs = "".join(
                f"<tr><td>{an_s(s['an'])}<br><span class='lead'>{s['vardiya']}</span></td>"
                f"<td><span class='who'>{esc(s['kim'])}</span></td>"
                f"<td class='r money'>{para(s['tutar'])}</td>"
                f"<td><b>{esc(s['oda'] or '—')}</b> {esc(s['misafir'][:28])}</td>"
                f"<td>{rez_link(s['rid'])}<br><span class='lead'>{esc(s['kanal'] or ('acentasız' if s['rid'] else ''))}</span></td>"
                f"<td>{''.join(tag(n, '#b45309') for n in s['nedenler'])}</td></tr>"
                for s in diger)
            bol2 = ("<h2>🔎 Şüpheli olabilecek diğerleri</h2>"
                    "<p class='lead'>Liste fiyatı sorunu olmayan ama başka bir nedenle bakmaya değer nakit hareketleri. "
                    "Bunlar <b>suçlama değil</b>, kontrol listesi: çoğunun masum bir açıklaması olabilir.</p>"
                    "<table><tr><th>Tahsilat</th><th>Alan</th><th class='r'>Tutar</th><th>Oda / misafir</th>"
                    "<th>Rez No</th><th>Neden bakmalı</th></tr>" + trs + "</table>")
        else:
            bol2 = ""

        trs = ""
        for s in sat:
            durum = (tag("liste altı", "#dc2626") if s["rid"] in la_ids else "") + \
                (tag("dikkat", "#b45309") if s["nedenler"] and s["rid"] not in la_ids else "")
            trs += (f"<tr><td>{an_s(s['an'])}</td><td>{s['vardiya']}</td>"
                    f"<td><span class='who'>{esc(s['kim'])}</span></td><td class='r money'>{para(s['tutar'])}</td>"
                    f"<td>{esc(s['oda'] or '—')}</td><td>{esc(s['misafir'][:28])}</td>"
                    f"<td>{esc(s['kanal'] or ('acentasız' if s['rid'] else '—'))}</td>"
                    f"<td>{rez_link(s['rid'])}</td><td>{durum}</td></tr>")
        bol3 = ("<h2>Haftanın tüm nakit tahsilatları</h2>"
                "<p class='lead'>Saat sırasıyla, Ön Kasa defterindeki her nakit tahsilat (acenta rezervasyonları dahil).</p>"
                + ("<table><tr><th>Tarih · saat</th><th>Vardiya</th><th>Alan</th><th class='r'>Tutar</th><th>Oda</th>"
                   "<th>Misafir</th><th>Kanal</th><th>Rez No</th><th></th></tr>" + trs + "</table>"
                   if sat else "<p class='lead'>Bu hafta nakit tahsilat yok.</p>"))

        kisi = defaultdict(lambda: [0, 0, 0])
        for s in sat:
            k = kisi[s["kim"]]
            k[0] += 1
            k[1] += s["tutar"]
            k[2] += 1 if s["rid"] in la_ids else 0
        bol4 = ""
        if kisi:
            bol4 = ("<h2>Kim ne kadar nakit aldı</h2><table><tr><th>Kasada alan</th><th class='r'>Adet</th>"
                    "<th class='r'>Toplam</th><th class='r'>Liste altı</th></tr>"
                    + "".join(f"<tr><td><span class='who'>{esc(k)}</span></td><td class='r'>{v[0]}</td>"
                              f"<td class='r money'>{para(v[1])}</td>"
                              f"<td class='r {'miss' if v[2] else ''}'>{v[2]}</td></tr>"
                              for k, v in sorted(kisi.items(), key=lambda kv: -kv[1][1]))
                    + "</table>")
        ozet = dict(n=len(sat), toplam=toplam, la=len(la), la_fark=la_fark, diger=len(diger))
        etiket = f"{ad}: {bas.day} {TR_MONTHS[bas.month]} – {bit.day} {TR_MONTHS[bit.month]}"
        return etiket, ozet, f"<div class='stats'>{st}</div>{bol1}{bol2}{bol3}{bol4}"

    opts, panels, ozetler = "", "", {}
    for anahtar, ad, bas, bit in haftalar:
        etiket, oz, html_ = hafta_paneli(anahtar, ad, bas, bit)
        ozetler[anahtar] = (etiket, oz)
        opts += (f"<option value='{anahtar}'>{esc(etiket)} — {oz['la']} liste altı, {oz['diger']} dikkat</option>")
        panels += f"<div class='nkpanel' data-h='{anahtar}' style='display:none'>{html_}</div>"
    secici = ("<p class='lead' style='margin-top:4px'>Hafta seç:</p><select id='nkSel'>" + opts + "</select>"
              + panels +
              "<script>(function(){var s=document.getElementById('nkSel');"
              "function g(){var ps=document.querySelectorAll('.nkpanel');for(var i=0;i<ps.length;i++)"
              "{ps[i].style.display=ps[i].getAttribute('data-h')===s.value?'block':'none';}}"
              "s.addEventListener('change',g);g();})();</script>")
    k = veri["kaynak"]
    note = ("<div class='note'>Kaynak: Elektra Ön Kasa defteri (QA_EASYPMS_DAILYCASHDETAIL), yalnız <b>Folio Cash</b>. "
            "Saatler Türkiye saati (Elektra UTC tutuyor, +3 eklendi). Elektra tahsilatı <b>iş gününe</b> yazar — "
            "gece ve sabah tahsilatları bir önceki güne düşer; burada gerçek tarihe çevrildi "
            f"(saat bilgisinden {k['time']}, iş günü düzeltmesiyle {k['is_gunu']}, yalnız tarihli {k['tarih']}). "
            "Liste kıyası yalnız walk-in / telefon / acentasız satışlarda; acenta fiyatı kontrat fiyatıdır. "
            f"Fark {SATIS_PAYI} ₺'ye kadar kur yuvarlaması sayılır. Bakiyesi 0 olan bir satışta misafirden fazlası "
            "alınıp farkın cebe atılmasını sistem gösteremez — bu yüzden kamera kontrolü.</div>")
    fresh = ("<div style='background:#fef3c7;border:1px solid #fde68a;color:#92400e;padding:9px 13px;"
             f"border-radius:9px;margin:0 0 12px;font-size:12.5px'>⏱ Veriler <b>{now_str()}</b> itibarıyladır.</div>")
    etiket, gz = ozetler["gecen"]
    sub = (f"{etiket} · {gz['n']} nakit tahsilat {tl(gz['toplam'])[:-3]} ₺ · "
           f"{gz['la']} liste altı" + (f" ({tl(gz['la_fark'])[:-3]} ₺)" if gz["la"] else "")
           + f" · {gz['diger']} dikkat")
    return {"label": "Nakit Tahsilat Kontrol", "count": gz["la"],
            "count_label": "liste altı nakit (geçen hafta)", "tone": "bad" if gz["la"] else "ok",
            "sub": sub, "updated": now_str(),
            "html": PAGE("Denetim", "Nakit Tahsilat Kontrol",
                         "Nakit tahsilatlar — liste fiyatı altında kalanlar önce; kamera kontrolü için saatli",
                         fresh + secici + note + REZ_COPY_JS)}


# --------------------------------------------------------------------------- Bankadan ödenen vergiler
# 23.11.2026 (sahibi "yapalım"): Vergiler sayfasında "ödendi / ödenmedi" artık bankadan da
# okunur. Muhasebeci vergi ödemelerini banka açıklamasıyla işliyor: "VERGI-0015 KDV GERÇEK
# VD:…-THN:20261028…-VN:… RİVA OTEL…". Dört haneli kod vergi türüdür; THN'nin ilk 8 hanesi
# tahakkuk (beyan) tarihi = hangi ayın vergisi olduğu. SGK: "INTERNET SGK( EMS/BAĞ/SSK)/…".
# Açıklamada RİVA yoksa ödeme şahıs adınadır (sahibin Bağ-Kur'u, aile adına vergi/harç) —
# ayrı satırda gösterilir, şirket vergisine katılmaz.
VERGI_KOD = {"0015": "KDV-1", "4017": "KDV-2 (tevkifat)", "0003": "Muhtasar (stopaj)",
             "1047": "Damga vergisi", "1048": "Damga vergisi", "9047": "Damga vergisi",
             "0059": "Konaklama vergisi", "0068": "Turizm payı", "0033": "Geçici vergi",
             "0010": "Kurumlar vergisi", "9015": "MTV"}
VERGI_SIRA = ["KDV-1", "KDV-2 (tevkifat)", "Muhtasar (stopaj)", "Damga vergisi", "Konaklama vergisi",
              "Turizm payı", "Geçici vergi", "Kurumlar vergisi", "SGK primi", "MTV"]
_BANKA_CACHE = {}


def _banka_6ay(env):
    """Son GG_AY ayın banka (102) satırları, açılış/kapanış fişleri hariç, iç virmanlar
    işaretli. Gelir-Gider ve Vergiler aynı derlemede ikisi de ister: tek okuma."""
    today = dt.date.today()
    bas = month_start(today, GG_AY - 1)
    k = (bas, today)
    if k not in _BANKA_CACHE:
        rows = [r for r in _banka_satirlari(env, bas, today)
                if not _tr_has(r.get("RECEIPTNOTES"), ("KAPANIŞ", "AÇILIŞ", "KAPANIS", "ACILIS"))]
        _BANKA_CACHE[k] = _ic_virman_isaretle(rows)
    return _BANKA_CACHE[k]


def _vergi_odemeleri(rows):
    """Banka satırlarından vergi/SGK ödemeleri: [{d, ay, tur, tutar, sirket}].
    tutar > 0 = bankadan çıkan (ters kayıt eksi gelir, toplamda netleşir). ay = (yıl, ay):
    tahakkuk tarihi (THN) varsa onun ayı, yoksa banka tarihinin ayı."""
    import re
    out = []
    for r in rows:
        n = str(r.get("DETAILNOTES") or "")
        u = _fold(n)
        if u.startswith("VERGI-"):
            kod = u[6:10]
            tur = VERGI_KOD.get(kod) or (n[11:].split(" VD:")[0].strip().title()[:28] or "Diğer vergi")
        elif "SGK(" in u or "SGK (" in u:
            tur = "SGK primi"
        else:
            continue
        v = num(r.get("LOCALCREDIT")) - num(r.get("LOCALDEBIT"))
        d = pdate(r.get("RECEIPTDATE"))
        if not v or not d:
            continue
        sirket = "RIVA" in u
        if not sirket:
            tur = "Bağ-Kur (şahsi)" if tur == "SGK primi" else tur + " (şahıs adına)"
        thn = re.search(r"THN:(\d{4})(\d{2})(\d{2})", n)
        if thn:
            ay = (int(thn.group(1)), int(thn.group(2)))
        else:
            # SGK: vadesi ay sonu, hafta sonuna denk gelirse ertesi ayın ilk iş gününe kayar
            # (31.10.2026 Cmt → 02.11 Pzt). O güne kadarki ödeme ÖNCEKİ ayın borcudur.
            onceki_son = dt.date(d.year, d.month, 1) - dt.timedelta(days=1)
            ay = ((onceki_son.year, onceki_son.month) if d <= _is_gunu(onceki_son)
                  else (d.year, d.month))
        out.append({"d": d, "ay": ay, "tur": tur, "tutar": v, "sirket": sirket})
    return out


def _vergi_banka_tablo(banka, son_kayit):
    """Son 6 ay, tür × ay: bankadan gerçekten ödenen vergiler (BANKA TARİHİNE göre)."""
    today = dt.date.today()
    aylar = [month_start(today, GG_AY - 1 - i) for i in range(GG_AY)]
    akey = [(a.year, a.month) for a in aylar]
    tab = defaultdict(lambda: [0.0] * len(aylar))
    for p in banka:
        k = (p["d"].year, p["d"].month)
        if k in akey:
            tab[p["tur"]][akey.index(k)] += p["tutar"]
    sir = [t for t in VERGI_SIRA if t in tab] + sorted(
        t for t in tab if t not in VERGI_SIRA and "şahs" not in t and "şahıs" not in t)
    sah = sorted(t for t in tab if t not in sir)
    bas = "".join(f"<th class='r'>{esc(mlabel(k))}</th>" for k in akey)

    def satir(t):
        xs = tab[t]
        return (f"<tr><td>{esc(t)}</td>" + "".join(
            f"<td class='r'>{tl(x) if abs(x) >= 1 else '—'}</td>" for x in xs)
            + f"<td class='r money'>{tl(sum(xs))}</td></tr>")
    top = [sum(tab[t][j] for t in sir) for j in range(len(aylar))]
    html = (
        f"<h2>Bankadan ödenen vergiler — son {GG_AY} ay</h2>"
        "<p class='lead'>Muhasebecinin Elektra'ya işlediği banka hareketlerinden: vergi dairesine ve "
        "SGK'ya <b>gerçekten ödenen</b> tutarlar, ödeme gününün ayına göre. Son banka kaydı "
        f"<b>{_tr_d(son_kayit)}</b>; sonraki ödemeler henüz burada yok.</p>"
        f"<div class='scroll'><table><tr><th>Tür</th>{bas}<th class='r'>Toplam</th></tr>"
        + "".join(satir(t) for t in sir)
        + "<tr class='top'><td>Şirket toplamı</td>" + "".join(
            f"<td class='r money'>{tl(x)}</td>" for x in top) + f"<td class='r money'>{tl(sum(top))}</td></tr>")
    if sah:
        html += (f"<tr><th colspan='{len(aylar) + 2}'>Şahıs adına ödenenler (şirket vergisine "
                 "katılmadı)</th></tr>" + "".join(satir(t) for t in sah))
    return html + "</table></div>"
