"""
Pazarlama sayfaları (24.11.2026, sahibinin isteği): Kurumlar · Google Yorumları · Google Paylaşımları.

Veri https://api.rivaalsancak.com (Cloudflare Worker + KV, kaynak: rivahotelalsancak-web/cloudflare/panel-api).
Panel statik ve şifreli olduğu için müdürün "gönderildi / cevap geldi" kayıtları orada tutulur.
Anahtarlar GitHub Secret PANEL_KEY_YONETIM / PANEL_KEY_MUDUR → bölümün şifreli HTML'ine gömülür:
  - kurumlar: resepsiyon + yönetim (müdür işaretler) → KEY_MUDUR (yalnız "kurumlar"a yazar)
  - yorumlar, paylasim: yalnız yönetim → KEY_YONETIM
Yorum ve paylaşım listeleri Google İşletme Profili'nden Claude'un her pazartesi yüklediği anlık görüntüdür
(GBP API izni yok); kurum listesi aşağıda sabit.
"""
import json, os, re

from checks import PAGE, esc, now_str

API = "https://api.rivaalsancak.com/v1/"

# ---------------------------------------------------------------------------
# Bağlantı / iş birliği kurumları (araştırma 16.11.2026; e-postalar kurumların kendi sitelerinden,
# "doğrula" yazanlar ikincil kaynaktan). Öncelik 1–5 = ilk gidilecekler.
# ---------------------------------------------------------------------------
KURUMLAR = [
    {"id": "kaskaloglu", "ad": "Kaşkaloğlu Göz Hastanesi", "tur": "Göz", "web": "https://kaskaloglu.com",
     "eposta": "info@kaskaloglu.com", "adres": "1400 Sk. No:10, Alsancak", "oncelik": 1,
     "istek": "Yabancı hastalarına 'yakındaki otel' olarak İngilizce sayfamıza bağlantı; hasta konaklama iş birliği",
     "sayfa": "https://www.rivaalsancak.com/ENG/hotel-for-dental-eye-treatment-izmir.html", "yol": "Ziyaret + mektup"},
    {"id": "turkoglu", "ad": "Dr. Türkoğlu Diş Kliniği", "tur": "Diş", "web": "https://drturkoglu.com",
     "eposta": "info@drturkoglu.com", "adres": "Kızılay Cd. No:3/1 K:1 D:2, Alsancak", "oncelik": 2,
     "istek": "Sağlık turizmi hastalarına konaklama önerisi; diş tedavisi sayfamıza bağlantı",
     "sayfa": "https://www.rivaalsancak.com/ENG/hotel-for-dental-eye-treatment-izmir.html", "yol": "Ziyaret + mektup"},
    {"id": "deu", "ad": "Dokuz Eylül Üniversitesi — Uluslararası İlişkiler", "tur": "Üniversite",
     "web": "https://international.deu.edu.tr", "eposta": "international@deu.edu.tr, erasmus@deu.edu.tr",
     "adres": "Cumhuriyet Blv. No:144, Alsancak", "oncelik": 3,
     "istek": "Misafir akademisyen ve öğrenci aileleri için önerilen konaklama listesine eklenmek",
     "sayfa": "https://www.rivaalsancak.com/uzun-konaklama.html", "yol": "İmzalı mektup + e-posta"},
    {"id": "visitizmir", "ad": "Visit İzmir (İzmir Büyükşehir)", "tur": "Şehir portalı", "web": "https://visitizmir.org",
     "eposta": "him@izmir.bel.tr · başvuru: bizizmir.com", "adres": "Kültürpark 1 No'lu Hol, Konak", "oncelik": 4,
     "istek": "Portalın 'Konaklama' bölümüne eklenmek", "sayfa": "https://www.rivaalsancak.com/",
     "yol": "Dilekçe + işletme belgesi"},
    {"id": "gezenthi", "ad": "Gezenthi Travel", "tur": "Efes turları", "web": "https://gezenthi.com",
     "eposta": "info@gezenthi.com", "adres": "Şair Eşref Blv. 57 D:2, Alsancak", "oncelik": 5,
     "istek": "Karşılıklı tavsiye: tur müşterilerine otel önerisi, bizde tur önerisi",
     "sayfa": "https://www.rivaalsancak.com/ENG/izmir-hotel-for-ephesus-day-trips.html", "yol": "Kısa e-posta"},
    {"id": "dunyagoz", "ad": "Dünyagöz İzmir", "tur": "Göz", "web": "https://dunyagoz.com", "eposta": "info@dunyagoz.com",
     "adres": "Ali Çetinkaya Blv. No:79, Alsancak", "oncelik": 9,
     "istek": "Yabancı hasta konaklama önerisi listesine eklenmek",
     "sayfa": "https://www.rivaalsancak.com/izmir-hastaneye-yakin-otel-tedavi.html", "yol": "Ziyaret + mektup"},
    {"id": "avrupadent", "ad": "Avrupadent (Alsancak)", "tur": "Diş", "web": "https://avrupadent.com.tr",
     "eposta": "info@avrupadent.com.tr", "adres": "Atatürk Cd. No:420, Alsancak (doğrula)", "oncelik": 9,
     "istek": "Hasta konaklama ortaklığı", "sayfa": "https://www.rivaalsancak.com/ENG/hotel-for-dental-eye-treatment-izmir.html",
     "yol": "Ziyaret"},
    {"id": "ossihair", "ad": "Ossi Hair", "tur": "Saç ekimi", "web": "https://ossihair.com", "eposta": "info@ossihair.com",
     "adres": "Heris Tower, Şht. Fethi Bey Cd. No:55 K:9, Alsancak", "oncelik": 9,
     "istek": "'Şehir dışından gelenler' bölümüne otel önerisi", "sayfa": "https://www.rivaalsancak.com/izmir-hastaneye-yakin-otel-tedavi.html",
     "yol": "Ziyaret"},
    {"id": "ieu", "ad": "İzmir Ekonomi Üniversitesi — Uluslararası Ofis", "tur": "Üniversite",
     "web": "https://www.ieu.edu.tr/international", "eposta": "oia@ieu.edu.tr", "adres": "Sakarya Cd. No:156, Balçova",
     "oncelik": 9, "istek": "Değişim öğrencileri / misafir hocalar için uzun konaklama sayfamız",
     "sayfa": "https://www.rivaalsancak.com/uzun-konaklama.html", "yol": "Mektup + e-posta"},
    {"id": "yasar", "ad": "Yaşar Üniversitesi — Erasmus", "tur": "Üniversite", "web": "https://erasmus.yasar.edu.tr",
     "eposta": "sitedeki iletişim sayfası", "adres": "Bornova", "oncelik": 9,
     "istek": "Gelen öğrenci bilgi sayfasına eklenmek", "sayfa": "https://www.rivaalsancak.com/uzun-konaklama.html", "yol": "E-posta"},
    {"id": "izfas", "ad": "İZFAŞ (Fuar İzmir)", "tur": "Fuar", "web": "https://izfas.com.tr/iletisim",
     "eposta": "iletişim formu · 0232 497 10 00", "adres": "Gaziemir Fuar Alanı", "oncelik": 9,
     "istek": "Fuar katılımcılarına konaklama listesi (İZBAN ile doğrudan)",
     "sayfa": "https://www.rivaalsancak.com/izmir-is-seyahati-fuar-rehberi.html", "yol": "Resmi yazı"},
    {"id": "ktb", "ad": "İzmir İl Kültür ve Turizm Müdürlüğü", "tur": "Resmi kurum", "web": "https://izmir.ktb.gov.tr",
     "eposta": "iktm35@kulturturizm.gov.tr (doğrula)", "adres": "Konak", "oncelik": 9,
     "istek": "Kongre turizmi sayfasındaki otel listesine eklenmek", "sayfa": "https://www.rivaalsancak.com/", "yol": "Dilekçe"},
    {"id": "izto", "ad": "İzmir Ticaret Odası (İZTO)", "tur": "Oda", "web": "https://izto.org.tr", "eposta": "sitedeki iletişim",
     "adres": "Atatürk Cd. No:126, Pasaport (doğrula)", "oncelik": 9,
     "istek": "Heyet konaklamalarında önerilmek", "sayfa": "https://www.rivaalsancak.com/", "yol": "Telefon + randevu"},
    {"id": "ebso", "ad": "Ege Bölgesi Sanayi Odası — Dış Ticaret", "tur": "Oda", "web": "https://ebso.org.tr",
     "eposta": "disticaret@ebso.org.tr", "adres": "Atatürk Cd. No:382, Alsancak", "oncelik": 9,
     "istek": "Yabancı alıcı heyetlerine kurumsal fiyat", "sayfa": "https://www.rivaalsancak.com/izmir-is-seyahati-fuar-rehberi.html",
     "yol": "Telefon + randevu"},
    {"id": "theephesus", "ad": "theephesus.com (liman turları)", "tur": "Tur", "web": "https://theephesus.com/contact",
     "eposta": "info@theephesus.com", "adres": "Kuşadası", "oncelik": 9,
     "istek": "'Turdan önce nerede kalınır' önerisi", "sayfa": "https://www.rivaalsancak.com/ENG/hotel-near-izmir-cruise-port.html",
     "yol": "İngilizce e-posta"},
    {"id": "journeybeyond", "ad": "Journey Beyond the Horizon (gezi blogu)", "tur": "Blog",
     "web": "https://journeybeyondhorizon.com/contact", "eposta": "iletişim formu", "adres": "—", "oncelik": 9,
     "istek": "'Where to stay in Izmir' yazısının Alsancak bölümüne eklenmek",
     "sayfa": "https://www.rivaalsancak.com/ENG/hotel-near-kordon-izmir.html", "yol": "İngilizce e-posta"},
]

