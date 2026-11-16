#!/usr/bin/env python3
"""
Google yorum kartları — çıkışta her misafire verilen, QR'lı A6 kart (16.11.2026, sahibinin isteği).

Ön yüz Türkçe, arka yüz İngilizce. Otel sitesinin renkleri (lacivert #132742, mavi #537eac,
açık #f0f6fd) ve otelin logosu. Her renk için:
  - <ad>.pdf            2 sayfa (ön + arka), A6 yatay 148×105 mm — dijital baskı / önizleme
  - <ad>-on.png / -arka.png   300 dpi (WhatsApp ile matbaaya göndermek için)
  - matbaa/<ad>-matbaa.pdf    3 mm taşma payı + kesim işaretli, 2 sayfa
  - <ad>-A4.pdf         ofis yazıcısı: A4 yatayda 4 kart, 2. sayfa arka yüzler (uzun kenardan çift yön)
  - onizleme-<ad>.jpg   panodaki küçük görsel
QR → https://www.rivaalsancak.com/yorum.html → Google'da "yorum yaz" penceresi. Hedef değişirse
sitedeki yorum.html güncellenir; basılı kartlar değişmez.

Google kuralı: yorum karşılığı indirim/hediye YOK, kart HERKESE verilir (yalnız memnunlara değil).

Çalıştırma:  python3 kartlar/yorum/uret.py      (chromium + pdftoppm + ImageMagick)
"""
import pathlib, subprocess, shutil, json, datetime, re

HERE = pathlib.Path(__file__).resolve().parent
IMG = HERE / "img"

RENKLER = [
    {"kod": "lacivert", "ad": "Lacivert", "bg": "#132742", "fg": "#ffffff", "sub": "#c3d1e3",
     "vurgu": "#537eac", "yildiz": "#e9c46a", "logo": "logo-beyaz.png", "cizgi": "#2b4466"},
    {"kod": "mavi", "ad": "Mavi", "bg": "#537eac", "fg": "#ffffff", "sub": "#e6eef8",
     "vurgu": "#132742", "yildiz": "#ffd772", "logo": "logo-beyaz.png", "cizgi": "#6f95bf"},
    {"kod": "beyaz", "ad": "Beyaz", "bg": "#ffffff", "fg": "#132742", "sub": "#5f6b7a",
     "vurgu": "#537eac", "yildiz": "#e0a422", "logo": "logo-lacivert.png", "cizgi": "#d6e2f0"},
    {"kod": "acik-mavi", "ad": "Açık mavi", "bg": "#f0f6fd", "fg": "#132742", "sub": "#55657a",
     "vurgu": "#537eac", "yildiz": "#e0a422", "logo": "logo-lacivert.png", "cizgi": "#d6e2f0"},
    {"kod": "iki-renk", "ad": "İki renk", "bg": "#132742", "fg": "#ffffff", "sub": "#c3d1e3",
     "vurgu": "#537eac", "yildiz": "#e9c46a", "logo": "logo-beyaz.png", "cizgi": "#2b4466", "iki": True},
]

METIN = {
    "tr": {"baslik": "Konaklamanız nasıldı?",
           "govde": "Birkaç cümlelik Google yorumunuz, yeni misafirlerimizin bizi bulmasını sağlıyor. "
                    "Ekibimiz her yorumu okuyor.",
           "qr": "Telefon kameranızla<br>okutun",
           "tesekkur": "Teşekkür ederiz"},
    "en": {"baslik": "How was your stay?",
           "govde": "A short Google review helps other travellers find us. "
                    "Our team reads every single one.",
           "qr": "Scan with your<br>phone camera",
           "tesekkur": "Thank you"},
}
ALT = "rivaalsancak.com · +90 232 464 64 02 · 1454 Sokak No:11, Alsancak · İzmir"

