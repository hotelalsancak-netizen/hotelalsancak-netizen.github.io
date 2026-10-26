"""Kanal fiyat toplayıcı — Fiyat Kontrol sayfasının otomatik gözlemleri.

GitHub Actions'ta (yurt dışı sunucu) gerçek bir tarayıcıyla kanalların HERKESE AÇIK otel
sayfalarını açar, oda başına en düşük (iptal edilemez) fiyatı okur ve gözlem listesine yazar.
Yurt dışından çalıştığı için Booking'in Türkiye engeli burada geçerli değil.

19.10.2026 testi: Booking, Etstur, Trip.com sayfa metninden; trivago (tüm satıcılar: Hotels.com,
ZenHotels, obilet, Jolly...), TatilBudur ve Enuygun sitenin kendi fiyat isteklerinden okunuyor.
trivago/TatilBudur (Akamai) ve Enuygun (Cloudflare) GÖRÜNMEZ (headless) tarayıcıyı engelliyor;
bu yüzden tarayıcı görünür açılır — sunucuda sanal ekranla çalıştırın:
    xvfb-run -a python fiyat_topla.py <çıktı.json> [önceki.json]

Kullanım:  python fiyat_topla.py <çıktı.json> [önceki.json]
Çıktı, checks.fiyat_gozlemler()'in okuduğu biçimdedir (gozlem.json ile aynı alanlar).
"""
import asyncio
import datetime as dt
import html as htmllib
import json
import os
import re
import sys
from urllib.parse import parse_qsl, urlencode
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")

# Oda adı → Fiyat Kontrol oda anahtarı. "Superior Deluxe" kanallarda Superior odadır.
def oda_key(ad):
    n = ad.lower()
    if any(k in n for k in ("1+1", "daire", "suit", "suite")):
        return "sui"
    if any(k in n for k in ("ekonomik", "economic", "economy")):
        return "eko"
    if "superior" in n:
        return "sup"
    if "deluxe" in n:
        return "dlx"
    if any(k in n for k in ("studio", "stüdyo", "standart", "standard")):
        return "stu"
    return None


ODA_KELIME = re.compile(r"studio|stüdyo|standart|standard|superior|deluxe|suit|daire|ekonomik|economic|economy", re.I)
TL_SATIR = re.compile(r"^(?:TL\s?)?(\d{1,3}(?:\.\d{3})+|\d{3,5})(?:,\d{2})?\s?(?:TL|₺)?$")
TL_SAYI = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{4,5})(?:,\d{2})?")


def tl(s):
    return int(s.replace(".", ""))


def oda_basligi(line):
    return (len(line) <= 70 and ODA_KELIME.search(line) and not re.search(r"\d\s?TL|TL\s?\d", line)
            and not line.endswith((".", "!", "?")))


def bloklar(text):
    """Sayfa metnini oda başlıklarına göre böler: [(başlık, [satırlar])]."""
    out, cur = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if oda_basligi(line) and oda_key(line):
            cur = (line, [])
            out.append(cur)
        elif cur:
            cur[1].append(line)
    return out


def en_dusuk(sonuc, kanal, oda, fiyat, acik=None):
    if oda and 1000 <= fiyat <= 30000:
        k = (kanal, oda)
        if k not in sonuc or fiyat < sonuc[k][0]:
            sonuc[k] = (fiyat, acik if acik and acik > fiyat else None)


def parse_etstur(text):
    """Blok: '4.787 TL' (üstü çizili) '%20' '3.830 TL' (son) ... Fiyatlar vergiler dahil."""
    s = {}
    for ad, lines in bloklar(text):
        nums = [tl(m.group(1)) for l in lines[:60] if (m := TL_SATIR.match(l))]
        if nums:
            f = min(nums)
            i = nums.index(f)
            en_dusuk(s, "etstur", oda_key(ad), f, nums[i - 1] if i > 0 else None)
    return s


