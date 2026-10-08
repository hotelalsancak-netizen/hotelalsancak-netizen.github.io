#!/usr/bin/env python3
"""
Oda TV kartları — Next uydu alıcısı + odadaki TV kumandası için kullanım kartı.

Her TV kumandası modeli için ayrı bir A6 kart üretir (PDF + PNG) ve dördünü tek
A4'e dizen baskı sayfası. Görseller img/ altında; tuş konumları aşağıdaki KUMANDALAR
tablosunda, kumanda görselinin genişlik/yükseklik KESRİ olarak tutulur.

Çalıştırma:  python3 kartlar/tv-kumanda/uret.py      (chromium gerekir)
"""
import pathlib, subprocess, shutil, json, datetime

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE

# oran = kesilmiş kumanda görselinin genişlik/yükseklik oranı
# fx, fy = tuş merkezinin görsel içindeki konumu (0..1)
NEXT = {"img": "kumanda-N_next.png", "zoom": "zoom-N_next.jpg",
        "oran": 1050 / 3895, "fx": 0.667, "fy": 0.040}

KUMANDALAR = [
    {"kod": "A", "ad": "Beko · gri", "dosya": "kart-A-beko-gri",
     "img": "kumanda-A_beko_gri.png", "zoom": "zoom-A_beko_gri.jpg",
     "oran": 789 / 3222, "fx": 0.531, "fy": 0.080, "tus": "ikon"},
    {"kod": "B", "ad": "Beko · uzun siyah", "dosya": "kart-B-beko-uzun-siyah",
     "img": "kumanda-B_beko_uzun.png", "zoom": "zoom-B_beko_uzun.jpg",
     "oran": 1000 / 3787, "fx": 0.491, "fy": 0.541, "tus": "ikon"},
    {"kod": "C", "ad": "Beko · küçük siyah", "dosya": "kart-C-beko-kucuk-siyah",
     "img": "kumanda-C_beko_kucuk.png", "zoom": "zoom-C_beko_kucuk.jpg",
     "oran": 805 / 3156, "fx": 0.773, "fy": 0.158, "tus": "ikon"},
    {"kod": "D", "ad": "Awox", "dosya": "kart-D-awox",
     "img": "kumanda-D_awox.png", "zoom": "zoom-D_awox.jpg",
     "oran": 1073 / 3423, "fx": 0.260, "fy": 0.315, "tus": "source"},
]

# Beko kumandalarındaki giriş (source) tuşunun simgesi
IKON = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M9 5h10a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H9" fill="none" stroke="currentColor" stroke-width="2.2"/>'
        '<path d="M3 12h10m-3.5-3.6L13 12l-3.5 3.6" fill="none" stroke="currentColor" stroke-width="2.2" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg>')
GUC = ('<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">'
       '<path d="M12 3v8" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/>'
       '<path d="M7.2 6.4a7.5 7.5 0 1 0 9.6 0" fill="none" stroke="currentColor" stroke-width="2.6" '
       'stroke-linecap="round"/></svg>')

# ---- figür geometrisi (mm) -------------------------------------------------
FW, FH = 44.0, 55.0      # figür kutusu
RH = 53.5                # kumanda görsel yüksekliği
D = 14.5                 # büyüteç çapı
GAP = 3.2                # kumanda ile büyüteç arası
R = 2.9                  # tuş halkası yarıçapı


def figur(k):
    rw = k["oran"] * RH
    grp = rw + GAP + D
    sol = k["fx"] < 0.42                       # tuş solda ise büyüteç de solda
    if sol:
        lx = (FW - grp) / 2; rx = lx + D + GAP
    else:
        rx = (FW - grp) / 2; lx = rx + rw + GAP
    ry = (FH - RH) / 2
    bx, by = rx + k["fx"] * rw, ry + k["fy"] * RH
    lcx = lx + D / 2
    lcy = min(max(by, D / 2 + 0.6), FH - D / 2 - 0.6)
    # bağlantı çizgisi: halkanın kenarından büyütecin kenarına
    dx, dy = lcx - bx, lcy - by
    L = (dx * dx + dy * dy) ** 0.5 or 1
    x1, y1 = bx + dx / L * (R + 0.4), by + dy / L * (R + 0.4)
    x2, y2 = lcx - dx / L * (D / 2 + 0.3), lcy - dy / L * (D / 2 + 0.3)
    f = lambda v: f"{v:.2f}"
    return f"""
      <div class="fig">
        <img class="rem" src="img/{k['img']}" alt="" style="left:{f(rx)}mm;top:{f(ry)}mm;height:{f(RH)}mm">
        <svg class="ov" viewBox="0 0 {FW} {FH}" width="{FW}mm" height="{FH}mm" aria-hidden="true">
          <line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" stroke="#fff" stroke-width="1.1" stroke-linecap="round"/>
          <line x1="{f(x1)}" y1="{f(y1)}" x2="{f(x2)}" y2="{f(y2)}" class="red" stroke-width="0.5" stroke-linecap="round"/>
          <circle cx="{f(bx)}" cy="{f(by)}" r="{R}" fill="none" stroke="#fff" stroke-width="1.3"/>
          <circle cx="{f(bx)}" cy="{f(by)}" r="{R}" fill="none" class="red" stroke-width="0.65"/>
        </svg>
        <img class="lens" src="img/{k['zoom']}" alt="" style="left:{f(lx)}mm;top:{f(lcy - D/2)}mm;width:{D}mm;height:{D}mm">
      </div>"""


