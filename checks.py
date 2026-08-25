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
.wrap{max-width:960px;margin:0 auto}
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
    var s = sym(rec.currency);
    var out = "<div class='recon'><h3>"+(rec.currency==='TL'?'💳':(rec.currency==='EUR'?'💶':'💵'))
      + " POS / Kredi Kartı — "+curName(rec.currency);
    if(rec.hasEl){
      var diff = rec.elCardSum - rec.posComp, tol = Math.max(rec.elCardSum*0.05, rec.currency==='TL'?5000:150);
      if(diff <= tol) out += " <span class='pill ok'>✓ Tüm POS geçmiş</span></h3>"
        + "<p class='lead'>Karşılaştırılabilir günlerde bankaya geçen POS, Elektra'daki kart tahsilatını karşılıyor.</p>";
      else out += " <span class='pill warn'>⚠ "+f(diff)+" "+s+" eksik olabilir</span></h3>"
        + "<p class='lead'>Elektra'da <b>"+f(diff)+" "+s+"</b> kart tahsilatı var ama bankaya geçen POS'ta yok — incelenmeli.</p>";
      out += "<div class='stats'>"
        + "<div class='stat'><div class='n'>"+f(rec.elCardSum)+" "+s+"</div><div class='l'>Elektra kart (karşılaştırılan)</div></div>"
        + "<div class='stat'><div class='n'>"+f(rec.posComp)+" "+s+"</div><div class='l'>Banka POS (aynı günler, brüt)</div></div>"
        + "<div class='stat'><div class='n'>"+f(rec.posKs)+" "+s+"</div><div class='l'>banka komisyonu (toplam)</div></div></div>";
      var rowsH='';
      rec.tbl.forEach(function(t){
        if(t.unknown){
          rowsH += "<tr><td>"+trg(t.bankDay)+"</td><td class='muted'>"+trg(t.elDay)+"</td>"
            +"<td class='r muted'>—</td><td class='r money'>"+f(t.bankPos)+"</td>"
            +"<td class='r muted' title='Bu güne ait Elektra verisi yüklü aralıkta yok'>karşılaştırma dışı</td></tr>";
          return;
        }
        var cls=Math.abs(t.diff)<1?'ok':(Math.abs(t.diff)>=(rec.currency==='TL'?5000:100)?'amber':'');
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


def open_balances(env):
    """res-guest-balance-list (QA_HOTEL_RESERVATION_GUESTFOLIOS): folios that GENUINELY
    owe money, i.e. FOLIO_BALANCE > 0. This is the authoritative signal because the view
    already (a) consolidates FOLIO ROUTING — a reservation whose folio is routed to another
    shows 0, the target carries the combined balance — and (b) nets agency prepayments. So
    it catches what per-reservation GENERALBALANCE missed: agency-side debts and routed
    folios. _left=True when the guest checked out (RESSTATEID 4) still owing. Sorted:
    checked-out-owing first, then by amount. Shared by build_bakiye and build_odeme."""
    rows = E.fetch_guest_folios(env)
    owed = [r for r in rows if fbal(r) > 0.5]
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
    sub = (f"misafir {tl(total)} ₺ · cari {tl(cari_total)} ₺"
           + (f" · {len(left)} çıkıp borçlu 🔴" if left else ""))
    return {"label": "Bakiye Kontrolü", "count": len(owed) + len(cari),
            "count_label": "açık + cari", "tone": "bad" if (owed or cari) else "ok",
            "sub": sub, "updated": now_str(),
            "html": PAGE("Tahsilat — Açık Bakiye", "Bakiye Kontrolü",
                         "misafir açık bakiyeleri + cari alacaklar",
                         f"<div class='stats'>{stats}</div>{table}{cari_panel}{note}{REZ_COPY_JS}")}


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

    body = f"<div class='stats'>{stats}</div>{openpanel}{selector}{note}{REZ_COPY_JS}"
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
    kv_rows, onceki_vergi, kv_bugun = [], 0.0, None
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

    body = (f"<div class='stats'>{stats}</div>{kdv_tbl}{kv_tbl}{kirilim}{v360_tbl}{duzelt}{note}")
    return {"label": "Vergi Sayfası", "count": int(round(bu_ay["odenecek"] / 1000)),
            "count_label": "bin ₺ · bu ay KDV",
            "tone": "bad" if bu_ay["odenecek"] else "ok",
            "sub": (f"{TR_MON_FULL[today.month]} KDV {tl(bu_ay['odenecek'])} ₺ · "
                    f"{year} KDV {tl(kdv_yil)} ₺ · kurumlar v. matrahı {tl(max(0.0, y_gelir - y_indirim - y_gider + y_kkeg))} ₺"),
            "updated": now_str(),
            "html": PAGE("Muhasebe & Vergi", "Vergi Sayfası",
                         f"{year} · aylık KDV, konaklama vergisi ve kurumlar (geçici) vergisi",
                         body)}


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


# --------------------------------------------------------------------------- Parite (fiyat) — elle giriş
# OTA'lar kendi indirimlerini (Booking Genius, promosyon, mobil) OTA tarafında uygular;
# Elektra bunu görmez. Gerçek EKRAN fiyatını yakalamanın tek güvenilir yolu: kullanıcı
# gördüğü fiyatı girer. Her kanal "Aç →" ile açılır; kapıdandan ucuz OTA = parite ihlali.
# DOĞRUDAN otel sayfaları (arama değil) — tek tıkla otelin kendi ilanına gider.
# {ci}/{co} = bu gece → yarın (YYYY-AA-GG); {ci_d}/{co_d} aynı tarihler GG.AA.YYYY
# biçiminde (Türk OTA'ları böyle ister). JS bunları çalışma anında doldurur.
PARITE_CHANNELS = [
    ("kapidan", "🏠 Kapıdan (rezervasyonal)",
     "https://rivahotelalsancak.rezervasyonal.com/?Checkin={ci}&Checkout={co}&Adult=2&child=0&ChildAges=&language=tr"),
    ("booking", "Booking.com",
     "https://www.booking.com/hotel/tr/apart-alsancak.html?checkin={ci}&checkout={co}&group_adults=2&no_rooms=1&group_children=0"),
    ("hotels", "Hotels.com / Expedia",
     "https://tr.hotels.com/ho657763/hotel-apart-alsancak-izmir-turkiye/?chkin={ci}&chkout={co}&rm1=a2"),
    ("etstur", "Etstur",
     "https://www.etstur.com/Riva-Hotel-Alsancak?check_in={ci_d}&check_out={co_d}&adult_1=2&child_1=0"),
    ("tatilsepeti", "Tatilsepeti",
     "https://www.tatilsepeti.com/riva-hotel-alsancak?ara=oda:2;tarih:{ci_d},{co_d}"),
    ("enuygun", "Enuygun",
     "https://www.enuygun.com/otel/detay/riva-hotel-alsancak-428633/?checkInDate={ci_d}&checkOutDate={co_d}&rooms=2"),
    ("tatilbudur", "Tatilbudur",
     "https://www.tatilbudur.com/riva-hotel-alsancak"),
    ("obilet", "Obilet",
     "https://www.obilet.com/otel-detay/riva-hotel-alsancak-751493/{ci_c}-{co_c}/2ad"),
    ("tripcom", "Trip.com",
     "https://tr.trip.com/hotels/detail/?city=1216&hotelid=102583877&checkin={ci}&checkout={co}&adult=2&crn=1&curr=TRY&locale=tr_TR"),
    ("trivago", "Trivago",
     "https://www.trivago.com.tr/tr/lm/konaklama-hizmeti-verilen-apart-daire-riva-hotel-alsancak-izmir"),
]


def build_parite(env):
    """Parite Kontrolü — kullanıcı her kanalda GÖRDÜĞÜ gerçek fiyatı (Genius/indirim dahil)
    girer. Kapıdandan ucuz satan OTA parite ihlali (kırmızı); en ucuz yeşil. Girilen
    fiyatlar tarayıcıda gün gün saklanır. OTA'ların kendi indirimlerini Elektra göremediği
    için gerçek ekran fiyatını yakalamanın tek güvenilir yolu budur."""
    ch_js = json.dumps([{"key": k, "name": n, "url": u} for k, n, u in PARITE_CHANNELS],
                       ensure_ascii=False)
    body = f"""
    <p class='lead'>Baz: <b>bu gece · 2 kişi · Standart Stüdyo (mutfaklı)</b>. Her kanalın
    <b>Aç →</b> linkine tıkla, <b>gördüğün gerçek fiyatı</b> (Genius/indirim dahil) yaz.
    🔴 <b>kapıdandan ucuz</b> satan OTA = parite ihlali · 🟢 en ucuz.</p>
    <div class='stats' id='psum'></div>
    <table><tr><th>Kanal</th><th></th><th class='r'>Gördüğün fiyat (₺)</th></tr>
      <tbody id='prows'></tbody></table>
    <div class='note'>Girdiğin fiyatlar bu tarayıcıda, gün gün saklanır. OTA'ların Genius/promosyon
    indirimleri OTA tarafında olur; Elektra göremez — o yüzden gerçek fiyatı sen girersin.</div>
    <script>
    (function(){{
      var CH={ch_js};
      function pad(n){{return(n<10?'0':'')+n;}}
      var now=new Date(),tom=new Date(Date.now()+864e5);
      var ci=now.getFullYear()+'-'+pad(now.getMonth()+1)+'-'+pad(now.getDate());
      var co=tom.getFullYear()+'-'+pad(tom.getMonth()+1)+'-'+pad(tom.getDate());
      var ci_d=pad(now.getDate())+'.'+pad(now.getMonth()+1)+'.'+now.getFullYear();
      var co_d=pad(tom.getDate())+'.'+pad(tom.getMonth()+1)+'.'+tom.getFullYear();
      var ci_c=now.getFullYear()+pad(now.getMonth()+1)+pad(now.getDate());
      var co_c=tom.getFullYear()+pad(tom.getMonth()+1)+pad(tom.getDate());
      // Uzun jetonları (ci_d/co_d/ci_c/co_c) önce değiştir ki {{ci}} onların içine denk gelmesin.
      function chUrl(c){{return c.url.replace('{{ci_d}}',ci_d).replace('{{co_d}}',co_d).replace('{{ci_c}}',ci_c).replace('{{co_c}}',co_c).replace('{{ci}}',ci).replace('{{co}}',co);}}
      // Kanal adı = otelin ilanına giden link (Aç → ile aynı hedef).
      function nameHtml(c){{return '<a href="'+chUrl(c)+'" target="_blank" rel="noopener" title="'+c.name+' — otelin ilanını aç" style="color:inherit;text-decoration:none;border-bottom:1px solid var(--brand,#0e7490);font-weight:600">'+c.name+'</a>';}}
      var KEY='parite-'+ci;
      var saved={{}}; try{{saved=JSON.parse(localStorage.getItem(KEY)||'{{}}');}}catch(e){{}}
      var rows=document.getElementById('prows');
      CH.forEach(function(c){{
        var tr=document.createElement('tr'); tr.id='row-'+c.key;
        tr.innerHTML='<td class="pn">'+nameHtml(c)+'</td>'+
          '<td><a href="'+chUrl(c)+'" target="_blank" rel="noopener" style="color:var(--brand,#0e7490);font-weight:600">Aç →</a></td>'+
          '<td class="r"><input type="number" inputmode="decimal" data-k="'+c.key+'" placeholder="—" '+
          'style="width:130px;text-align:right;padding:7px 9px;border:1px solid #cbd5e1;border-radius:8px;font:inherit"'+
          (saved[c.key]!=null?' value="'+saved[c.key]+'"':'')+'></td>';
        rows.appendChild(tr);
      }});
      function tl(n){{return(Math.round(n*100)/100).toLocaleString('tr-TR',{{minimumFractionDigits:2}});}}
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
          var tr=document.getElementById('row-'+c.key); var v=vals[c.key]; tr.className='';
          var td=tr.querySelector('.pn'); td.innerHTML=nameHtml(c);
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
    return {"label": "Parite Kontrolü", "count": 0, "count_label": "gerçek fiyat gir",
            "tone": "ok", "sub": "her kanalda gördüğün fiyatı gir · kapıdandan ucuz = ihlal",
            "updated": now_str(),
            "html": PAGE("Fiyat / Parite", "Parite Kontrolü",
                         "gördüğün gerçek fiyatları gir (Genius/indirim dahil)", body)}


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
.tabs{display:flex;gap:4px;flex-wrap:wrap;border-bottom:2px solid var(--border);margin:18px 0 0}
.tab{border:0;background:none;color:var(--sub);font:inherit;font-weight:700;font-size:13px;
  padding:10px 14px;border-radius:9px 9px 0 0;cursor:pointer;position:relative;top:2px;white-space:nowrap}
.tab:hover{color:var(--fg)}
.tab.active{color:var(--eyebrow);border-bottom:2px solid var(--eyebrow);background:var(--card)}
.tab .cnt{display:inline-block;background:var(--statbad);color:#fff;border-radius:999px;
  font-size:10.5px;padding:0 6px;margin-left:5px;font-weight:800;vertical-align:1px}
.panel{display:none;padding-top:14px}.panel.active{display:block}
.mono{font-family:ui-monospace,Menlo,monospace}
.chg{font-family:ui-monospace,Menlo,monospace;font-weight:700}.chg .arw{color:var(--eyebrow);padding:0 4px}
.reason-none{color:var(--statbad);font-weight:600}
td textarea{width:100%;min-height:38px;font:inherit;font-size:12.5px;padding:7px 9px;
  border:1px solid var(--input-line);border-radius:8px;background:var(--input-bg);color:var(--fg);resize:vertical}
td textarea:focus{border-color:var(--eyebrow);outline:none}
td input[type=checkbox]{width:auto;transform:scale(1.35);cursor:pointer;accent-color:var(--eyebrow)}
.addbar{display:flex;gap:8px;align-items:center;margin:2px 0 10px;flex-wrap:wrap}
.addbar input{flex:1;min-width:120px}
.saverow{display:flex;align-items:center;gap:12px;margin:8px 0 6px}
.btn{font:inherit;font-weight:700;padding:9px 18px;border-radius:10px;border:1px solid var(--eyebrow);
  background:var(--eyebrow);color:#fff;cursor:pointer}
.btn.ghost{background:transparent;color:var(--eyebrow)}
.saved{color:var(--statok);font-weight:700;font-size:13px;opacity:0;transition:opacity .2s}
.saved.show{opacity:1}
.ph{background:var(--card);border:1px dashed var(--border);border-radius:12px;padding:24px;
  text-align:center;color:var(--sub);font-size:13px}
.rowdel{border:0;background:none;color:var(--statbad);cursor:pointer;font-size:15px;padding:2px 6px}
</style>"""
GUNLUK_JS = r"""<script>
(function(){
  var D = window.__GUNLUK__ || {days:{},openbal:[],cari:[],today:''};
  var alldays = Object.keys(D.days).sort();
  var cur = (D.today && D.days[D.today]) ? D.today : (alldays[alldays.length-1] || D.today);
  var curTab = 'rc';
  function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c];});}
  function money(n){return (Math.round((+n||0)*100)/100).toLocaleString('tr-TR',{minimumFractionDigits:2,maximumFractionDigits:2});}
  var MON=['','Oca','Şub','Mar','Nis','May','Haz','Tem','Ağu','Eyl','Eki','Kas','Ara'];
  var DOW=['Paz','Pzt','Sal','Çar','Per','Cum','Cmt'];
  function fday(iso){var p=iso.split('-');return (+p[2])+' '+MON[+p[1]]+' '+p[0];}
  function dow(iso){var p=iso.split('-');return DOW[new Date(Date.UTC(+p[0],+p[1]-1,+p[2])).getUTCDay()];}
  // ---- storage (v1: tarayıcı; sonra buluta taşınır) ----
  function sset(k,v){try{localStorage.setItem(k,v);}catch(e){}}
  function sget(k){try{return localStorage.getItem(k)||'';}catch(e){return '';}}
  function K(tab,row){return 'RG:'+cur+':'+tab+':'+row;}
  function listKey(tab){return 'RG:'+cur+':'+tab;}
  function loadList(tab){try{var s=localStorage.getItem(listKey(tab));return s?JSON.parse(s):[];}catch(e){return [];}}
  function saveList(tab,a){sset(listKey(tab),JSON.stringify(a));}
  function note(tab,row){return "<td><textarea data-k='"+K(tab,row)+"' placeholder='(açıklama gir)'>"+esc(sget(K(tab,row)))+"</textarea></td>";}
  function savebar(tab){return "<div class='saverow'><button class='btn' data-save>💾 Kaydet</button>"
    +"<span class='saved' data-savedmsg>✓ kaydedildi</span></div>";}

  // ---- panel içerikleri ----
  function pRC(){
    var rows=(D.days[cur]||{}).rc||[];
    if(!rows.length) return "<h2>Oda Değişimleri — "+fday(cur)+"</h2><div class='ph'>Bu gün oda değişimi yok.</div>";
    var h="<h2>Oda Değişimleri — "+fday(cur)+"</h2>"
      +"<p class='lead'><b>Neden</b> Elektra Oda Notu'ndan okunur; boşsa <span class='reason-none'>⚠ girilmemiş</span>. En sağda müdür açıklaması — otomatik saklanır.</p>"
      +"<table><thead><tr><th>Saat</th><th>Misafir</th><th>Oda Değişimi</th><th>Yapan</th><th>Neden (Oda Notu)</th><th style='width:26%'>Müdür açıklaması</th></tr></thead><tbody>";
    rows.forEach(function(r,i){
      var reason=r.reason?"<span>"+esc(r.reason)+"</span>":"<span class='reason-none'>⚠ girilmemiş</span>";
      h+="<tr><td class='mono'>"+esc(r.saat)+"</td><td>"+esc(r.guest)+"</td>"
        +"<td class='chg'>"+esc(r.from)+"<span class='arw'>→</span>"+esc(r.to)+"</td>"
        +"<td>"+esc(r.user)+"</td><td>"+reason+"</td>"+note('rc','rc'+i)+"</tr>";
    });
    return h+"</tbody></table>"+savebar('rc');
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
  function pProb(tab,title){
    var a=loadList(tab);
    var h="<h2>"+title+" — "+fday(cur)+"</h2>"
      +"<p class='lead'>Oda no + problem yaz, <b>+ Ekle</b>; açıklamayı yaz; <b>Kaydet</b>. Otomatik da saklanır.</p>"
      +"<table><thead><tr><th style='width:90px'>Oda</th><th>Problem</th><th style='width:34%'>Müdür açıklama</th><th style='width:34px'></th></tr></thead><tbody data-list='"+tab+"'>";
    a.forEach(function(r,i){
      h+="<tr><td><input data-f='oda' data-i='"+i+"' value='"+esc(r.oda)+"' style='max-width:80px'></td>"
        +"<td><input data-f='problem' data-i='"+i+"' value='"+esc(r.problem)+"'></td>"
        +"<td><textarea data-f='note' data-i='"+i+"'>"+esc(r.note||'')+"</textarea></td>"
        +"<td><button class='rowdel' data-del='"+i+"' title='sil'>✕</button></td></tr>";
    });
    if(!a.length) h+="<tr><td colspan='4' class='sub' style='padding:14px;color:var(--sub)'>Henüz kayıt yok — alttan ekle.</td></tr>";
    h+="</tbody></table>"
      +"<div class='addbar'><input data-add='oda' placeholder='Oda no' style='max-width:120px'>"
      +"<input data-add='problem' placeholder='Problem'>"
      +"<button class='btn ghost' data-addbtn='"+tab+"'>+ Ekle</button></div>"+savebar(tab);
    return h;
  }
  function pYorum(){
    var rows=(D.days[cur]||{}).dep||[];
    if(!rows.length) return "<h2>İstenilen Yorumlar</h2><div class='ph'>Bu gün çıkış yok.</div>";
    var h="<h2>İstenilen Yorumlar — çıkış yapan misafirler ("+fday(cur)+")</h2>"
      +"<p class='lead'>O günün çıkışları. Yorum karşılığı <b>%10 indirim</b> vereceğin misafiri işaretle, <b>yorumunu</b> yaz.</p>"
      +"<table><thead><tr><th>Oda</th><th>Misafir</th><th style='text-align:center;width:100px'>%10 indirim</th><th style='width:44%'>Misafir yorumu</th></tr></thead><tbody>";
    rows.forEach(function(r,i){
      var ck=sget(K('yind',i+'@'+cur))==='1'?'checked':'';
      h+="<tr><td class='mono'>"+esc(r.room)+"</td><td>"+esc(r.guest)+"</td>"
        +"<td style='text-align:center'><input type='checkbox' data-ck='"+K('yind',i+'@'+cur)+"' "+ck+"></td>"
        +"<td><textarea data-k='"+K('yyor',i+'@'+cur)+"'>"+esc(sget(K('yyor',i+'@'+cur)))+"</textarea></td></tr>";
    });
    return h+"</tbody></table>"+savebar('yorum');
  }
  var TABS=[
    {k:'rc',   t:'Oda Değişimleri', cnt:function(){return ((D.days[cur]||{}).rc||[]).filter(function(x){return !x.reason;}).length;}, f:pRC},
    {k:'bal',  t:'Açık Bakiyeler',  cnt:function(){return (D.openbal||[]).length;}, f:pBal},
    {k:'cari', t:'Açık Cariler',    cnt:function(){return (D.cari||[]).length;}, f:pCari},
    {k:'odap', t:'Oda Problemleri', cnt:function(){return loadList('odap').length;}, f:function(){return pProb('odap','Oda Problemleri');}},
    {k:'temp', t:'Temizlik Problemleri', cnt:function(){return loadList('temp').length;}, f:function(){return pProb('temp','Temizlik Problemleri');}},
    {k:'yorum',t:'İstenilen Yorumlar', cnt:function(){return 0;}, f:pYorum}
  ];
  // ---- render ----
  function renderTabs(){
    document.getElementById('tabs').innerHTML=TABS.map(function(tb){
      var c=tb.cnt(); var b=c>0?" <span class='cnt'>"+c+"</span>":"";
      return "<button class='tab"+(tb.k===curTab?" active":"")+"' data-tab='"+tb.k+"'>"+tb.t+b+"</button>";
    }).join('');
  }
  function renderPanel(){
    var tb=TABS.filter(function(x){return x.k===curTab;})[0]||TABS[0];
    document.getElementById('panels').innerHTML="<div class='panel active'>"+tb.f()+"</div>";
  }
  function renderDay(){
    var el=document.getElementById('curday');
    el.innerHTML=esc(fday(cur))+"<small>"+esc(dow(cur))+"</small>";
    var i=alldays.indexOf(cur);
    document.getElementById('dprev').disabled=(i<=0);
    document.getElementById('dnext').disabled=(i>=alldays.length-1);
  }
  function full(){renderDay();renderTabs();renderPanel();}
  // ---- events ----
  document.getElementById('dprev').onclick=function(){var i=alldays.indexOf(cur);if(i>0){cur=alldays[i-1];full();}};
  document.getElementById('dnext').onclick=function(){var i=alldays.indexOf(cur);if(i<alldays.length-1){cur=alldays[i+1];full();}};
  document.getElementById('tabs').addEventListener('click',function(e){var b=e.target.closest('[data-tab]');if(b){curTab=b.getAttribute('data-tab');renderTabs();renderPanel();}});
  // otomatik kayıt (textarea[data-k], checkbox[data-ck]) + problem listeleri
  document.getElementById('panels').addEventListener('input',function(e){
    var t=e.target;
    if(t.hasAttribute&&t.hasAttribute('data-k')) sset(t.getAttribute('data-k'),t.value);
    var f=t.getAttribute&&t.getAttribute('data-f');
    if(f){ var tbody=t.closest('[data-list]'); if(tbody){var tab=tbody.getAttribute('data-list');var a=loadList(tab);var i=+t.getAttribute('data-i');if(a[i]){a[i][f]=t.value;saveList(tab,a);}} }
  });
  document.getElementById('panels').addEventListener('change',function(e){
    var t=e.target; if(t.hasAttribute&&t.hasAttribute('data-ck')) sset(t.getAttribute('data-ck'),t.checked?'1':'0');
  });
  document.getElementById('panels').addEventListener('click',function(e){
    var add=e.target.closest('[data-addbtn]');
    if(add){var tab=add.getAttribute('data-addbtn');var box=add.parentNode;
      var oda=box.querySelector("[data-add='oda']").value.trim(), prob=box.querySelector("[data-add='problem']").value.trim();
      if(!oda&&!prob)return; var a=loadList(tab);a.push({oda:oda,problem:prob,note:''});saveList(tab,a);renderTabs();renderPanel();return;}
    var del=e.target.closest('[data-del]');
    if(del){var tbody=del.closest('[data-list]');var tab=tbody.getAttribute('data-list');var a=loadList(tab);a.splice(+del.getAttribute('data-del'),1);saveList(tab,a);renderPanel();renderTabs();return;}
    var sv=e.target.closest('[data-save]');
    if(sv){var m=sv.parentNode.querySelector('[data-savedmsg]');if(m){m.classList.add('show');setTimeout(function(){m.classList.remove('show');},1400);}}
  });
  full();
})();
</script>"""


def build_gunluk(env):
    today = dt.date.today()
    start = today - dt.timedelta(days=13)          # son 14 gün
    changes = E.fetch_room_changes(start.isoformat(), today.isoformat(), env=env)
    notes = E.fetch_notes({c["rez_id"] for c in changes if c["rez_id"]}, env=env) if changes else {}
    deps = E.fetch_departed_range(start.isoformat(), today.isoformat(), env=env)
    owed = open_balances(env)
    cari = cari_receivables(env)

    days = OrderedDict()
    d = start
    while d <= today:
        days[d.isoformat()] = {"rc": [], "dep": []}
        d += dt.timedelta(days=1)
    for c in changes:
        day = c["when"][:10]
        if day in days:
            days[day]["rc"].append({"saat": c["when"][11:16], "guest": c["guest"],
                                    "from": c["from_room"], "to": c["to_room"],
                                    "user": c["user"], "reason": notes.get(c["rez_id"], "")})
    for r in deps:
        day = str(r.get("checkout") or "")[:10]
        if day in days:
            days[day]["dep"].append({"room": r.get("room") or "",
                                     "guest": (r.get("guest") or "")[:40],
                                     "agency": (r.get("agency") or "")[:20]})
    ob = [{"rezid": str(r.get("RESID") or ""), "room": r.get("ROOMNO") or "",
           "guest": (r.get("GUESTNAMES") or "")[:34], "agency": (r.get("AGENCY") or "")[:16],
           "left": bool(r.get("_left")), "borc": round(fbal(r), 2)} for r in owed]
    cr = [{"kod": r.get("CODE") or "", "name": (r.get("NAME") or "")[:36],
           "alacak": round(num(r.get("LOCALBALANCE")), 2)} for r in cari]

    data = {"today": today.isoformat(), "days": days, "openbal": ob, "cari": cr}
    skeleton = (
        "<div class='topbar'><div class='daynav'>"
        "<button id='dprev' title='önceki gün'>‹</button>"
        "<div class='cur' id='curday'>—</div>"
        "<button id='dnext' title='sonraki gün'>›</button></div>"
        "<div><div class='eyebrow'>Riva Hotel Alsancak · Günlük Defter</div>"
        "<h1 style='margin:2px 0 0'>Günlük Rapor</h1></div></div>"
        "<div class='sub'>Seçilen günün olayları + müdürün açıklamaları. Girilenler otomatik saklanır.</div>"
        "<div class='tabs' id='tabs'></div>"
        "<div id='panels'></div>")
    body = (GUNLUK_CSS + skeleton + "<script>window.__GUNLUK__="
            + json.dumps(data, ensure_ascii=False, default=str) + ";</script>" + GUNLUK_JS)
    n_open = len(ob)
    left = sum(1 for r in ob if r["left"])
    return {"label": "Günlük Rapor", "count": n_open, "count_label": "açık bakiye",
            "tone": "bad" if (n_open or left) else "ok",
            "sub": f"günlük defter · {tr_g(today)} · {len(changes)} oda değişimi (14g)",
            "updated": now_str(),
            "html": PAGE("Günlük Defter", "Günlük Rapor",
                         f"gün seçici + oda değişimleri, açık bakiye/cari, problemler, yorumlar", body)}