def parse_trip(text):
    """Blok: '3.883 TL' (üstü çizili, vergisiz) '3.340 TL' (vergisiz) 'Toplam fiyat: 3.708 TL'
    (vergiler dahil). Vergiler dahil toplam esas alınır."""
    s = {}
    for ad, lines in bloklar(text):
        tops, prev = [], []
        for l in lines[:80]:
            m = re.match(r"Toplam fiyat:\s*(\d{1,3}(?:\.\d{3})+)", l)
            if m:
                t = tl(m.group(1))
                base = [n for n in prev if n <= t]
                acik = None
                if len(prev) >= 2 and base:
                    acik = round(max(prev) * t / min(base))
                tops.append((t, acik))
                prev = []
            elif (m2 := TL_SATIR.match(l)):
                prev.append(tl(m2.group(1)))
        for t, acik in tops:
            en_dusuk(s, "trip", oda_key(ad), t, acik)
    return s


def parse_booking(text):
    """Satır: 'TL 4.225 TL 3.802' (üstü çizili, son). Yurt dışından bakınca fiyat VERGİSİZ
    gösterilebilir. İki biçim görüldü: sayfada bir kez 'Hariç: %10 KDV, %1 devlet vergisi'
    (oran) ya da fiyatın altında '+TL 381 vergiler ve ücretler' (tutar). Vergi eklenerek
    misafirin ödediğine çevrilir. Hiçbiri yoksa fiyat vergi dahil kabul edilir ve vergi
    satırları rapora yazılır (BOOKING_VERGI_IZ) ki biçim değişirse görülsün."""
    global BOOKING_VERGI_IZ
    # 'Hariç:' ile oranlar aynı satırda ya da sonraki 1-2 satırda olabilir (görünür tarayıcıda ayrı).
    m = re.search(r"Hariç:?\s*((?:[^\n]*\n?){1,3})", text)
    oranlar = re.findall(r"%\s?(\d{1,2})\s*(?:KDV|devlet|vergi|konaklama)", m.group(1), re.I) if m else []
    if not oranlar and m:
        m = None  # 'Hariç' var ama oran yok: vergi biçimi tanınmadı → iz bırak
    vergi = 1 + sum(int(x) for x in oranlar) / 100 if oranlar else 1.0
    # Not yoksa: yurt dışından (GitHub, ABD) Booking fiyatı VERGİSİZ gösteriyor; not bazı sayfa
    # düzenlerinde hiç çıkmıyor (19.10.2026). 'vergiler dahil' yazmıyorsa Türkiye vergisi eklenir.
    varsayilan = False
    if not oranlar and not re.search(r"vergi(?:ler)?\s*(?:ve\s*ücretler\s*)?dahil", text, re.I):
        vergi, varsayilan = VARSAYILAN_VERGI, True
    ek_re = re.compile(r"\+\s?(?:TL\s?)?(\d{1,3}(?:\.\d{3})*|\d+)\s?(?:TL\s?)?(?:vergi|ücret)", re.I)
    ek_goruldu = False
    s = {}
    for ad, lines in bloklar(text):
        lines = lines[:120]
        for i, l in enumerate(lines):
            if "TL" not in l or len(l) > 40 or ek_re.search(l):
                continue
            nums = [tl(x) for x in TL_SAYI.findall(l)]
            if not nums:
                continue
            ek = 0
            for j in range(i + 1, min(i + 4, len(lines))):
                me = ek_re.search(lines[j])
                if me:
                    ek = tl(me.group(1)) if "." in me.group(1) else int(me.group(1))
                    break
            if ek:
                ek_goruldu = True
                oran = 1 + ek / nums[-1]
            else:
                oran = vergi
            f = round(nums[-1] * oran)
            acik = round(nums[0] * oran) if len(nums) >= 2 else None
            en_dusuk(s, "booking", oda_key(ad), f, acik)
    BOOKING_VERGI_IZ = []
    return s, (vergi if not ek_goruldu else 1.11), (varsayilan and not ek_goruldu)


BOOKING_VERGI_IZ = []
VARSAYILAN_VERGI = 1.11  # %10 KDV + %1 konaklama vergisi (Booking notu: 'Hariç: %10 KDV, %1 devlet vergisi')


