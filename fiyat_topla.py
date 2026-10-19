"""Kanal fiyat toplayıcı — Fiyat Kontrol sayfasının otomatik gözlemleri.

GitHub Actions'ta (yurt dışı sunucu) gerçek bir tarayıcıyla kanalların HERKESE AÇIK otel
sayfalarını açar, oda başına en düşük (iptal edilemez) fiyatı okur ve gözlem listesine yazar.
Yurt dışından çalıştığı için Booking'in Türkiye engeli burada geçerli değil.

19.10.2026 testi: Booking, Etstur, Trip.com okunuyor. Hotels.com, TatilBudur, trivago
(Akamai) ve Enuygun (Cloudflare) otomatik ziyareti engelliyor; onlar elle kontrol edilir.

Kullanım:  python fiyat_topla.py <çıktı.json> [önceki.json]
Çıktı, checks.fiyat_gozlemler()'in okuduğu biçimdedir (gozlem.json ile aynı alanlar).
"""
import asyncio
import datetime as dt
import json
import re
import sys
from zoneinfo import ZoneInfo

TR = ZoneInfo("Europe/Istanbul")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")

# Oda adı → Fiyat Kontrol oda anahtarı. "Superior Deluxe" kanallarda Superior odadır.
def oda_key(ad):
    n = ad.lower()
    if any(k in n for k in ("1+1", "daire", "suit", "suite")):
        return "sui"
    if "ekonomik" in n or "economic" in n:
        return "eko"
    if "superior" in n:
        return "sup"
    if "deluxe" in n:
        return "dlx"
    if any(k in n for k in ("studio", "stüdyo", "standart", "standard")):
        return "stu"
    return None


ODA_KELIME = re.compile(r"studio|stüdyo|standart|standard|superior|deluxe|suit|daire|ekonomik|economic", re.I)
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
    gösterilir ('Hariç: %10 KDV, %1 devlet vergisi'); vergi eklenerek misafirin ödediğine çevrilir."""
    m = re.search(r"Hariç:\s*([^\n]{0,80})", text)
    vergi = 1 + sum(int(x) for x in re.findall(r"%\s?(\d{1,2})", m.group(1))) / 100 if m else 1.0
    s = {}
    for ad, lines in bloklar(text):
        for l in lines[:120]:
            if "TL" not in l:
                continue
            nums = [tl(x) for x in TL_SAYI.findall(l)]
            if not nums or len(l) > 40:
                continue
            f = round(nums[-1] * vergi)
            acik = round(nums[0] * vergi) if len(nums) >= 2 else None
            en_dusuk(s, "booking", oda_key(ad), f, acik)
    return s, vergi


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


async def topla():
    from playwright.async_api import async_playwright
    simdi = dt.datetime.now(TR)
    zaman = simdi.strftime("%Y-%m-%d %H:%M")
    gozlem, rapor = [], []
    async with async_playwright() as p:
        br = await p.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await br.new_context(locale="tr-TR", timezone_id="Europe/Istanbul", user_agent=UA,
                                   viewport={"width": 1366, "height": 900})
        for d in tarihler(simdi.date()):
            for kanal, url in urls(d).items():
                try:
                    text = await oku(ctx, url)
                    if kanal == "booking":
                        s, vergi = parse_booking(text)
                        kaynak = "Booking · otomatik" + (" (vergi eklendi)" if vergi > 1 else "")
                    elif kanal == "etstur":
                        s, kaynak = parse_etstur(text), "Etstur · otomatik"
                    else:
                        s, kaynak = parse_trip(text), "Trip.com · otomatik"
                    for (k, oda), (f, acik) in s.items():
                        gozlem.append({"tarih": d.isoformat(), "kanal": k, "oda": oda, "fiyat": f,
                                       "acik": acik, "etiket": "", "kaynak": kaynak, "zaman": zaman})
                    rapor.append(f"{d} {kanal}: " + (", ".join(f"{o}={f}" for (_, o), (f, _) in sorted(s.items())) or "FİYAT BULUNAMADI"))
                except Exception as e:
                    rapor.append(f"{d} {kanal}: HATA {str(e)[:120]}")
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