DURUMLAR = ["Bekliyor", "Mektup/e-posta gönderildi", "Ziyaret edildi", "Cevap geldi", "Görüşülüyor",
            "Bağlantı verdi ✓", "Olumsuz", "Vazgeçildi"]

MEKTUP_TR = """Sayın Yetkili,

Alsancak'ta, 1454 Sokak No:11'de bulunan 55 odalı Riva Hotel Alsancak olarak {ad} ile bir iş birliği önermek istiyoruz.

Otelimizde 42 mutfaklı (apart) oda, 1+1 suitler, 24 saat açık resepsiyon ve kahvaltı dahil konaklama sunuyoruz; Kordon'a 5 dakika, Alsancak İZBAN'a yürüme mesafesindeyiz.

Önerimiz: {istek}. Bu kapsamda misafirleriniz/hastalarınız için bilgi sayfamız: {sayfa}

Uygun gördüğünüz bir zamanda kısa bir görüşme için sizi otelimizde ağırlamaktan memnuniyet duyarız.

Saygılarımızla,
Riva Hotel Alsancak
+90 232 464 64 02 · info@rivaalsancak.com · www.rivaalsancak.com"""

MEKTUP_EN = """Dear Sir or Madam,

I am writing from Riva Hotel Alsancak, a 55-room city hotel at 1454 Sokak No:11 in central Alsancak, Izmir. 42 of our rooms have a kitchenette, breakfast is included, and our reception is open 24 hours; we are 5 minutes from the Kordon seafront.

We would like to propose a partnership with {ad}: {istek}. Our page for your guests: {sayfa}

We would be glad to welcome you at the hotel for a short meeting at your convenience.

Kind regards,
Riva Hotel Alsancak
+90 232 464 64 02 · info@rivaalsancak.com · www.rivaalsancak.com"""