def urls(d):
    a, b = d, d + dt.timedelta(days=1)
    return {
        "booking": ("https://www.booking.com/hotel/tr/apart-alsancak.html?checkin=%s&checkout=%s"
                    "&group_adults=2&no_rooms=1&group_children=0&selected_currency=TRY&lang=tr"
                    % (a.isoformat(), b.isoformat())),
        "etstur": ("https://www.etstur.com/Riva-Hotel-Alsancak?check_in=%s&check_out=%s&adult_1=2&child_1=0"
                   % (a.strftime("%d.%m.%Y"), b.strftime("%d.%m.%Y"))),
        "trip": ("https://tr.trip.com/hotels/detail/?city=1216&hotelid=102583877&checkin=%s&checkout=%s"
                 "&adult=2&crn=1&curr=TRY&locale=tr_TR" % (a.isoformat(), b.isoformat())),
    }


def tarihler(bugun):
    ds = {bugun, bugun + dt.timedelta(days=1), bugun + dt.timedelta(days=14)}
    for wd in (2, 5):  # önümüzdeki Çarşamba ve Cumartesi
        ds.add(bugun + dt.timedelta(days=(wd - bugun.weekday()) % 7 or 7))
    return sorted(ds)


async def oku(ctx, url):
    page = await ctx.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(10000)
        await page.mouse.wheel(0, 3000)
        await page.wait_for_timeout(4000)
        return await page.inner_text("body")
    finally:
        await page.close()


# ---------------------------------------------------------------- trivago (tüm satıcılar)
TRIVAGO_ID = 3221525  # trivago'da Riva Hotel Alsancak
TRIVAGO_ADLAR = {}  # satıcı no → ad; çalışma boyunca saklanır (site bir adı sonraki sayfada geç
                    # ya da önbellekten bildiği için hiç istemeyebiliyor).
SATICI = (("etstur", "etstur"), ("zenhotels", "zenhotels"), ("hotels.com", "hotels"), ("expedia", "expedia"),
          ("obilet", "obilet"), ("jolly", "jolly"), ("tatilbudur", "tatilbudur"), ("trip.com", "trip"),
          ("sembo", "sembo"), ("booking", "booking"), ("agoda", "agoda"), ("enuygun", "enuygun"))


def satici_key(ad):
    """trivago satıcı adı → kanal anahtarı. Otelin kendi sitesi 'site'."""
    n = ad.lower().strip()
    if "riva" in n or any(k in n for k in ("otel sitesi", "resmi site", "official site")):
        return "site"
    for k, v in SATICI:
        if k in n:
            return v
    return re.sub(r"[^a-z0-9]", "", n.translate(str.maketrans("çğıöşü", "cgiosu"))) or None


def oda_key_trivago(ad):
    """trivago'daki ZenHotels/Hotels.com oda adları Türkçeye çevrilmiş: 'Süper oda' = Superior,
    'Lüks oda' = Deluxe, 'Stüdyo Süit' = Suite. (Yalnız burada; sayfa metni ayrıştırıcıları
    yorum satırlarındaki 'süper' kelimesine takılmasın.)"""
    n = ad.lower()
    for a, b in (("süper", "superior"), ("lüks", "deluxe"), ("süit", "suite")):
        n = n.replace(a, b)
    return oda_key(n)


def parse_trivago(deals, adlar):
    """trivago teklifleri (GraphQL) → {(satıcı, oda): (fiyat, açık)}. Fiyat 'allIn' = vergiler dahil,
    gecelik TL. Oda adı (description) yoksa Studio sayılır; otelin kendi sitesi oda adsızsa atlanır."""
    s = {}
    for dl in deals:
        try:
            ad = adlar.get(dl["advertiserDetails"]["nsid"]["id"])
            f = int((dl.get("allInPricePerNight") or dl["pricePerNight"])["amount"])
        except (KeyError, TypeError, ValueError):
            continue
        k = ad and satici_key(ad)
        if not k:
            continue
        oda_ad = (dl.get("description") or "").strip()
        if oda_ad:
            oda = oda_key_trivago(oda_ad)  # tanınmayan oda adı → None → kaydedilmez
        elif k == "site":
            continue
        else:
            oda = "stu"
        cizili = (dl.get("pricePerNightStrikethrough") or {}).get("amount")
        net = (dl.get("pricePerNight") or {}).get("amount")
        en_dusuk(s, k, oda, f, round(cizili * f / net) if cizili and net else None)
    return s


