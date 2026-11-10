#!/usr/bin/env python3
"""Etstur düzeltmesi — Etstur yakın gecelerde (bugün, yarın, öbür gün) bazı odaları kendi tarafında
~%8–9 daha ucuz gösteriyor (10.11.2026 teşhis: Elektra 10, 11 ve 24 Kasım için aynı 72,84 € gönderdi,
etstur.com 10–11'de 2.991, 24'te 3.264 gösterdi). Etspartners'ta bunu kapatan ayar yok (otelin tek
promosyonu %20). Sahibi: "bir daha bu olursa ETS çarpanını düzenle" (10.11.2026).

Çalışma (fiyat-bandi.yml, yarım saatte bir):
  1. fiyat_topla.py'nin etstur.com okumalarından (site_data/fiyat/otomatik.json, son 3 saat) her
     gece × oda için Etstur'un %20 sonrası "liste" fiyatını (acik) alır.
  2. Beklenen = Elektra temel € × günün kuru × ETSTUR çarpanı × (1 + bu gecenin düzeltmesi) × 0,8.
     Oran = görülen ÷ beklenen; bu, Etstur'un kendi kesintisidir (bizim düzeltmemizden bağımsız).
  3. Oran ESIK'in altındaysa o gece × oda için Elektra "Kanal Fiyat Çarpanları"na (HOTEL_CHANNELMANAGER_
     PRICING) tek günlük + % satır yazar (yoksa ekler, varsa günceller) ve Etstur'a o geceyi yeniden
     gönderir. Etstur kesmeyi bırakırsa (oran 1+düzeltmeye yaklaşır) satırı 0'a çeker. Satır silinmez;
     geçmiş gece zararsız. Satırdan sonra kanal önbelleği temizlenir (resetcache), yoksa gönderim eski kalır.
Yalnız uzun süreli oda satırı olmayan odalar (Stüdyo, Superior): Deluxe/Suit'te 03.11'den beri −%8,08
satırı var, üst üste binme denenmedi. Düzeltme en fazla UST_SINIR; Etstur fiyatı bizimkine göre
eşitliyorsa sonsuz yükselmesin.

Kullanım: python ets_duzelt.py [--kuru]
"""
import argparse
import datetime as dt
import sys

import requests

import checks
import elektra_api as E
import fiyat_bandi as FB

KANAL, HCM, AD = 147, 50099, "ETSTUR"      # Elektra CHANNELMANAGERID, HOTELCHANNELMANAGERID, Online Kanallar adı
INDIRIM = 0.20          # Etspartners'taki otelin %20 "Özel İndirim"i (PRM-781768)
ESIK = 0.97             # görülen ÷ beklenen bunun altındaysa Etstur kendi kesmiş
UST_SINIR = 12.0        # % — en fazla bu kadar düzeltme
GUN_SAYISI = 3          # bugün + 2 gece
TAZE_SAAT = 3           # okuma en fazla bu kadar eski olsun
ODALAR = ("stu", "sup")
RATETYPE = 44257


def etstur_okumalari(bugun, simdi):
    """{(gece, oda): (acik, zaman)} — etstur.com okumaları, gece başına en sonuncusu."""
    sinir = (simdi - dt.timedelta(hours=TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    out = {}
    for g in checks.fiyat_tum_gozlemler():
        if g.get("kanal") != "etstur" or not str(g.get("kaynak", "")).startswith("Etstur"):
            continue
        d, k, a, z = checks.pdate(g.get("tarih")), g.get("oda"), g.get("acik"), g.get("zaman", "")
        if not d or k not in ODALAR or not a or z < sinir or not (bugun <= d < bugun + dt.timedelta(days=GUN_SAYISI)):
            continue
        if (d, k) not in out or z > out[(d, k)][1]:
            out[(d, k)] = (a, z)
    return out


def satirlar(e, hid):
    """Bu programın tek günlük satırları: {(gece, oda tipi ID): satır}."""
    r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                 "Where": [{"Column": "HOTELID", "Operator": "=", "Value": hid},
                           {"Column": "CHANNELID", "Operator": "=", "Value": KANAL}], "Select": []},
                action_name="Select")
    out = {}
    for s in (r or {}).get("ResultSets", [[]])[0]:
        a, b = str(s["FROMDATE"])[:10], str(s["TODATE"])[:10]
        if a == b:
            out[(dt.date.fromisoformat(a), s["ROOMTYPEID"])] = s
    return out