CSS = """
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap');
:root{--ink:#151515;--mut:#6b6b6b;--rule:#e3e3e3;--red:#d9232d;--soft:#f4f3f1;--paper:#fff}
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
html,body{margin:0;padding:0;background:var(--paper)}
body{font-family:"Poppins",system-ui,sans-serif;color:var(--ink)}
.card{width:105mm;height:148mm;padding:6.2mm 6.4mm 5mm;display:flex;flex-direction:column;
  background:var(--paper);position:relative;overflow:hidden}
header{flex:none;text-align:center;padding-bottom:2.6mm;border-bottom:0.3mm solid var(--ink)}
h1{font-size:12.4pt;font-weight:600;letter-spacing:.03em;margin:0;line-height:1.15}
header .en{font-size:7.4pt;color:var(--mut);margin:.6mm 0 0;letter-spacing:.02em}
.steps{display:grid;grid-template-columns:1fr 0.25mm 1fr;column-gap:2.4mm;margin-top:3mm;flex:1;min-height:0}
.vr{background:var(--rule)}
.step{display:flex;flex-direction:column;min-width:0}
.sh{display:flex;align-items:center;gap:1.6mm}
.num{width:5.4mm;height:5.4mm;border-radius:50%;border:0.45mm solid var(--red);color:var(--red);
  display:flex;align-items:center;justify-content:center;font-weight:700;font-size:8.4pt;line-height:1;flex:none}
.lbl{font-size:6.1pt;font-weight:600;letter-spacing:.14em;color:var(--red)}
h2{font-size:9.3pt;font-weight:600;margin:1.6mm 0 0;line-height:1.2}
.tr{font-size:6.9pt;line-height:1.38;margin:1mm 0 0}
.tr b{font-weight:600}
.step .en{font-size:6.2pt;line-height:1.35;color:var(--mut);margin:.7mm 0 0}
.fig{position:relative;width:44mm;height:55mm;margin:2mm auto 0;flex:none}
.rem{position:absolute;width:auto;filter:drop-shadow(0 .5mm .7mm rgba(0,0,0,.28))}
.ov{position:absolute;left:0;top:0;overflow:visible}
.red{stroke:var(--red)}
.lens{position:absolute;border-radius:50%;object-fit:cover;border:0.6mm solid var(--red);
  box-shadow:0 0 0 0.5mm #fff,0 .6mm 1.4mm rgba(0,0,0,.3)}
.keys{display:flex;align-items:center;justify-content:center;gap:1.1mm;margin-top:2mm;
  font-size:6.6pt;font-weight:600}
.key{display:inline-flex;align-items:center;justify-content:center;gap:.6mm;min-width:6mm;height:4.6mm;
  padding:0 1.5mm;border-radius:1.2mm;background:var(--ink);color:#fff;letter-spacing:.03em}
.key.pwr{background:var(--red);border-radius:50%;min-width:4.8mm;width:4.8mm;height:4.8mm;padding:0}
.key .ico{width:3.3mm;height:3.3mm}
.arr{color:var(--mut);font-weight:500}
.keyname{font-size:6.2pt;color:var(--mut);font-weight:500;margin-left:.6mm}
.s3{flex:none;display:flex;align-items:center;gap:2.2mm;background:var(--soft);border-radius:2mm;
  padding:2.2mm 3mm;margin-top:3mm}
.s3 p{margin:0;font-size:6.9pt;line-height:1.38}
.s3 b{font-weight:600}
.s3 .en{color:var(--mut);font-size:6.2pt}
footer{flex:none;display:flex;flex-direction:column;align-items:center;gap:1mm;margin-top:3.2mm}
footer img{width:26mm;height:auto;display:block}
footer p{margin:0;font-size:6.8pt;font-weight:500;letter-spacing:.02em}
footer p span{color:var(--mut);font-weight:400}
.code{position:absolute;right:4.2mm;bottom:3.2mm;font-size:5pt;color:#b5b5b5;letter-spacing:.06em}
"""