async def oku_trivago(ctx, d):
    """trivago otel sayfası. 'drs-40' parametresi URL'deki tarihleri uygulatır (yoksa takvim
    'Tarih seçin' der; o durumda takvimden seçilir). Riva kartındaki 'Tüm fiyatları göster' tüm
    satıcıların tekliflerini (accommodationDealsQuery) yükletir; satıcı adları getAdvertiserDetails
    yanıtlarından gelir. Pencere açılamazsa listedeki ilk 3 teklif (accommodationSearchQuery) kullanılır."""
    e = d + dt.timedelta(days=1)
    url = ("https://www.trivago.com.tr/tr/lm/riva-hotel-alsancak-izmir?search=100-%d;dr-%s-%s;drs-40;rc-1-2"
           % (TRIVAGO_ID, d.strftime("%Y%m%d"), e.strftime("%Y%m%d")))
    donem = {"arrival": d.isoformat(), "departure": e.isoformat()}
    adlar, liste, detay, gorevler = TRIVAGO_ADLAR, [], {"deals": [], "bitti": False}, []

    async def yanit(r):
        if "/graphql?" not in r.url:
            return
        op = r.url.split("?", 1)[1].split("&")[0]
        if op not in ("getAdvertiserDetails", "accommodationSearchQuery", "accommodationDealsQuery"):
            return
        try:
            data = (await r.json()).get("data") or {}
            v = json.loads((r.request.post_data_buffer or b"{}").decode("utf-8", "replace")).get("variables") or {}
        except Exception:
            return
        if op == "getAdvertiserDetails":
            for a in (data.get("getAdvertiserDetails") or {}).get("advertiserDetails") or []:
                adlar[a["nsid"]["id"]] = (a.get("translatedName") or {}).get("value") or ""
        elif op == "accommodationSearchQuery":
            if (v.get("params") or {}).get("stayPeriod") != donem:
                return
            for a in (data.get("accommodationSearchResponse") or {}).get("accommodations") or []:
                if (a.get("nsid") or {}).get("id") == TRIVAGO_ID:
                    dl = a.get("deals") or {}
                    yeni = [x for x in [dl.get("best"), dl.get("cheapest")] + (dl.get("alternatives") or []) if x]
                    if yeni:
                        liste[:] = yeni
        else:
            p = v.get("getAccommodationDealsParams") or {}
            if p.get("stayPeriod") != donem or (p.get("accommodationNsid") or {}).get("id") != TRIVAGO_ID:
                return
            g = data.get("getAccommodationDeals") or {}
            if g.get("deals"):
                detay["deals"] = g["deals"]
                detay["bitti"] = not g.get("pollData")

    page = await ctx.new_page()
    page.on("response", lambda r: gorevler.append(asyncio.ensure_future(yanit(r))))
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)
        try:
            await page.get_by_role("button", name="Tamam", exact=True).click(timeout=5000)  # çerez
        except Exception:
            pass
        tarih = page.locator('[data-testid="search-form-calendar-value"]')
        if "Tarih" in (await tarih.inner_text(timeout=10000)):  # URL'deki tarih uygulanmadı → takvim
            if not await page.locator('[data-testid="calendar-popover"]').is_visible():
                await page.locator('[data-testid="search-form-calendar"]').click()
            for gun in (d, e):
                sec = page.locator('[data-testid="valid-calendar-day-%s"]' % gun.isoformat())
                for _ in range(12):
                    if await sec.count():
                        break
                    await page.locator('[data-testid="calendar-button-next"]').click()
                    await page.wait_for_timeout(300)
                await sec.click()
            await page.locator('[data-testid="search-button-with-loader"]').click()
        kart = page.locator('[data-testid="accommodation-list-element"]').filter(
            has=page.locator('[data-testid="favorite-button-interactivity-section-100-%d"]' % TRIVAGO_ID))
        try:
            dugme = kart.first.get_by_text("Tüm fiyatları göster")
            await dugme.wait_for(timeout=35000)  # liste teklifleri gelince çıkar
            # Takvim/üst şerit düğmenin üstüne binebiliyor; olayı doğrudan düğmeye gönder.
            await dugme.dispatch_event("click")
            for _ in range(50):  # teklifler birkaç turda (poll) gelir
                if detay["bitti"]:
                    break
                await page.wait_for_timeout(500)
        except Exception:
            pass  # pencere açılamadı → liste teklifleri
        deals = detay["deals"] or liste
        for _ in range(20):  # satıcı adları (getAdvertiserDetails) bazen geç gelir
            await page.wait_for_timeout(500)
            await asyncio.gather(*gorevler, return_exceptions=True)
            if all((dl.get("advertiserDetails") or {}).get("nsid", {}).get("id") in adlar for dl in deals):
                break
        return parse_trivago(deals, adlar)
    finally:
        await page.close()