def yaz(e, hid, d, rt, yuzde, eski):
    row = {"HOTELID": hid, "CHANNELID": KANAL, "ROOMTYPEID": rt, "FROMDATE": d.isoformat(),
           "TODATE": d.isoformat(), "WEEKDAYPERCENT": yuzde, "WEEKDAYAMOUNT": 0,
           "WEEKENDPERCENT": yuzde, "WEEKENDAMOUNT": 0, "AVAILABILITYOFFSET": 0}
    if eski:
        r = e._post("Update/HOTEL_CHANNELMANAGER_PRICING",
                    {"Object": "HOTEL_CHANNELMANAGER_PRICING", "Row": {**row, "ID": eski["ID"]}},
                    action_name="Update")
    else:
        r = e._post("Insert/HOTEL_CHANNELMANAGER_PRICING",
                    {"Object": "HOTEL_CHANNELMANAGER_PRICING", "Row": row}, action_name="Insert")
    if not (r or {}).get("Success"):
        raise E.ElektraError(f"HOTEL_CHANNELMANAGER_PRICING {d} {rt}: {r}")
    # Kanal yöneticisi bu satırları önbellekte tutar; ekran kaydedince bunu çağırır (10.11.2026 ağ
    # kaydı). Çağrılmazsa yeniden gönderim eski değerle gider. Önbellek zaten boşsa 500 "No keys" döner.
    requests.get(f"https://channelmanager.elektraweb.com/booking?hotelId={hid}&action=resetcache"
                 "&resetCacheByHotel=true", headers={"Authorization": e.token}, timeout=60)
    p = {"FROM": d.isoformat(), "TO": d.isoformat(), "ROOMTYPEID": rt, "RATETYPEID": RATETYPE,
         "CHANNELMANAGERID": KANAL, "HOTELCHANNELMANAGERID": HCM, "WHATTOREFRESH": 1, "HOTELID": hid}
    for o in ("SP_RESEND_HOTEL_ROOMTYPE_AVAILABILITY", "SP_RESEND_CHANGE_COMMAND"):
        e._post("Execute/" + o, {"Object": o, "Parameters": p}, action_name="Execute")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true", help="yazmadan ne yapacağını göster")
    kuru = ap.parse_args().kuru
    e, env = E.connect()
    hid = int(env.get("ELEKTRA_HOTELID", E.DEFAULT_TENANT))
    simdi = dt.datetime.now(FB.ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
    bugun = simdi.date()
    FB.KUR = FB.elektra_kur(e, hid, bugun)
    if not FB.KUR:
        print("kur okunamadı; dokunmadım")
        return
    carpan = next((float(c["factor"] or 1) for c in E.fetch_channel_factors(env)
                   if c["name"] == AD and c["active"]), None)
    if not carpan:
        print("ETSTUR çarpanı okunamadı; dokunmadım")
        return
    okuma = etstur_okumalari(bugun, simdi)
    if not okuma:
        print("yakın gece için taze etstur.com okuması yok")
        return
    fiyat = FB.elektra_fiyatlar(e, hid, bugun, bugun + dt.timedelta(days=GUN_SAYISI - 1))
    mevcut = satirlar(e, hid)
    for (d, k), (acik, z) in sorted(okuma.items()):
        for rt, _ in FB.ODA_TIPLERI[k]:
            p = fiyat.get((d, rt))
            if not p:
                continue
            eski = mevcut.get((d, rt))
            c = float(eski["WEEKDAYPERCENT"]) if eski else 0.0
            beklenen = p * FB.KUR * carpan * (1 - INDIRIM)     # düzeltmesiz
            oran = acik / beklenen
            # Okuma saatte bir; düzeltmeden önceki okuma hâlâ "en son" olabilir. Bu yüzden:
            #   düzeltme yok, oran düşük        → Etstur kesiyor: düzelt
            #   düzeltme var, oran ≈ 1          → düzeltme işliyor (kesme sürüyor): bırak
            #   düzeltme var, oran düşük        → okuma eski: bekle
            #   düzeltme var, oran 1+c'ye yakın → Etstur kesmeyi bırakmış: düzeltmeyi 0'a çek
            if not c and oran < ESIK:
                yeni = min(UST_SINIR, round((1 / oran - 1) * 100, 2))
            elif c and oran > 1 + c / 200:
                yeni = 0.0
            else:
                yeni = c
            print(f"{d} {k} {rt}: görülen {acik} ({z}) beklenen {beklenen:.0f} oran {oran:.3f} "
                  f"düzeltme %{c:g} → %{yeni:g}")
            if abs(yeni - c) >= 0.5 and not kuru:
                yaz(e, hid, d, rt, yeni, eski)
                print("   yazıldı, Etstur'a yeniden gönderildi")


if __name__ == "__main__":
    sys.exit(main())
