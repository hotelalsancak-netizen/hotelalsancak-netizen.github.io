#!/usr/bin/env python3
"""Son dakika indirimi düzeltmesi — Trip.com ve obilet, Booking/Expedia ile aynı fiyatı göstersin.

Sahibi (14.11.2026): "booking expedia gibi Trip'i de sürekli kontrol eden kontrol yaz, sürekli indirim
yapıyor yapamasın ... obilet için de geçerli", "Trip Booking Expedia ile aynı fiyat olacak".

Teşhis (11–14.11 okumaları, görülen ÷ hedef): Trip 4+ gün sonrası Stüdyo 0,967, Deluxe 0,992; son 3 gece
0,83–0,92 (Trip kendi son dakika indirimi). obilet 4+ gün 1,000; son 3 gece 0,86–0,92.

Kaldıraç: Elektra "Kanal Fiyat Çarpanları" (HOTEL_CHANNELMANAGER_PRICING), kanal başına:
  * UZAK satır, oda tipi başına: bugün+YAKIN_GUN → 31.03.2027. Her gün başlangıcı bir gün ileri kayar.
  * YAKIN satırlar, gece × oda tipi başına tek gün: bugün … bugün+YAKIN_GUN−1.
Uzun satırın içine tek gecelik satır eklenemiyor (Elektra "başarılı" deyip yok sayıyor, 13.11 denendi);
bu yüzden ikisi çakışmaz: önce uzak satır kaydırılır, açılan geceye tek günlük satır eklenir.

Her gece (yakın) ya da oda türü (uzak) için: o satırın DEĞERİ en son değiştikten BEKLE_DK sonra alınmış
okumalar (GetLog) → oran = ortanca(görülen ÷ Elektra fiyatı TL; Booking'in gösterdiği). |oran − 1| > ESIK ise yeni % = (1 + eski%) ÷ oran
− 1. Yakın gecede tek bir okuma yeter (gece başına okuma az); tek oran o gecenin bütün odalarına uygulanır
(okunan odaların ortancası). Uzakta oda türü başına; okunmayan oda türü okunanların ortancasını alır.
Değeri değişmeyen satırın eski okumaları geçerli kalır, böylece gidip gelme olmaz.
Hiçbir satır silinmez. --kuru: yazmadan göster. --kanal trip|obilet: yalnız biri.
"""
import argparse
import datetime as dt
import json
import statistics
import sys
import time

import requests

import checks
import elektra_api as E
import fiyat_bandi as FB

KANALLAR = {   # panel anahtarı → (ad, CHANNELMANAGERID, HOTELCHANNELMANAGERID)
    "trip": ("Trip.com", 72, 59207),
    "obilet": ("obilet", 153, 57720),
}
RATETYPE = 44257
SON = dt.date(2027, 3, 31)
YAKIN_GUN = 4            # bugün + 3 gece tek tek; sonrası uzak satır
ESIK = 0.025             # ±%2,5'ten küçük sapma "hedefte"
ALT, UST = -20.0, 25.0   # % sınırları
TAZE_SAAT = 6            # uzak geceler
YAKIN_TAZE_DK = 240      # yakın gecede doluluk/fiyat hızlı değişir; okuma bugünü her turda okumuyor
BEKLE_DK = 20
ODALAR = ("stu", "sup", "dlx", "sui")     # Ekonomik OTA'da satılmıyor


def satirlar(e, hid, kanal):
    r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                 "Where": [{"Column": "HOTELID", "Operator": "=", "Value": hid},
                           {"Column": "CHANNELID", "Operator": "=", "Value": kanal}], "Select": [],
                 "Paging": {"ItemsPerPage": 1000, "Current": 1}},   # yoksa yalnız 10 satır döner
                action_name="Select")
    return ((r or {}).get("ResultSets") or [[]])[0]


def deger_degisim(e, hid, satir):
    """Satırın yüzdesinin en son değiştiği an (İstanbul, 'YYYY-AA-GG SS:DD'); yalnız tarih kaydırma sayılmaz."""
    if not satir:
        return ""
    for deneme in range(3):
        try:
            r = e._post("GetLog/HOTEL_CHANNELMANAGER_PRICING",
                        {"Object": "HOTEL_CHANNELMANAGER_PRICING", "PrimaryKey": satir["ID"], "Tenant": hid},
                        action_name="GetLog")
            break
        except Exception:
            time.sleep(5)
    else:
        return "9999"     # kayıt okunamadı → hiçbir okuma sayılmaz, bu satıra dokunulmaz (güvenli taraf)
    kayit = sorted(((x.get("LOGTIMEUTC", ""), x.get("BODY") or "{}")
                    for x in ((r or {}).get("ResultSets") or [[]])[0]))
    son, onceki = "", None
    for t, body in kayit:
        try:
            y = json.loads(body).get("WEEKDAYPERCENT")
        except ValueError:
            y = None
        if y != onceki:
            son, onceki = t, y
    if not son:
        return ""
    t = dt.datetime.strptime(son[:16], "%Y-%m-%d %H:%M") + dt.timedelta(hours=3, minutes=BEKLE_DK)
    return t.strftime("%Y-%m-%d %H:%M")