# ---------------------------------------------------------------- TatilBudur
def parse_tatilbudur(view):
    """calculate-room-price yanıtındaki HTML: her oda 'room-type-new' bloğu, başlığı
    'room-type-title'; her seçenekte '<del>4.787</del>TL' (üstü çizili) ve
    'sell-price' data-total="3829" (toplam, vergiler dahil). En düşük = İadesiz."""
    s = {}
    for parca in view.split('class="room-type-new"')[1:]:
        m = re.search(r'room-type-title[^>]*>\s*([^<]+?)\s*<', parca)
        if not m:
            continue
        oda = oda_key(htmllib.unescape(m.group(1)))
        for p in re.finditer(r'(?:<del>\s*([\d.]+)\s*</del>[^<]*</div>\s*)?'
                             r'<div class="sell-price"[^>]*data-total="([\d.]+)"', parca):
            en_dusuk(s, "tatilbudur", oda, round(float(p.group(2))), tl(p.group(1)) if p.group(1) else None)
    return s


async def oku_tatilbudur(ctx, d):
    """Sayfa açılınca site, bugünün tarihiyle ve fiyatları gizli (hidePrice=1) olarak
    /hotel/calculate-room-price çağırır; URL'deki tarih parametrelerini dikkate almaz. Aynı isteği
    (oturumun _token'ı ile) sayfanın içinden bizim tarihimiz ve hidePrice=0 ile tekrarlarız —
    'Güncelle' düğmesinin yaptığıyla aynı."""
    e = d + dt.timedelta(days=1)
    page = await ctx.new_page()
    try:
        async with page.expect_request(lambda r: "calculate-room-price" in r.url, timeout=45000) as bilgi:
            await page.goto("https://www.tatilbudur.com/riva-hotel-alsancak", wait_until="domcontentloaded",
                            timeout=60000)
        istek = await bilgi.value
        alan = dict(parse_qsl((istek.post_data_buffer or b"").decode("utf-8", "replace"), keep_blank_values=True))
        if "_token" not in alan:
            raise RuntimeError("TatilBudur fiyat isteği bulunamadı")
        alan.update(checkInDate=d.strftime("%d.%m.%Y"), checkOutDate=e.strftime("%d.%m.%Y"),
                    adult="2", child="0", hidePrice="0")
        basliklar = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "X-Requested-With": "XMLHttpRequest"}
        if istek.headers.get("x-csrf-token"):
            basliklar["X-CSRF-TOKEN"] = istek.headers["x-csrf-token"]
        durum, govde = await page.evaluate("""async ([body, headers]) => {
            const r = await fetch('/hotel/calculate-room-price', {method: 'POST', body, headers});
            return [r.status, await r.text()];
        }""", [urlencode(alan), basliklar])
        if durum != 200:
            raise RuntimeError(f"TatilBudur HTTP {durum}")
        return parse_tatilbudur(json.loads(govde).get("view") or "")
    finally:
        await page.close()