W, H = 148.0, 105.0          # A6 yatay, kesim boyu (mm)

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700;800&family=Playfair+Display:wght@600;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
html,body{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{font-family:Manrope,system-ui,sans-serif}
.card{width:148mm;height:105mm;position:relative;overflow:hidden;display:grid;
  grid-template-columns:1fr 46mm;column-gap:9mm;padding:11mm 11mm 12mm 12mm}
.card .ust{position:absolute;left:0;right:0;top:0;height:2.2mm}
.sol{display:flex;flex-direction:column;justify-content:flex-start;min-width:0}
.logo{height:13mm;width:auto;align-self:flex-start;margin-bottom:8.5mm}
h1{font:700 21pt/1.12 'Playfair Display',Georgia,serif;letter-spacing:-.01em;margin-bottom:3.6mm}
.govde{font-size:9.6pt;line-height:1.5;max-width:70mm}
.yildiz{font-size:15pt;letter-spacing:1.6mm;margin-top:4.5mm;line-height:1}
.sag{display:flex;flex-direction:column;align-items:center;justify-content:center}
.qr{width:46mm;height:46mm;background:#fff;border-radius:4mm;padding:4.2mm}
.qr svg{width:100%;height:100%;display:block}
.qr svg path{fill:#132742}
.qrnot{font-size:7.6pt;line-height:1.3;text-align:center;margin-top:2.6mm;font-weight:600}
.tes{font:700 10pt 'Playfair Display',Georgia,serif;margin-top:1.4mm;text-align:center}
.alt{position:absolute;left:12mm;right:11mm;bottom:5.2mm;font-size:6.6pt;letter-spacing:.02em;
  padding-top:2mm;border-top:.25mm solid}
.iki .sagzemin{position:absolute;top:0;right:0;bottom:0;width:66mm;background:#ffffff}
.iki .sag{position:relative;z-index:1}
.iki .qr{padding:2.6mm;border:.35mm solid #d6e2f0}
.iki .alt{right:66mm;padding-right:6mm}
"""


def qr_svg():
    s = (IMG / "qr.svg").read_text(encoding="utf-8")
    return re.sub(r'width="[^"]*" height="[^"]*"', 'width="100%" height="100%"', s, count=1)


def kart(r, dil):
    m = METIN[dil]
    iki = r.get("iki")
    qrnot_renk = "#132742" if iki else r["fg"]
    tes_renk = "#537eac" if iki else r["fg"]
    return f"""
<div class="card{' iki' if iki else ''}" style="background:{r['bg']};color:{r['fg']}">
  <div class="ust" style="background:{r['vurgu']}"></div>
  {'<div class="sagzemin"></div>' if iki else ''}
  <div class="sol">
    <img class="logo" src="img/{r['logo']}" alt="Riva Hotel Alsancak">
    <h1>{m['baslik']}</h1>
    <p class="govde" style="color:{r['sub']}">{m['govde']}</p>
    <div class="yildiz" style="color:{r['yildiz']}">★★★★★</div>
  </div>
  <div class="sag">
    <div class="qr">{qr_svg()}</div>
    <div class="qrnot" style="color:{qrnot_renk}">{m['qr']}</div>
    <div class="tes" style="color:{tes_renk}">{m['tesekkur']}</div>
  </div>
  <div class="alt" style="color:{r['sub']};border-color:{r['cizgi']}">{ALT}</div>
</div>"""


def sayfa(govde, boyut, ek_css=""):
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8"><title>Yorum kartı</title>
<style>{CSS}
@page{{size:{boyut};margin:0}}
.p{{page-break-after:always;break-after:page}}.p:last-child{{page-break-after:auto;break-after:auto}}
{ek_css}</style></head><body>{govde}</body></html>"""


def chromium():
    for b in ("chromium", "chromium-browser", "google-chrome"):
        if shutil.which(b):
            return b
    raise SystemExit("chromium bulunamadı")


def render(html_path, pdf_path):
    b = chromium()
    subprocess.run([b, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                    "--virtual-time-budget=15000", "--run-all-compositor-stages-before-draw",
                    "--no-pdf-header-footer", f"--print-to-pdf={pdf_path}", html_path.as_uri()],
                   check=True, capture_output=True)


def png(pdf, stem, sayfa_no, dpi):
    subprocess.run(["pdftoppm", "-r", str(dpi), "-png", "-singlefile", "-f", str(sayfa_no), "-l", str(sayfa_no),
                    str(pdf), str(stem)], check=True)


# ---- matbaa: 3 mm taşma (zemin rengi taşar) + kesim işaretleri -----------------------------
P, T = 10.0, 3.0
MB_CSS = f"""
.mb{{position:relative;width:{W + 2 * P}mm;height:{H + 2 * P}mm;background:#fff;overflow:hidden}}
.mb .tas{{position:absolute;left:{P - T}mm;top:{P - T}mm;width:{W + 2 * T}mm;height:{H + 2 * T}mm}}
.mb .card{{position:absolute;left:{P}mm;top:{P}mm}}
.cm{{position:absolute;background:#000}}.cm.h{{height:.09mm;width:{P - T}mm}}.cm.v{{width:.09mm;height:{P - T}mm}}
.slug{{position:absolute;left:0;right:0;bottom:1.6mm;text-align:center;font-size:5pt;color:#888}}"""


def matbaa(r, dil, yuz):
    xs, ys = (P, P + W), (P, P + H)
    m = []
    for y in ys:
        m += [f'<i class="cm h" style="left:0;top:{y}mm"></i>', f'<i class="cm h" style="left:{P + W + T}mm;top:{y}mm"></i>']
    for x in xs:
        m += [f'<i class="cm v" style="left:{x}mm;top:0"></i>', f'<i class="cm v" style="left:{x}mm;top:{P + H + T}mm"></i>']
    tas = (f'<div class="tas" style="background:linear-gradient(90deg,{r["bg"]} 0 {T + W - 66}mm,#fff {T + W - 66}mm)"></div>'
           if r.get("iki") else f'<div class="tas" style="background:{r["bg"]}"></div>')
    ust = f'<div style="position:absolute;left:{P - T}mm;top:{P - T}mm;width:{W + 2 * T}mm;height:{T + 2.2}mm;background:{r["vurgu"]}"></div>'
    slug = f"Riva Hotel Alsancak · Google yorum kartı · {r['ad']} · {yuz} · kesim A6 148×105 mm · 3 mm taşma · çift yüz 4 renk"
    return f'<div class="p mb">{tas}{ust}{kart(r, dil)}{"".join(m)}<div class="slug">{slug}</div></div>'


A4_CSS = """
.a4{width:297mm;height:210mm;display:grid;grid-template-columns:148.5mm 148.5mm;grid-template-rows:105mm 105mm;position:relative}
.a4 .card{width:148.5mm;height:105mm}
.cut{position:absolute;border:0 dashed #bbb}.cut.v{left:148.5mm;top:0;bottom:0;border-left-width:.2mm}
.cut.h{top:105mm;left:0;right:0;border-top-width:.2mm}"""


def main():
    (HERE / "matbaa").mkdir(exist_ok=True)
    manifest = []
    for r in RENKLER:
        k = r["kod"]
        # dijital 2 sayfa
        h = HERE / f"yorum-karti-{k}.html"
        h.write_text(sayfa(f'<div class="p">{kart(r, "tr")}</div><div class="p">{kart(r, "en")}</div>', "148mm 105mm"),
                     encoding="utf-8")
        pdf = HERE / f"yorum-karti-{k}.pdf"
        render(h, pdf)
        png(pdf, HERE / f"yorum-karti-{k}-on", 1, 300)
        png(pdf, HERE / f"yorum-karti-{k}-arka", 2, 300)
        tmp = HERE / f".tmp-{k}"
        png(pdf, tmp, 1, 110)
        subprocess.run(["convert", f"{tmp}.png", "-quality", "85", "-strip", str(HERE / f"onizleme-{k}.jpg")], check=True)
        png(pdf, tmp, 2, 110)
        subprocess.run(["convert", f"{tmp}.png", "-quality", "85", "-strip", str(HERE / f"onizleme-{k}-arka.jpg")], check=True)
        pathlib.Path(f"{tmp}.png").unlink()
        # matbaa
        hm = HERE / "matbaa" / f"yorum-karti-{k}-matbaa.html"
        hm.write_text(sayfa(matbaa(r, "tr", "ÖN (Türkçe)") + matbaa(r, "en", "ARKA (İngilizce)"),
                            f"{W + 2 * P}mm {H + 2 * P}mm", MB_CSS).replace('src="img/', 'src="../img/'), encoding="utf-8")
        render(hm, HERE / "matbaa" / f"yorum-karti-{k}-matbaa.pdf")
        # ofis yazıcısı: A4 yatay 4'lü; arka sayfa uzun kenardan çevrilir → sütunlar yer değiştirmez,
        # 4 kart aynı olduğu için düzen aynı kalır
        cut = '<i class="cut v"></i><i class="cut h"></i>'
        on, arka = kart(r, "tr"), kart(r, "en")
        ha = HERE / f"yorum-karti-{k}-A4.html"
        ha.write_text(sayfa(f'<div class="p a4">{on * 4}{cut}</div><div class="p a4">{arka * 4}{cut}</div>',
                            "297mm 210mm", A4_CSS), encoding="utf-8")
        render(ha, HERE / f"yorum-karti-{k}-A4.pdf")
        manifest.append({"kod": k, "ad": r["ad"], "renk": r["bg"], "pdf": f"yorum-karti-{k}.pdf",
                         "png_on": f"yorum-karti-{k}-on.png", "png_arka": f"yorum-karti-{k}-arka.png",
                         "matbaa": f"matbaa/yorum-karti-{k}-matbaa.pdf", "a4": f"yorum-karti-{k}-A4.pdf",
                         "onizleme": f"onizleme-{k}.jpg", "onizleme_arka": f"onizleme-{k}-arka.jpg"})
        print("  ✓", k)
    (HERE / "kartlar.json").write_text(json.dumps({"uretim": datetime.date.today().isoformat(),
                                                   "hedef": "https://www.rivaalsancak.com/yorum.html",
                                                   "kartlar": manifest}, ensure_ascii=False, indent=1),
                                       encoding="utf-8")


if __name__ == "__main__":
    main()