def row(hid, kanal, rt, a, b, y, eski=None):
    r = {"HOTELID": hid, "CHANNELID": kanal, "ROOMTYPEID": rt, "FROMDATE": a.isoformat(), "TODATE": b.isoformat(),
         "WEEKDAYPERCENT": y, "WEEKDAYAMOUNT": 0, "WEEKENDPERCENT": y, "WEEKENDAMOUNT": 0, "AVAILABILITYOFFSET": 0}
    if eski:
        r["ID"] = eski["ID"]
    return r


def kaydet(e, r):
    islem = "Update" if "ID" in r else "Insert"
    x = e._post(f"{islem}/HOTEL_CHANNELMANAGER_PRICING",
                {"Object": "HOTEL_CHANNELMANAGER_PRICING", "Row": r}, action_name=islem)
    if not (x or {}).get("Success"):
        raise E.ElektraError(f"HOTEL_CHANNELMANAGER_PRICING {islem} {r}: {x}")


def gonder(e, hid, kanal, hcm, rt, a, b):
    while a <= b:
        s = min(b, a + dt.timedelta(days=89))
        p = {"FROM": a.isoformat(), "TO": s.isoformat(), "ROOMTYPEID": rt, "RATETYPEID": RATETYPE,
             "CHANNELMANAGERID": kanal, "HOTELCHANNELMANAGERID": hcm, "WHATTOREFRESH": 1, "HOTELID": hid}
        for o in ("SP_RESEND_HOTEL_ROOMTYPE_AVAILABILITY", "SP_RESEND_CHANGE_COMMAND"):
            e._post("Execute/" + o, {"Object": o, "Parameters": p}, action_name="Execute")
        a = s + dt.timedelta(days=1)


def yeni_deger(cur, oranlar):
    if not oranlar:
        return cur, None
    o = statistics.median(oranlar)
    if abs(o - 1) <= ESIK:
        return cur, o
    return round(max(ALT, min(UST, ((1 + cur / 100) / o - 1) * 100)), 2), o