# ---------------------------------------------------------------- Enuygun
def parse_enuygun(j, gece=1):
    """/otel/search-core/detail-search JSON: hotels[].rooms[].type.name, offers[].tryPrice.total
    (konaklama toplamı, TL, vergiler dahil), discountFrom (üstü çizili)."""
    s = {}
    for h in j.get("hotels") or []:
        for r in h.get("rooms") or []:
            if (r.get("hiddenState") or {}).get("hidden"):
                continue
            oda = oda_key((r.get("type") or {}).get("name") or "")
            for o in r.get("offers") or []:
                if (o.get("hiddenState") or {}).get("hidden"):
                    continue
                try:
                    f = float(o["tryPrice"]["total"]["amount"]) / gece
                except (KeyError, TypeError, ValueError):
                    continue
                acik = o.get("discountFrom")
                en_dusuk(s, "enuygun", oda, round(f), round(float(acik) / gece) if acik else None)
    return s


async def oku_enuygun(ctx, d):
    """'autoRequest=1' ile sayfa oda aramasını kendisi başlatır (yoksa 'Oda bul' tıklanır);
    fiyatlar /otel/search-core/detail-search yanıtından (JSON) okunur."""
    e = d + dt.timedelta(days=1)
    url = ("https://www.enuygun.com/otel/detay/riva-hotel-alsancak-428633/?checkInDate=%s&checkOutDate=%s"
           "&rooms=2&autoRequest=1" % (d.strftime("%d.%m.%Y"), e.strftime("%d.%m.%Y")))
    hedef = lambda r: "search-core/detail-search" in r.url and r.request.method == "POST"
    page = await ctx.new_page()
    try:
        try:
            async with page.expect_response(hedef, timeout=40000) as bilgi:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            yanit = await bilgi.value
        except Exception:
            async with page.expect_response(hedef, timeout=30000) as bilgi:
                await page.get_by_text("Oda bul", exact=True).first.click(timeout=10000)
            yanit = await bilgi.value
        j = await yanit.json()
        p = j.get("parameters") or {}
        if p.get("checkInDate") not in (None, d.isoformat()):
            raise RuntimeError(f"Enuygun yanlış tarih döndü: {p.get('checkInDate')}")
        return parse_enuygun(j)
    finally:
        await page.close()


async def oku_metin(ctx, kanal, url):
    """Booking / Etstur / Trip.com: sayfa metninden."""
    text = await oku(ctx, url)
    if "Riva" not in text:
        # Ör. Booking Türkiye'den bakınca ana sayfaya yönlendiriyor; uydurma fiyat yazmayalım.
        raise RuntimeError("otel sayfası açılmadı")
    if kanal == "booking":
        s, vergi, varsayilan = parse_booking(text)
        if not s:
            # 26.10.2026'dan beri sayfa açılıyor ama fiyat çıkmıyor: biçim değişti mi, iz bırak.
            fiyatli = [l.strip() for l in text.splitlines() if re.search(r"\d", l) and
                       re.search(r"TL|₺|€|US\$|\$|EUR|USD", l)][:8]
            basliklar = [ad for ad, _ in bloklar(text)][:6]
            print(f"BOOKING İZ {url[-40:]}: oda başlıkları={basliklar} · fiyatlı satırlar={fiyatli}", flush=True)
        return s, "Booking · otomatik" + (" (%11 vergi eklendi)" if varsayilan else " (vergi eklendi)" if vergi > 1 else "")
    if kanal == "etstur":
        return parse_etstur(text), "Etstur · otomatik"
    return parse_trip(text), "Trip.com · otomatik"


