"""Canlı fiyat toplayıcı — otelin kendi rezervasyon motorundan (Elektra bookingapi).

Gerçek bir tarayıcıyla rivahotelalsancak.rezervasyonal.com açılır; sayfa kendi captcha'sını
(Friendly Captcha) çözüp herkese açık oturum anahtarını (JWT) alır. Sonra aynı sayfanın içinden,
motorun kullandığı istekle önümüzdeki GUN günün her gecesi için oda fiyatları sorulur:
  GET https://bookingapi.elektraweb.com/hotel/29481/price/?fromdate=D&todate=D+1&adult=2&currency=TRY...
Misafirin gördüğü fiyat budur: doluluk kuralları ("30 odadan sonra artar") ve kampanyalar dahil.

Motor çok sık sorguda IP'yi engelliyor (429) → sorgular sırayla ve aralıklı; saatte bir çalıştırın.
Çıktı (site oda-fiyatlari.html bunu okur):
  {"guncellendi": ISO, "para": "TRY", "gunler": {"YYYY-AA-GG": {"eko": {"f": 3336, "k": 4, "iade": true}, ...}}}
  Bir oda tipi o gece satışta değilse (dolu / stop-sell) anahtarı hiç yazılmaz.
Kullanım:  xvfb-run -a python motor_fiyat.py <çıktı.json> [gün sayısı]
Bulut: .github/workflows/canli-fiyat.yml (saatte bir) → 'canli-fiyat' dalı → site oda-fiyatlari.html okur:
  https://raw.githubusercontent.com/hotelalsancak-netizen/hotelalsancak-netizen.github.io/canli-fiyat/canli-fiyat.json
Not (23.10.2026): herkese açık oturum anahtarı 15 dk geçerli → her çalışmada captcha yeniden çözülür. Aynı IP'den
art arda denemede captcha zorlaşıp takılabiliyor; bulutta her çalışma farklı IP'den, saatte bir.
Güvenlik: Verinin yarısından azı gelirse çıktı YAZILMAZ (eski iyi veri korunur), çıkış kodu 1.
"""
import asyncio, datetime as dt, json, os, sys
from zoneinfo import ZoneInfo
from playwright.async_api import async_playwright

TR = ZoneInfo("Europe/Istanbul")
OTEL = 29481
MOTOR = "https://rivahotelalsancak.rezervasyonal.com/"
API = "https://bookingapi.elektraweb.com/hotel/%d/price/" % OTEL
ARALIK_MS = 1500


def oda_key(ad):
    n = (ad or "").lower()
    if any(k in n for k in ("1+1", "suit", "suite")): return "sui"
    if any(k in n for k in ("ekonomik", "economic", "economy")): return "eko"
    if "superior" in n: return "sup"
    if "deluxe" in n: return "dlx"
    if any(k in n for k in ("studio", "stüdyo", "standart", "standard")): return "stu"
    return None


def ozet(teklifler):
    """Bir gecenin teklif listesi → {oda_key: {f: en düşük TL, k: kalan oda, iade: bool}}."""
    out = {}
    for t in teklifler or []:
        k = oda_key(t.get("room-type"))
        if not k or "kahvalt" not in (t.get("board-type") or "").lower():
            continue
        if (t.get("rate-rules") or {}).get("stop-sell"):
            continue
        f = t.get("discounted-price") if t.get("discounted-price") is not None else t.get("price")
        if not f or f <= 0:
            continue
        f = int(round(f))
        kalan = int(t.get("room-to-sell") or 0)
        iade = bool((t.get("cancellation-penalty") or {}).get("is-refundable"))
        o = out.get(k)
        if o is None or f < o["f"]:
            out[k] = {"f": f, "k": max(kalan, (o or {}).get("k", 0)), "iade": iade}
        else:
            o["k"] = max(o["k"], kalan)
    return out


async def main(cikti, gun):
    bugun = dt.datetime.now(TR).date()
    ilk = bugun.isoformat(); ertesi = (bugun + dt.timedelta(days=1)).isoformat()
    async with async_playwright() as p:
        yol = os.environ.get("CHROME_YOLU")
        b = await p.chromium.launch(headless=False, **({"executable_path": yol} if yol else {}))
        ctx = await b.new_context(locale="tr-TR", viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()
        ilk_cevap = asyncio.get_event_loop().create_future()
        async def cevap(r):
            if "/price/" in r.url and not ilk_cevap.done():
                try: ilk_cevap.set_result(await r.json())
                except Exception: pass
        page.on("response", cevap)
        adres = f"{MOTOR}?checkin={ilk}&checkout={ertesi}&adult=2&child=0"
        for deneme in (1, 2):              # captcha takılırsa sayfayı bir kez yenile
            await page.goto(adres, wait_until="load", timeout=60000)
            try:
                await asyncio.wait_for(asyncio.shield(ilk_cevap), timeout=150)   # captcha çözülüp sayfa arayana kadar
                break
            except asyncio.TimeoutError:
                print(f"  deneme {deneme}: captcha çözülmedi")
        if not ilk_cevap.done():
            sys.exit("motor fiyat sorgusu yapmadı (captcha çözülmedi) — eski veri korunur")
        jwt = await page.evaluate("() => (typeof jwt !== 'undefined' ? jwt : null)")
        if not jwt:
            sys.exit("oturum anahtarı (jwt) okunamadı")
        gunler, hata = {}, 0
        for i in range(gun):
            d = bugun + dt.timedelta(days=i)
            q = (f"?fromdate={d}&todate={d + dt.timedelta(days=1)}&adult=2&childage=&currency=TRY&nationality="
                 f"&onlybestoffer=false&room-type-group-id=&skip-stopsell=&language=tr&promo-code=&GETPRICEDETAILS=true&child=0")
            sonuc = await page.evaluate("""async ([url, jwt]) => {
                try {
                  const r = await fetch(url, {headers: {'Content-Type':'application/json','Accept':'application/json','Authorization':'Bearer '+jwt}});
                  return {s: r.status, j: r.ok ? await r.json() : null};
                } catch (e) { return {s: 0, j: null}; }
            }""", [API + q, jwt])
            if sonuc["s"] == 200 and isinstance(sonuc["j"], list):
                gunler[d.isoformat()] = ozet(sonuc["j"])
            else:
                hata += 1
                print(f"  {d}: HTTP {sonuc['s']}")
                if sonuc["s"] == 429:
                    print("  motor sorgu sınırına takıldı, duruluyor"); break
            await page.wait_for_timeout(ARALIK_MS)
        await b.close()
    if len(gunler) < gun / 2:
        sys.exit(f"yetersiz veri: {len(gunler)}/{gun} gün — çıktı yazılmadı")
    veri = {"guncellendi": dt.datetime.now(TR).isoformat(timespec="seconds"), "para": "TRY",
            "kaynak": "rivahotelalsancak.rezervasyonal.com", "gunler": gunler}
    gecici = cikti + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(gecici, cikti)
    print(f"tamam: {len(gunler)} gün, {hata} hata → {cikti}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 30))