def kart(k):
    if k["tus"] == "ikon":
        tus_tr, tus_en = "giriş", "input"
        k1 = f'<span class="key">{IKON}</span>'
    else:
        tus_tr, tus_en = "<b>SOURCE</b>", "SOURCE"
        k1 = '<span class="key">SOURCE</span>'
    return f"""
<div class="card">
  <header>
    <h1>TELEVİZYON NASIL İZLENİR?</h1>
    <p class="en">How to watch TV</p>
  </header>
  <div class="steps">
    <section class="step">
      <div class="sh"><span class="num">1</span><span class="lbl">ADIM · STEP</span></div>
      <h2>Uydu alıcısını açın</h2>
      <p class="tr"><b>Next</b> kumandasındaki <b>kırmızı</b> tuşa basın.</p>
      <p class="en">Press the red button on the Next remote.</p>
      {figur(NEXT)}
      <div class="keys"><span class="key pwr">{GUC}</span><span class="keyname">Next kumandası</span></div>
    </section>
    <div class="vr"></div>
    <section class="step">
      <div class="sh"><span class="num">2</span><span class="lbl">ADIM · STEP</span></div>
      <h2>TV'de HDMI 1'i seçin</h2>
      <p class="tr"><b>TV</b> kumandasında {tus_tr} tuşuna basın, <b>HDMI 1</b>'i seçip <b>OK</b>'a basın.</p>
      <p class="en">Press {tus_en} on the TV remote, pick HDMI 1, press OK.</p>
      {figur(k)}
      <div class="keys">{k1}<span class="arr">›</span><span class="key">HDMI 1</span><span class="arr">›</span><span class="key">OK</span></div>
    </section>
  </div>
  <div class="s3">
    <span class="num">3</span>
    <p><b>Kanal ve sesi artık Next kumandasıyla değiştirin.</b><br>
       <span class="en">Then use the Next remote for channels and volume.</span></p>
  </div>
  <footer>
    <img src="img/riva-logo.png" alt="Riva Hotel Alsancak">
    <p>Keyifli seyirler! <span>· Enjoy watching!</span></p>
  </footer>
  <div class="code">{k['kod']} · {k['ad']}</div>
</div>"""