async def topla():
    from playwright.async_api import async_playwright
    simdi = dt.datetime.now(TR)
    zaman = simdi.strftime("%Y-%m-%d %H:%M")
    gozlem, rapor = [], []

    async def kaydet(d, ad, is_):
        """Bir kaynağı okur; hata/zaman aşımı diğer kaynakları durdurmaz."""
        try:
            s, kaynak = await asyncio.wait_for(is_, 150)
        except Exception as e:
            rapor.append(f"{d} {ad}: HATA {(str(e) or type(e).__name__)[:120]}")
            return
        for (k, oda), (f, acik) in s.items():
            gozlem.append({"tarih": d.isoformat(), "kanal": k, "oda": oda, "fiyat": f,
                           "acik": acik, "etiket": "", "kaynak": kaynak, "zaman": zaman})
        cok = ad == "trivago"  # birçok satıcı: satıcı/oda=fiyat
        rapor.append(f"{d} {ad}: " + (", ".join(f"{k}/{o}={f}" if cok else f"{o}={f}"
                                                 for (k, o), (f, _) in sorted(s.items())) or "FİYAT BULUNAMADI"))

    async def ile(is_, kaynak):
        return await is_, kaynak

    async with async_playwright() as p:
        # Görünür tarayıcı: trivago/TatilBudur/Enuygun görünmez (headless) tarayıcıyı engelliyor.
        # Sunucuda ekran yok → 'xvfb-run -a python fiyat_topla.py ...' ile çalıştırılır.
        br = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"])
        ctx = await br.new_context(locale="tr-TR", timezone_id="Europe/Istanbul", user_agent=UA,
                                   viewport={"width": 1366, "height": 900})
        # Booking görünmez tarayıcıyı engellemiyor ve yalnız o modda vergi notunu ('Hariç: %10 KDV,
        # %1 devlet vergisi') metne koyuyor; görünür modda not yok, fiyat vergisiz kalıyor.
        brh = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        ctxh = await brh.new_context(locale="tr-TR", timezone_id="Europe/Istanbul", user_agent=UA,
                                     viewport={"width": 1366, "height": 900})
        for d in tarihler(simdi.date()):
            # trivago önce: aynı zaman damgasında sonraki gözlem kazanır (checks.fiyat_gozlemler),
            # böylece kanalın kendi sayfasından okunan fiyat trivago'daki kopyasının önüne geçer.
            await kaydet(d, "trivago", ile(oku_trivago(ctx, d), "trivago · otomatik"))
            for kanal, url in urls(d).items():
                await kaydet(d, kanal, oku_metin(ctxh if kanal == "booking" else ctx, kanal, url))
            await kaydet(d, "tatilbudur", ile(oku_tatilbudur(ctx, d), "TatilBudur · otomatik"))
            if os.environ.get("GITHUB_ACTIONS"):
                # Enuygun'un kendi sayfası GitHub sunucusundan engelleniyor (19.10.2026);
                # Enuygun fiyatı trivago'dan geliyor. Yerelde (Türkiye) doğrudan okunur.
                pass
            else:
                await kaydet(d, "enuygun", ile(oku_enuygun(ctx, d), "Enuygun · otomatik"))
        await brh.close()
        await br.close()
    return gozlem, rapor


def birlestir(eski, yeni, bugun):
    """Önceki gözlemleri korur (geçmiş için), geçmiş tarihleri ve 30 günden eskiyi atar."""
    sinir = (bugun - dt.timedelta(days=30)).isoformat()
    tut = [g for g in eski if g["tarih"] >= (bugun - dt.timedelta(days=1)).isoformat()
           and g.get("zaman", "") >= sinir]
    return tut + yeni


def main():
    cikti = sys.argv[1] if len(sys.argv) > 1 else "otomatik.json"
    eski = []
    if len(sys.argv) > 2:
        try:
            eski = json.load(open(sys.argv[2], encoding="utf-8")).get("gozlemler", [])
        except (OSError, ValueError):
            eski = []
    gozlem, rapor = asyncio.run(topla())
    print("\n".join(rapor))
    bugun = dt.datetime.now(TR).date()
    json.dump({"aciklama": "Otomatik toplanan herkese açık fiyatlar (fiyat_topla.py, GitHub Actions).",
               "guncellendi": dt.datetime.now(TR).strftime("%Y-%m-%d %H:%M"),
               "gozlemler": birlestir(eski, gozlem, bugun)},
              open(cikti, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not gozlem:
        print("HİÇ FİYAT OKUNAMADI", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