CSS = """
<style>
.pz-top{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:6px 0 14px}
.pz-top input{padding:7px 10px;border:1px solid var(--border);border-radius:8px;background:var(--bg);color:var(--fg);font:inherit}
.pz-durum{font-size:12px;color:var(--sub)}
.pz-tw{overflow-x:auto}
.pz-t{border-collapse:collapse;width:100%;font-size:13.5px;min-width:760px}
.pz-t th,.pz-t td{text-align:left;padding:9px 8px;border-bottom:1px solid var(--border);vertical-align:top}
.pz-t th{font-size:11.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--sub)}
.pz-t a{color:var(--eyebrow)}
.pz-t select,.pz-t textarea{width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--fg);font:inherit;font-size:13px}
.pz-t textarea{min-height:38px;resize:vertical}
.pz-ok{font-size:11.5px;color:var(--sub);margin-top:4px}
.pz-on{display:inline-block;background:var(--eyebrow);color:var(--card);border-radius:6px;padding:0 6px;font-size:11px;font-weight:800;margin-left:5px}
.pz-btn{padding:5px 10px;border:1px solid var(--border);border-radius:7px;background:var(--bg);color:var(--fg);cursor:pointer;font:inherit;font-size:12.5px}
.pz-btn:hover{border-color:var(--eyebrow)}
.pz-mektup{white-space:pre-wrap;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;font-size:13px;margin-top:8px}
.pz-rev{border:1px solid var(--border);border-radius:12px;padding:12px 14px;margin:10px 0}
.pz-rev .y{color:#e0a422;letter-spacing:1px}
.pz-rev .m{margin:6px 0;font-size:14px}
.pz-rev .c{background:var(--bg);border-radius:8px;padding:8px 11px;font-size:13px;color:var(--sub)}
.pz-rev.kotu{border-left:4px solid #c0392b}
.pz-ist{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:8px 0 14px}
.pz-ist .k{border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.pz-ist .k b{display:block;font-size:22px}
.pz-ist .k span{font-size:12px;color:var(--sub)}
.pz-filtre{display:flex;gap:6px;flex-wrap:wrap;margin:4px 0}
.pz-filtre button.on{background:var(--eyebrow);color:var(--card);border-color:var(--eyebrow)}
</style>"""


def _anahtar(ad):
    return os.environ.get(ad, "").strip()