def sayfa(govde, boyut, ek_css=""):
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<title>TV kartı</title><style>{CSS}
@page{{size:{boyut};margin:0}}{ek_css}</style></head><body>{govde}</body></html>"""


def chromium():
    for b in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(b):
            return b
    raise SystemExit("chromium bulunamadı")


def render(html_path, pdf_path, png_path=None):
    b = chromium()
    base = [b, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            "--virtual-time-budget=12000", "--run-all-compositor-stages-before-draw"]
    subprocess.run(base + ["--no-pdf-header-footer", f"--print-to-pdf={pdf_path}",
                           html_path.as_uri()], check=True, capture_output=True)
    if png_path:
        # PNG'yi PDF'ten üret (400 dpi): ekran görüntüsü penceresi kartı kırpabiliyordu,
        # böylece PNG her zaman PDF'in birebir aynısı olur.
        stem = str(png_path)[:-4]
        subprocess.run(["pdftoppm", "-r", "400", "-png", "-singlefile", str(pdf_path), stem],
                       check=True)


# ---- matbaa: A6 + 3 mm taşma payı + kesim işaretleri ----------------------
# Sayfa = kesim boyu + her yanda 10 mm (3 mm taşma + işaret/künye alanı). Kart zemini
# beyaz ve kenara dayanan öğe yok, bu yüzden taşma payı beyaz kalır; işaretler kesim
# çizgisinin 3 mm dışından başlar ki bıçak kaysa da kartın üstüne çıkmasın.
MB_PAY, MB_TASMA = 10.0, 3.0
MB_CSS = """
.mb{position:relative;width:125mm;height:168mm;background:#fff}
.mb .card{position:absolute;left:10mm;top:10mm}
.cm{position:absolute;background:#000}
.cm.h{height:.09mm;width:7mm}.cm.v{width:.09mm;height:7mm}
.slug{position:absolute;left:0;right:0;bottom:2.6mm;text-align:center;font-size:5pt;color:#888;
  letter-spacing:.04em}"""


def matbaa_govde(k):
    W, H, P, T = 105.0, 148.0, MB_PAY, MB_TASMA
    L = P - T                      # işaret uzunluğu (kenardan taşma çizgisine)
    xs, ys = (P, P + W), (P, P + H)
    m = []
    for y in ys:                   # yatay işaretler: sol ve sağ kenarda
        m.append(f'<i class="cm h" style="left:0;top:{y}mm"></i>')
        m.append(f'<i class="cm h" style="left:{P + W + T}mm;top:{y}mm"></i>')
    for x in xs:                   # dikey işaretler: üst ve alt kenarda
        m.append(f'<i class="cm v" style="left:{x}mm;top:0"></i>')
        m.append(f'<i class="cm v" style="left:{x}mm;top:{P + H + T}mm"></i>')
    slug = (f"Riva Hotel Alsancak · TV kartı {k['kod']} ({k['ad']}) · kesim A6 105×148 mm · "
            f"3 mm taşma payı · tek yüz 4 renk")
    return f'<div class="mb">{kart(k)}{"".join(m)}<div class="slug">{slug}</div></div>'


def main():
    (OUT / "matbaa").mkdir(exist_ok=True)
    kartlar, manifest = [], []
    for k in KUMANDALAR:
        h = OUT / f"{k['dosya']}.html"
        h.write_text(sayfa(kart(k), "105mm 148mm"), encoding="utf-8")
        render(h, OUT / f"{k['dosya']}.pdf", OUT / f"{k['dosya']}.png")
        # matbaa sürümü
        hm = OUT / "matbaa" / f"{k['dosya']}-matbaa.html"
        hm.write_text(sayfa(matbaa_govde(k), "125mm 168mm", MB_CSS).replace('src="img/', 'src="../img/'),
                      encoding="utf-8")
        render(hm, OUT / "matbaa" / f"{k['dosya']}-matbaa.pdf")
        # panodaki önizleme görseli
        tmp = OUT / f".tmp-{k['kod']}"
        subprocess.run(["pdftoppm", "-r", "130", "-png", "-singlefile",
                        str(OUT / f"{k['dosya']}.pdf"), str(tmp)], check=True)
        subprocess.run(["convert", f"{tmp}.png", "-quality", "84", "-strip",
                        str(OUT / f"onizleme-{k['kod']}.jpg")], check=True)
        pathlib.Path(f"{tmp}.png").unlink()
        kartlar.append(kart(k))
        manifest.append({"kod": k["kod"], "ad": k["ad"],
                         "pdf": f"{k['dosya']}.pdf", "png": f"{k['dosya']}.png",
                         "matbaa": f"matbaa/{k['dosya']}-matbaa.pdf",
                         "onizleme": f"onizleme-{k['kod']}.jpg"})
        print("  ✓", k["dosya"], "(+ matbaa)")
    # dört kart tek A4'te (2×2), kesim kılavuzlarıyla — ofis yazıcısı için
    a4 = ('<div class="sheet">' + "".join(kartlar) +
          '<i class="cut v"></i><i class="cut h"></i></div>')
    a4css = """
.sheet{width:210mm;height:297mm;display:grid;grid-template-columns:105mm 105mm;
  grid-template-rows:148mm 148mm;position:relative}
.cut{position:absolute;border:0 dashed #c9c9c9}
.cut.v{left:105mm;top:0;bottom:1mm;border-left-width:.2mm}
.cut.h{top:148mm;left:0;right:0;border-top-width:.2mm}"""
    h = OUT / "hepsi-A4-baski.html"
    h.write_text(sayfa(a4, "A4", a4css), encoding="utf-8")
    render(h, OUT / "hepsi-A4-baski.pdf")
    print("  ✓ hepsi-A4-baski")
    # panodaki "TV Kullanım Kartları" sayfası bu listeyi okur (checks.build_tvkart)
    (OUT / "kartlar.json").write_text(json.dumps(
        {"uretim": datetime.date.today().isoformat(), "kartlar": manifest,
         "a4": "hepsi-A4-baski.pdf"}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("  ✓ kartlar.json")


if __name__ == "__main__":
    main()