def calistir(e, env, hid, anahtar, bugun, simdi, fiyat, kuru):
    ad, kanal, hcm = KANALLAR[anahtar]
    tipler = {k: [rt for rt, _ in FB.ODA_TIPLERI[k]] for k in ODALAR}
    uzak_bas = bugun + dt.timedelta(days=YAKIN_GUN)
    rows = satirlar(e, hid, kanal)
    uzun = {s["ROOMTYPEID"]: s for s in rows if str(s["FROMDATE"])[:10] < str(s["TODATE"])[:10]
            and str(s["TODATE"])[:10] >= bugun.isoformat()}
    gun = {(dt.date.fromisoformat(str(s["FROMDATE"])[:10]), s["ROOMTYPEID"]): s for s in rows
           if str(s["FROMDATE"])[:10] == str(s["TODATE"])[:10] and str(s["TODATE"])[:10] >= bugun.isoformat()}
    sinir = (simdi - dt.timedelta(hours=TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    ysinir = (simdi - dt.timedelta(minutes=YAKIN_TAZE_DK)).strftime("%Y-%m-%d %H:%M")
    okuma = []   # (gece, oda türü, zaman, oran)
    # Kıyas: Elektra'nın o geceki fiyatı (TL) = Booking/Expedia'nın gösterdiği. Panel hedefi değil; iptalle
    # doluluk düşse de fiyat inmez, Trip yine Booking'e eşit olmalı.
    for g in checks.fiyat_tum_gozlemler():
        d, k, f, z = checks.pdate(g.get("tarih")), g.get("oda", "stu"), g.get("fiyat"), g.get("zaman", "")
        if g.get("kanal") != anahtar or k not in ODALAR or not f or not d or not bugun <= d <= SON:
            continue
        if z < (ysinir if d < uzak_bas else sinir):
            continue
        p = fiyat.get((d, tipler[k][0]))
        if p and (d, k) not in checks.ELLE_FIYAT:
            okuma.append((d, k, z, f / (p * FB.KUR)))
    yazilacak, gonderilecek = [], set()

    # 1) UZAK satırlar: oda türü başına oran
    uzak_yeni, uzak_oran = {}, {}
    for k in ODALAR:
        s = uzun.get(tipler[k][0])
        cur = float(s["WEEKDAYPERCENT"]) if s else 0.0
        degisim = deger_degisim(e, hid, s)
        o = [x[3] for x in okuma if x[1] == k and x[0] >= uzak_bas and x[2] > degisim]
        uzak_yeni[k], uzak_oran[k] = yeni_deger(cur, o)
    okunan = [v for v in uzak_oran.values() if v]
    for k in ODALAR:             # okunmayan oda türü: okunanların ortancası (aynı cari değerden)
        if uzak_oran[k] is None and okunan:
            s = uzun.get(tipler[k][0])
            cur = float(s["WEEKDAYPERCENT"]) if s else 0.0
            uzak_yeni[k], uzak_oran[k] = yeni_deger(cur, [statistics.median(okunan)])
    for k in ODALAR:
        for rt in tipler[k]:
            s = uzun.get(rt)
            cur = float(s["WEEKDAYPERCENT"]) if s else None
            if s and (str(s["FROMDATE"])[:10] != uzak_bas.isoformat() or abs(cur - uzak_yeni[k]) >= 0.5):
                yazilacak.append(row(hid, kanal, rt, uzak_bas, SON, uzak_yeni[k] if abs(cur - uzak_yeni[k]) >= 0.5 else cur, s))
                if abs(cur - uzak_yeni[k]) >= 0.5:
                    gonderilecek.add((rt, uzak_bas, SON))
            elif not s and abs(uzak_yeni[k]) >= 0.5:
                yazilacak.append(row(hid, kanal, rt, uzak_bas, SON, uzak_yeni[k]))
                gonderilecek.add((rt, uzak_bas, SON))
        print(f"{ad} uzak {k}: %{(float(uzun[tipler[k][0]]['WEEKDAYPERCENT']) if tipler[k][0] in uzun else 0):g} → "
              f"%{uzak_yeni[k]:g}" + (f" (görülen÷hedef {uzak_oran[k]:.3f})" if uzak_oran[k] else " (okuma yok)"))

    # 2) YAKIN geceler: oda türünün o geceki okuması varsa onunla (Trip Suit'e daha derin indiriyor, 15.11),
    #    yoksa o gecenin bütün okumalarının ortancasıyla. Her oda türü kendi satırının son değişiminden sonrasını sayar.
    for i in range(YAKIN_GUN):
        d = bugun + dt.timedelta(days=i)
        hepsi = [x[3] for x in okuma if x[0] == d]
        for k in ODALAR:
            degisim = deger_degisim(e, hid, gun.get((d, tipler[k][0])))
            o = ([x[3] for x in okuma if x[0] == d and x[1] == k and x[2] > degisim]
                 or [x[3] for x in okuma if x[0] == d and x[2] > degisim])
            for rt in tipler[k]:
                s = gun.get((d, rt))
                if s:
                    cur = float(s["WEEKDAYPERCENT"])
                else:   # bu geceyi önceden uzak satır kapsıyordu (dün kaydı) → onun değeriyle başla
                    u = uzun.get(rt)
                    cur = float(u["WEEKDAYPERCENT"]) if u and str(u["FROMDATE"])[:10] <= d.isoformat() else 0.0
                y, oran = yeni_deger(cur, o)
                if not s or abs(y - cur) >= 0.5:
                    yazilacak.append(row(hid, kanal, rt, d, d, y, s))
                    gonderilecek.add((rt, d, d))
        if hepsi:
            print(f"{ad} {d}: {len(hepsi)} okuma, görülen÷hedef ortanca {statistics.median(hepsi):.3f}")

    if not yazilacak:
        print(f"{ad}: değişiklik yok")
        return
    for r in yazilacak:
        print(f"   {'güncelle' if 'ID' in r else 'ekle'} {r['ROOMTYPEID']} {r['FROMDATE']}–{r['TODATE']} %{r['WEEKDAYPERCENT']:g}")
    if kuru:
        return
    # Sıra önemli: önce uzak satırlar (kaydırma), sonra açılan gecelere tek günlük satırlar.
    for r in sorted(yazilacak, key=lambda r: r["FROMDATE"] == r["TODATE"]):
        kaydet(e, r)
    requests.get(f"https://channelmanager.elektraweb.com/booking?hotelId={hid}&action=resetcache"
                 "&resetCacheByHotel=true", headers={"Authorization": e.token}, timeout=60)
    for rt, a, b in sorted(gonderilecek):
        gonder(e, hid, kanal, hcm, rt, a, b)
    print(f"{ad}: {len(yazilacak)} satır yazıldı, {len(gonderilecek)} gönderim")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true")
    ap.add_argument("--kanal", choices=sorted(KANALLAR))
    a = ap.parse_args()
    e, env = E.connect()
    hid = int(env.get("ELEKTRA_HOTELID", E.DEFAULT_TENANT))
    simdi = dt.datetime.now(FB.ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
    bugun = simdi.date()
    FB.KUR = FB.elektra_kur(e, hid, bugun)
    if not FB.KUR:
        print("kur okunamadı; dokunmadım")
        return
    fiyat = FB.elektra_fiyatlar(e, hid, bugun, bugun + dt.timedelta(days=120))
    for k in ([a.kanal] if a.kanal else KANALLAR):
        try:
            calistir(e, env, hid, k, bugun, simdi, fiyat, a.kuru)
        except Exception as ex:      # biri bozulursa öteki yine çalışsın
            print(f"{k}: HATA {ex}")


if __name__ == "__main__":
    sys.exit(main())