def _yok_notu():
    return ("<div class='note'><b>Kayıt servisi bağlı değil.</b> Panel derlemesinde anahtar bulunamadı "
            "(GitHub Secret PANEL_KEY_*). Liste görünür ama değişiklik kaydedilmez.</div>")


# ---------------------------------------------------------------------------
# Kurumsal müşteriler (26.11.2026, sahibinin isteği "otelin doluluğu için firmaları arayalım"):
# bu yıl otelde kalmış firmalar/cariler, Elektra'dan her derlemede yeniden çekilir. OTA, tur operatörü
# ve kanal adları hariç. Durum + not aynı kayıt servisinde, kimlik "m-<firma>" ile tutulur.
# ---------------------------------------------------------------------------
MUSTERI_DURUM = ["Aranmadı", "Arandı – ulaşılamadı", "Arandı – teklif verildi", "Rezervasyon geldi ✓",
                 "İlgilenmiyor", "Aranmasın"]
KANAL_DISI = {
    "BOOKING", "EXPEDIA", "WALKIN", "TELEFON", "ONLINE", "ETSODAMAX", "TATIL BUDUR", "ENUYGUN", "TRIP.COM",
    "OSTROVOK.RU", "OTEL FİYAT", "OTEL FIYAT", "ALLEGROTOUR  AŞ.", "ALLEGROTOUR AŞ.", "OBİLET", "OBILET",
    "JOLLY TOUR", "PIKONAKLAMA", "PİKONAKLAMA", "EPOSTA", "OTELZV2", "SETUR", "TATILSEPETI", "TATİLSEPETİ",
    "RATEBEDS", "BUTA TOUR", "ANTUR TURIZM A.Ş", "OYAK TUR", "EMELTUR", "TRAVELWAY", "DREAM INCENTIVE",
    "VIKINGTUR", "GOLDENBAY", "GEZİNOMİ", "GEZINOMI", "TURISMO TUR", "VACANZA", "SANTATUR", "ALPİNA TUR",
    "HYPERGUEST", "TCI SEYAHAT", "BİLETSEL-DIAMOND", "BRO OTEL", "AIRBNB", "CTRIP", "?", ""}


