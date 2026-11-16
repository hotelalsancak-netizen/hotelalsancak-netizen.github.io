#!/usr/bin/env python3
"""Kanal eşitleme — her kanalda misafirin gördüğü fiyat Booking ile aynı kalsın, yalnız Elektra'dan.

Sahibi (16.11.2026): "senin görevin fark olmamasını sağlamak ... her gün panellere giremeyiz, Elektra'dan
bunu yapman lazım". ets_duzelt.py (Etstur, 13.11) bütün kanallara genişletildi; gece_duzelt.py'nin
(14–16.11) hatalarından ders alındı: obilet değişikliği saatlerce yansıtmadı, program her saat biraz daha
indirip −%14'e gitti; yakın gece okumaları (oda dolunca başka oda) güvenilmez.

Kaldıraç: Elektra "Kanal Fiyat Çarpanları" (HOTEL_CHANNELMANAGER_PRICING), kanal × oda tipi başına TEK uzun
satır (→ 31.03.2027). Uzun satırın içine tek gecelik satır eklenemez (Elektra yok sayar, 13.11 denendi);
o yüzden yalnız uzun satır. Yakın gecelerdeki (0–2 gün) kanalın kendi son dakika indirimi buradan
düzeltilmez; o, kanalın kendi panelindeki promosyondan kapatılır.

Her kanal × oda türü için (yarım saatte bir, fiyat-bandi.yml):
  1. Okumalar: son TAZE_SAAT, bugün+YAKIN_GUN … +UFUK_GUN geceleri, satırın değeri en son değiştikten
     BEKLE_DK sonra alınmış. Oran = görülen ÷ Elektra'nın o geceki TL fiyatı (Booking'in gösterdiği).
     En az EN_AZ_OKUMA okuma, en az 2 ayrı gece. Ortanca.
  2. |oran − 1| ≤ ESIK → hedefte, dokunma.
  3. YANIT DENETİMİ: satır son 48 saatte değiştiyse, değişiklikten önceki okumaların oranıyla kıyasla;
     oran beklenen yönde beklenen yolun yarısı kadar bile gitmediyse kanal yansıtmıyor demektir → dokunma.
  4. Yeni % = (1 + eski%) ÷ oran − 1; bir adımda en fazla ADIM puan; [ALT, UST] içinde.
  5. Satır güncellenir (yoksa eklenir), kanal önbelleği temizlenir (resetcache), oda yeniden gönderilir.
Hiçbir satır silinmez. --kuru: yazmadan göster. --kanal: yalnız biri.
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

# panel anahtarı → (ad, CHANNELMANAGERID, HOTELCHANNELMANAGERID, okumada hariç oda türleri, okuma çarpanı)
KANALLAR = {
    "booking":        ("Booking", 12, 23670, ("sui",), 1.0),      # Suit okuması 3 kişilik (×1,05)
    "hotels":         ("Expedia", 10, 23672, (), 0.9),            # trivago üye OLMAYAN fiyatı gösterir
    "etstur":         ("Etstur", 147, 50099, (), 1.0),
    "trip":           ("Trip.com", 72, 59207, (), 1.0),
    "obilet":         ("obilet", 153, 57720, (), 1.0),
    "enuygun":        ("Enuygun", 136, 40136, ("sui",), 1.0),     # Suit okuması 4 kişilik (×1,10)
    "jolly":          ("Jollytur", 83, 38893, (), 1.0),
    "tatilbudur":     ("TatilBudur", 107, 24784, (), 1.0),
    "tatilsepeticom": ("Tatilsepeti", 78, 24226, (), 1.0),
}
RATETYPE = 44257
SON = dt.date(2027, 3, 31)
ESIK = 0.025
ADIM = 4.0                # puan — bir çalışmada en fazla bu kadar değişir
ALT, UST = -15.0, 15.0
TAZE_SAAT = 8
YAKIN_GUN = 3
UFUK_GUN = 60
EN_AZ_OKUMA = 3
BEKLE_DK = 30
ODALAR = ("stu", "sup", "dlx", "sui")


def satirlar(e, hid, kanal):
    r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                 "Where": [{"Column": "HOTELID", "Operator": "=", "Value": hid},
                           {"Column": "CHANNELID", "Operator": "=", "Value": kanal}], "Select": [],
                 "Paging": {"ItemsPerPage": 1000, "Current": 1}},   # yoksa yalnız 10 satır döner
                action_name="Select")
    return ((r or {}).get("ResultSets") or [[]])[0]


def gecmis(e, hid, satir):
    """[(İstanbul zamanı 'YYYY-AA-GG SS:DD', %)] — yalnız değerin değiştiği kayıtlar. Okunamazsa None."""
    if not satir:
        return []
    for _ in range(3):
        try:
            r = e._post("GetLog/HOTEL_CHANNELMANAGER_PRICING",
                        {"Object": "HOTEL_CHANNELMANAGER_PRICING", "PrimaryKey": satir["ID"], "Tenant": hid},
                        action_name="GetLog")
            break
        except Exception:
            time.sleep(5)
    else:
        return None
    out, onceki = [], object()
    for t, body in sorted((x.get("LOGTIMEUTC", ""), x.get("BODY") or "{}")
                          for x in ((r or {}).get("ResultSets") or [[]])[0]):
        try:
            y = float(json.loads(body).get("WEEKDAYPERCENT") or 0)
        except (ValueError, TypeError):
            continue
        if y != onceki:
            tr = dt.datetime.strptime(t[:16], "%Y-%m-%d %H:%M") + dt.timedelta(hours=3)
            out.append((tr.strftime("%Y-%m-%d %H:%M"), y))
            onceki = y
    return out


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


def calistir(e, hid, anahtar, bugun, simdi, fiyat, gozlem, kuru):
    ad, kanal, hcm, haric, okuma_kat = KANALLAR[anahtar]
    rows = satirlar(e, hid, kanal)
    ilk, son_gece = bugun + dt.timedelta(days=YAKIN_GUN), bugun + dt.timedelta(days=UFUK_GUN)
    okuma = {}   # oda türü → [(zaman, gece, oran)]
    for g in gozlem:
        d, k, f, z = checks.pdate(g.get("tarih")), g.get("oda", "stu"), g.get("fiyat"), g.get("zaman", "")
        if g.get("kanal") != anahtar or k not in ODALAR or k in haric or not f or not d or not ilk <= d <= son_gece:
            continue
        if (d, k) in checks.ELLE_FIYAT:
            continue
        p = fiyat.get((d, FB.ODA_TIPLERI[k][0][0]))
        if p:
            kat = okuma_kat if "trivago" in str(g.get("kaynak", "")) else 1.0
            okuma.setdefault(k, []).append((z, d, f * kat / (p * FB.KUR)))
    sinir = (simdi - dt.timedelta(hours=TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    degisen = []
    for k in ODALAR:
        tipler = [rt for rt, _ in FB.ODA_TIPLERI[k]]
        uzun = {}
        for s in rows:
            if s["ROOMTYPEID"] in tipler and str(s["TODATE"])[:10] == SON.isoformat() \
                    and str(s["FROMDATE"])[:10] < str(s["TODATE"])[:10]:
                uzun[s["ROOMTYPEID"]] = s
        s0 = uzun.get(tipler[0])
        cur = float(s0["WEEKDAYPERCENT"]) if s0 else 0.0
        gc = gecmis(e, hid, s0)
        if gc is None:
            print(f"{ad} {k}: değişiklik kaydı okunamadı · dokunmadım")
            continue
        t_deg = gc[-1][0] if gc else ""      # satırın değerinin en son değiştiği (ya da eklendiği) an
        t_bas = ((dt.datetime.strptime(t_deg, "%Y-%m-%d %H:%M") + dt.timedelta(minutes=BEKLE_DK))
                 .strftime("%Y-%m-%d %H:%M") if t_deg else "")
        sonra = [x for x in okuma.get(k, []) if x[0] >= sinir and x[0] > t_bas]
        if len(sonra) < EN_AZ_OKUMA or len({x[1] for x in sonra}) < 2:
            print(f"{ad} {k}: %{cur:g} · yeterli yeni okuma yok ({len(sonra)})")
            continue
        oran = statistics.median(x[2] for x in sonra)
        if abs(oran - 1) <= ESIK:
            print(f"{ad} {k}: %{cur:g} · görülen÷Booking {oran:.3f} → hedefte")
            continue
        # Yanıt denetimi: son değişiklik kanalda karşılık buldu mu?
        if len(gc) >= 2 and t_deg >= (simdi - dt.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M"):
            v_once = gc[-2][1]
            t_once = (dt.datetime.strptime(t_deg, "%Y-%m-%d %H:%M") - dt.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
            once = [x[2] for x in okuma.get(k, []) if t_once <= x[0] < t_deg]
            if len(once) >= 2:
                r0 = statistics.median(once)
                bek = r0 * (1 + cur / 100) / (1 + v_once / 100)
                if abs(bek - r0) > 0.01 and (oran - r0) / (bek - r0) < 0.5:
                    print(f"{ad} {k}: %{cur:g} · görülen÷Booking {oran:.3f} ama son değişiklik ({t_deg}, "
                          f"%{v_once:g}→%{cur:g}) kanala yansımadı (önce {r0:.3f}, beklenen {bek:.3f}) · bekliyorum")
                    continue
        hedef = ((1 + cur / 100) / oran - 1) * 100
        yeni = round(max(ALT, min(UST, max(cur - ADIM, min(cur + ADIM, hedef)))), 2)
        print(f"{ad} {k}: %{cur:g} · {len(sonra)} okuma, görülen÷Booking {oran:.3f} → %{yeni:g}"
              + (f" (tam düzeltme %{hedef:.1f}, adım sınırı)" if abs(yeni - hedef) > 0.05 else ""))
        if abs(yeni - cur) < 0.5:
            continue
        for rt in tipler:
            s = uzun.get(rt)
            if s:
                bas = dt.date.fromisoformat(str(s["FROMDATE"])[:10])
                r = {k2: s[k2] for k2 in ("ID", "HOTELID", "CHANNELID", "ROOMTYPEID", "AVAILABILITYOFFSET")}
                r.update(FROMDATE=bas.isoformat(), TODATE=SON.isoformat(), WEEKDAYPERCENT=yeni,
                         WEEKENDPERCENT=yeni, WEEKDAYAMOUNT=0, WEEKENDAMOUNT=0)
            else:
                # uzun satır, bugünden ve bu oda tipinin tek günlük satırlarından sonra başlar (çakışırsa Elektra yok sayar)
                gunler = [dt.date.fromisoformat(str(x["FROMDATE"])[:10]) for x in rows
                          if x["ROOMTYPEID"] == rt and str(x["FROMDATE"])[:10] == str(x["TODATE"])[:10]
                          and str(x["TODATE"])[:10] >= bugun.isoformat()]
                bas = max([bugun] + [g + dt.timedelta(days=1) for g in gunler])
                r = {"HOTELID": hid, "CHANNELID": kanal, "ROOMTYPEID": rt, "FROMDATE": bas.isoformat(),
                     "TODATE": SON.isoformat(), "WEEKDAYPERCENT": yeni, "WEEKENDPERCENT": yeni,
                     "WEEKDAYAMOUNT": 0, "WEEKENDAMOUNT": 0, "AVAILABILITYOFFSET": 0}
            degisen.append((r, rt, max(bas, bugun)))
    if not degisen or kuru:
        return
    for r, _, _ in degisen:
        kaydet(e, r)
    requests.get(f"https://channelmanager.elektraweb.com/booking?hotelId={hid}&action=resetcache"
                 "&resetCacheByHotel=true", headers={"Authorization": e.token}, timeout=60)
    for _, rt, bas in degisen:
        gonder(e, hid, kanal, hcm, rt, bas, SON)
    print(f"   {ad}: {len(degisen)} satır yazıldı, yeniden gönderildi")


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
    fiyat = FB.elektra_fiyatlar(e, hid, bugun, bugun + dt.timedelta(days=UFUK_GUN))
    gozlem = checks.fiyat_tum_gozlemler()
    for k in ([a.kanal] if a.kanal else KANALLAR):
        try:
            calistir(e, hid, k, bugun, simdi, fiyat, gozlem, a.kuru)
        except Exception as ex:      # biri bozulursa öbürleri yine çalışsın
            print(f"{k}: HATA {ex}")


if __name__ == "__main__":
    sys.exit(main())