def _mid(ad):
    import unicodedata
    t = unicodedata.normalize("NFKD", ad.replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode()
    return "m-" + (re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-") or "firma")


def _kurumsal_musteriler(env):
    """[{id, ad, rez, gece, son, misafir, tel}] — bu yıl CHECKIN'i olan, iptal edilmemiş konaklamalar."""
    import datetime as dt
    import elektra_api as E
    bugun = dt.date.today()
    rows, ay = [], dt.date(bugun.year, 1, 1)
    while ay <= bugun:
        son = min(bugun, (ay.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1))
        rows += E.fetch_reservations_between("CHECKIN", ay.isoformat(), son.isoformat(), env=env)
        ay = son + dt.timedelta(days=1)
    gr = {}
    for r in rows:
        if str(r.get("RESSTATE")) not in ("CheckOut", "InHouse", "Reservation"):
            continue
        ad = " ".join((r.get("AGENCY") or "").split())
        if ad.upper() in KANAL_DISI:
            continue
        gr.setdefault(ad, []).append(r)
    sonlar = {ad: max(v, key=lambda r: str(r.get("CHECKIN"))) for ad, v in gr.items()}
    tel = {}
    ids = [int(r["RESID"]) for r in sonlar.values() if str(r.get("RESID", "")).isdigit()]
    if ids:
        try:
            for g in E.fetch_res_guests([{"Column": "RESID", "Operator": "IN", "Value": ids}], env=env):
                p = (g.get("CONTACTPHONE") or g.get("GUESTPHONE") or "").strip()
                if p and str(g.get("RESID")) not in tel:
                    tel[str(g.get("RESID"))] = p
        except Exception:
            pass
    out = []
    for ad, v in gr.items():
        s = sonlar[ad]
        out.append({"id": _mid(ad), "ad": ad, "rez": len(v), "gece": sum(int(r.get("NIGHT") or 0) for r in v),
                    "son": str(s.get("CHECKIN"))[:10], "misafir": " ".join((s.get("GUESTNAMES") or "").split()),
                    "tel": tel.get(str(s.get("RESID")), "")})
    return sorted(out, key=lambda m: (-m["gece"], m["ad"]))


def _musteri_tablosu(env):
    try:
        ml = _kurumsal_musteriler(env)
    except Exception as ex:
        return (f"<div class='note'><b>Kurumsal müşteri listesi alınamadı</b> (Elektra: {esc(str(ex)[:160])}). "
                "Bir sonraki güncellemede tekrar denenir.</div>"), 0
    def tarih(s):
        return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if len(s) >= 10 else s
    def tel_a(t):
        d = re.sub(r"[^0-9+]", "", t)
        return f"<a href='tel:{esc(d)}'>{esc(t)}</a>" if d else "<span class='pz-ok'>telefon yok</span>"
    satir = "".join(
        f"<tr class='pz-m' data-id='{esc(m['id'])}'>"
        f"<td><b>{esc(m['ad'])}</b><div class='pz-ok'>{m['rez']} rezervasyon · {m['gece']} gece · son giriş {tarih(m['son'])}</div></td>"
        f"<td style='font-size:13px'>{tel_a(m['tel'])}<div class='pz-ok'>Son misafir: {esc(m['misafir']) or '—'}</div></td>"
        f"<td style='min-width:170px'><select class='pz-d'>{''.join(f'<option>{esc(d)}</option>' for d in MUSTERI_DURUM)}</select>"
        f"<div class='pz-ok pz-son'>—</div></td>"
        f"<td style='min-width:180px'><textarea class='pz-n' placeholder='Kiminle görüşüldü, ne teklif edildi…'></textarea></td>"
        f"</tr>" for m in ml)
    html = (
        "<h3 style='margin:26px 0 6px'>Kurumsal müşteriler — bu yıl bizde kalan firmalar</h3>"
        "<p class='lead'>Elektra'dan otomatik gelir (Booking, Expedia, tur şirketleri hariç). Bu firmaları arayıp "
        "kış ve uzun konaklama için yer teklif edin; fiyat listesindeki fiyatlarla. Sonucu buradan işaretleyin, "
        "<b>anında kaydedilir</b>. Telefona dokununca arar.</p>"
        "<div class='pz-top'><span class='pz-durum-m'>yükleniyor…</span></div>"
        "<div class='pz-tw'><table class='pz-t'><thead><tr><th>Firma</th><th>Telefon</th><th>Durum</th><th>Not</th>"
        f"</tr></thead><tbody>{satir}</tbody></table></div>")
    return html, len(ml)


# ---------------------------------------------------------------------------
def build_kurumlar(env=None):
    key = _anahtar("PANEL_KEY_MUDUR")
    sirali = sorted(KURUMLAR, key=lambda k: (k["oncelik"], k["ad"]))
    satir = "".join(
        f"<tr data-id='{esc(k['id'])}'>"
        f"<td><b>{esc(k['ad'])}</b>{'<span class=pz-on>' + str(k['oncelik']) + '. öncelik</span>' if k['oncelik'] < 9 else ''}"
        f"<div class='pz-ok'>{esc(k['tur'])} · {esc(k['adres'])}</div>"
        f"<div class='pz-ok'><a href='{esc(k['web'])}' target='_blank' rel='noopener'>{esc(k['web'].split('//')[-1])}</a></div></td>"
        f"<td style='font-size:13px'>{esc(k['eposta'])}<div class='pz-ok'>Yol: {esc(k['yol'])}</div></td>"
        f"<td style='font-size:13px'>{esc(k['istek'])}"
        f"<div style='margin-top:6px'><button class='pz-btn' data-mektup='tr'>Mektup (TR)</button> "
        f"<button class='pz-btn' data-mektup='en'>E-posta (EN)</button></div><div class='pz-mk'></div></td>"
        f"<td style='min-width:170px'><select class='pz-d'>{''.join(f'<option>{esc(d)}</option>' for d in DURUMLAR)}</select>"
        f"<div class='pz-ok pz-son'>—</div></td>"
        f"<td style='min-width:180px'><textarea class='pz-n' placeholder='Not: kime, ne zaman, ne dendi…'></textarea></td>"
        f"</tr>" for k in sirali)
    veri = {k["id"]: {"ad": k["ad"], "istek": k["istek"], "sayfa": k["sayfa"]} for k in KURUMLAR}
    js = """
<script>(function(){
var API=%s, KEY=%s, V=%s, TR=%s, EN=%s;
var kok=document.currentScript.parentNode, dur=kok.querySelector('.pz-durum'), kim=kok.querySelector('.pz-kim');
try{kim.value=localStorage.getItem('pz-kim')||'';}catch(e){}
kim.addEventListener('change',function(){try{localStorage.setItem('pz-kim',kim.value)}catch(e){}});
function tarih(s){if(!s)return'';var d=new Date(s);return d.toLocaleDateString('tr-TR')+' '+d.toLocaleTimeString('tr-TR',{hour:'2-digit',minute:'2-digit'});}
function goster(id,r){var tr=kok.querySelector('tr[data-id="'+id+'"]'); if(!tr||!r)return;
  if(r.durum)tr.querySelector('.pz-d').value=r.durum; if(r.not!=null)tr.querySelector('.pz-n').value=r.not;
  tr.querySelector('.pz-son').textContent=(r.kim?r.kim+' · ':'')+tarih(r.guncelleme);}
function sayac(sec,el){if(!el)return; var s={}; kok.querySelectorAll(sec).forEach(function(x){s[x.value]=(s[x.value]||0)+1});
  el.textContent=Object.keys(s).map(function(k){return k+': '+s[k]}).join(' · ');}
function say(){sayac('tr:not(.pz-m) .pz-d',dur); sayac('tr.pz-m .pz-d',kok.querySelector('.pz-durum-m'));}
if(!KEY){dur.textContent='Kayıt servisi bağlı değil — değişiklikler kaydedilmez.';}
else fetch(API+'kurumlar',{headers:{'X-Key':KEY}}).then(function(r){return r.json()}).then(function(d){
  Object.keys(d).forEach(function(id){goster(id,d[id])}); say();}).catch(function(){dur.textContent='Kayıt servisine ulaşılamadı.';});
function kaydet(tr){ if(!KEY)return; var id=tr.getAttribute('data-id');
  var b={durum:tr.querySelector('.pz-d').value, not:tr.querySelector('.pz-n').value, kim:kim.value||''};
  tr.querySelector('.pz-son').textContent='kaydediliyor…';
  fetch(API+'kurumlar/'+encodeURIComponent(id),{method:'PUT',headers:{'X-Key':KEY,'Content-Type':'application/json'},body:JSON.stringify(b)})
   .then(function(r){return r.json()}).then(function(d){goster(id,d.kayit); say();})
   .catch(function(){tr.querySelector('.pz-son').textContent='KAYDEDİLEMEDİ — tekrar deneyin';});}
kok.querySelectorAll('tr[data-id]').forEach(function(tr){
  tr.querySelector('.pz-d').addEventListener('change',function(){kaydet(tr)});
  tr.querySelector('.pz-n').addEventListener('change',function(){kaydet(tr)});
  tr.querySelectorAll('[data-mektup]').forEach(function(btn){btn.addEventListener('click',function(){
    var v=V[tr.getAttribute('data-id')], t=(btn.getAttribute('data-mektup')=='tr'?TR:EN).replace('{ad}',v.ad).replace('{istek}',v.istek).replace('{sayfa}',v.sayfa);
    var m=tr.querySelector('.pz-mk'); m.innerHTML=''; var p=document.createElement('div'); p.className='pz-mektup'; p.textContent=t; m.appendChild(p);
    var c=document.createElement('button'); c.className='pz-btn'; c.textContent='Kopyala'; c.style.marginTop='6px';
    c.onclick=function(){try{navigator.clipboard.writeText(t); c.textContent='Kopyalandı ✓';}catch(e){}}; m.appendChild(c);});});});
})();</script>""" % (json.dumps(API), json.dumps(key), json.dumps(veri, ensure_ascii=False),
                     json.dumps(MEKTUP_TR, ensure_ascii=False), json.dumps(MEKTUP_EN, ensure_ascii=False))
    musteri_html, n_musteri = _musteri_tablosu(env)
    body = (
        CSS +
        "<p class='lead'>Bu kurumların sitesinden bizim sayfalarımıza verilecek her bağlantı Google'da sıralamamızı yükseltir "
        "ve doğrudan misafir getirir. Her kuruma ne yapıldığını buradan işaretleyin; değişiklik <b>anında kaydedilir</b> "
        "ve sahibi de görür. 'Mektup' düğmesi o kuruma göre doldurulmuş hazır metni açar.</p>"
        "<div class='pz-top'><label>Adınız: <input class='pz-kim' placeholder='ör. Müdür' size='14'></label>"
        "<span class='pz-durum'>yükleniyor…</span></div>"
        "<div class='pz-tw'><table class='pz-t'><thead><tr><th>Kurum</th><th>İletişim</th><th>Ne istiyoruz</th>"
        f"<th>Durum</th><th>Not</th></tr></thead><tbody>{satir}</tbody></table></div>"
        "<div class='note'><b>Öneri:</b> klinik ve üniversitelere imzalı mektup + tek sayfalık broşür, mümkünse kısa ziyaret; "
        "ardından aynı metni e-postayla gönderin. Tur firması ve bloga kısa İngilizce e-posta yeter. "
        "Para karşılığı bağlantı teklif edenleri kabul etmeyin (Google cezalandırır). Kurum indirimi sizin kararınız.</div>"
        + musteri_html
        + ("" if key else _yok_notu()) + js)
    return {"label": "Kurumlar", "count": len(KURUMLAR), "count_label": "kurum", "tone": "ok",
            "sub": f"Bağlantı / iş birliği kurumları + {n_musteri} kurumsal müşteri · arama takibi", "updated": now_str(),
            "html": PAGE("Pazarlama", "Kurumlar — bağlantı ve iş birliği",
                         "Kime yazıldı, kim cevap verdi: müdür işaretler, sahibi görür", body)}


# ---------------------------------------------------------------------------
TEMALAR = [
    ("Temizlik", "Toz, klozet, yarım kalan oda temizliği, değişmeyen çarşaf — en sık şikâyet"),
    ("Eksik malzeme", "Odada su, terlik, temiz bardak, sabun/duş jeli yok"),
    ("Arıza", "TV, sıcak su, akan sifon, kapanmayan banyo kapısı; 'acil bakım' yorumu"),
    ("Rezervasyon", "Enuygun onaylı rezervasyonda varışta oda yok; bebek yatağı hazırlanmamış"),
    ("Resepsiyon", "Üslup, oda saatinde hazır değil, yanlış kart, kayıp eşya (şarj aleti)"),
    ("B blok 202", "'Acil çıkış odası' olarak tarif edildi, ütü verilmedi"),
]


def build_yorumlar(env=None):
    key = _anahtar("PANEL_KEY_YONETIM")
    tema = "".join(f"<li><b>{esc(a)}:</b> {esc(b)}</li>" for a, b in TEMALAR)
    js = """
<script>(function(){
var API=%s, KEY=%s, kok=document.currentScript.parentNode, liste=kok.querySelector('.pz-liste'), ist=kok.querySelector('.pz-ist'), fl='hepsi', D=null;
function e(s){var d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML;}
function ciz(){ if(!D)return; var L=D.liste||[];
  var n=L.length, ort=n?(L.reduce(function(a,x){return a+(x.y||0)},0)/n):0, kotu=L.filter(function(x){return x.y<=3}).length, cv=L.filter(function(x){return x.c}).length;
  ist.innerHTML='<div class=k><b>'+e(D.ozet&&D.ozet.puan)+'</b><span>Google puanı ('+e(D.ozet&&D.ozet.toplam_yorum)+' yorum)</span></div>'+
   '<div class=k><b>'+ort.toFixed(1)+'</b><span>son '+n+' yorumun ortalaması</span></div>'+
   '<div class=k><b>'+cv+'/'+n+'</b><span>cevaplı</span></div>'+
   '<div class=k><b>'+kotu+'</b><span>3 yıldız ve altı</span></div>';
  liste.innerHTML=L.filter(function(x){return fl=='hepsi'||(fl=='kotu'&&x.y<=3)||(fl=='iyi'&&x.y>=4)||(fl=='cevapsiz'&&!x.c)}).map(function(x){
    return '<div class="pz-rev'+(x.y<=3?' kotu':'')+'"><b>'+e(x.ad)+'</b> <span class=y>'+'★★★★★'.slice(0,x.y||0)+'</span> <span class=pz-ok style="display:inline">'+e(x.z)+'</span>'+
     '<div class=m>'+e(x.m)+'</div>'+(x.c?'<div class=c><b>Cevabımız:</b> '+e(x.c)+'</div>':'<div class=c style="color:#c0392b"><b>Cevap yok</b></div>')+'</div>';}).join('')||'<p class=lead>Bu filtrede yorum yok.</p>';
  kok.querySelector('.pz-zaman').textContent=D.ozet&&D.ozet.guncelleme?('Son güncelleme: '+new Date(D.ozet.guncelleme).toLocaleString('tr-TR')):'';}
kok.querySelectorAll('.pz-filtre button').forEach(function(b){b.addEventListener('click',function(){
  kok.querySelectorAll('.pz-filtre button').forEach(function(x){x.classList.remove('on')}); b.classList.add('on'); fl=b.getAttribute('data-f'); ciz();});});
if(!KEY){liste.innerHTML='<p class=lead>Kayıt servisi bağlı değil.</p>';return;}
fetch(API+'yorumlar',{headers:{'X-Key':KEY}}).then(function(r){return r.json()}).then(function(d){D=d; ciz();})
 .catch(function(){liste.innerHTML='<p class=lead>Kayıt servisine ulaşılamadı.</p>';});
})();</script>""" % (json.dumps(API), json.dumps(key))
    body = (
        CSS +
        "<p class='lead'>Google'daki son yorumlar ve otel adına yazılan cevaplar. Cevapları Claude, sahibin onayladığı "
        "üslupla yazar (olumsuzda: özür, sorunu adlandırma, iletişim bilgisi; tartışma yok). Liste her pazartesi güncellenir.</p>"
        "<div class='pz-ist'></div><div class='pz-ok pz-zaman'></div>"
        "<div class='pz-filtre'><button class='pz-btn on' data-f='hepsi'>Hepsi</button><button class='pz-btn' data-f='kotu'>3★ ve altı</button>"
        "<button class='pz-btn' data-f='iyi'>4–5★</button><button class='pz-btn' data-f='cevapsiz'>Cevapsız</button></div>"
        "<div class='pz-liste'>yükleniyor…</div>"
        f"<div class='card' style='margin-top:16px'><h3>Olumsuz yorumlarda tekrar eden konular</h3><ul>{tema}</ul>"
        "<p class='lead' style='margin:6px 0 0'>Kat hizmetleri için oda kontrol listesi (su, terlik, bardak, sabun, sifon, TV, "
        "sıcak su) en çok tekrar eden şikâyetleri keser.</p></div>"
        + ("" if key else _yok_notu()) + js)
    return {"label": "Google Yorumları", "count": 50, "count_label": "son yorum", "tone": "ok",
            "sub": "Son 50 Google yorumu ve cevaplarımız", "updated": now_str(),
            "html": PAGE("Pazarlama", "Google Yorumları", "Son yorumlar, cevaplar ve tekrar eden şikâyetler", body)}


# ---------------------------------------------------------------------------
def build_paylasim(env=None):
    key = _anahtar("PANEL_KEY_YONETIM")
    js = """
<script>(function(){
var API=%s, KEY=%s, kok=document.currentScript.parentNode, t=kok.querySelector('tbody');
function e(s){var d=document.createElement('div'); d.textContent=s==null?'':String(s); return d.innerHTML;}
if(!KEY){t.innerHTML='<tr><td colspan=4>Kayıt servisi bağlı değil.</td></tr>';return;}
fetch(API+'paylasim',{headers:{'X-Key':KEY}}).then(function(r){return r.json()}).then(function(d){
  var L=Object.keys(d).filter(function(k){return d[k]&&d[k].tarih}).map(function(k){return d[k]}).sort(function(a,b){return a.tarih<b.tarih?-1:1});
  var bugun=new Date().toISOString().slice(0,10);
  t.innerHTML=L.map(function(p){var yay=p.durum=='yayinda'||p.tarih<=bugun;
    return '<tr><td><b>'+e(p.tarih.split('-').reverse().join('.'))+'</b><div class=pz-ok>'+e(p.saat||'')+'</div></td>'+
     '<td>'+(yay?'<span class=pz-on style="background:#2f7a52">Yayında</span>':'<span class=pz-on>Planlı</span>')+'</td>'+
     '<td><b>'+e(p.baslik)+'</b><div style="margin-top:4px">'+e(p.metin)+'</div><div class=pz-ok>Fotoğraf: '+e(p.foto)+'</div></td>'+
     '<td>'+e(p.dugme)+'<div class=pz-ok><a href="'+e(p.baglanti)+'" target=_blank rel=noopener>'+e((p.baglanti||'').replace('https://www.',''))+'</a></div></td></tr>';}).join('');
}).catch(function(){t.innerHTML='<tr><td colspan=4>Kayıt servisine ulaşılamadı.</td></tr>';});
})();</script>""" % (json.dumps(API), json.dumps(key))
    body = (
        CSS +
        "<p class='lead'>Google İşletme Profili'nde haftada bir paylaşım (otelin kendi fotoğrafıyla). Paylaşımlar Google'da "
        "<b>planlanmış</b> durumda: tarihi gelince Google kendisi yayınlar. Liste bitmeden Claude yeni haftaları yazar ve planlar.</p>"
        "<div class='pz-tw'><table class='pz-t'><thead><tr><th>Tarih</th><th>Durum</th><th>Paylaşım</th><th>Düğme</th></tr></thead>"
        "<tbody><tr><td colspan=4>yükleniyor…</td></tr></tbody></table></div>"
        "<div class='note'>Google, düzenli paylaşım yapan ve yorumlara cevap veren işletmeyi haritada daha üstte gösterir. "
        "Fiyat yazılmaz (sık değişiyor); kampanya varsa ayrı paylaşım yapılır.</div>"
        + ("" if key else _yok_notu()) + js)
    return {"label": "Google Paylaşımları", "count": 5, "count_label": "paylaşım", "tone": "ok",
            "sub": "İşletme Profili haftalık paylaşım takvimi", "updated": now_str(),
            "html": PAGE("Pazarlama", "Google Paylaşımları", "Haftalık paylaşım takvimi — yayında ve planlı", body)}
