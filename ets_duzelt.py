#!/usr/bin/env python3
"""Etstur düzeltmesi (2. sürüm, 13.11.2026) — Etstur'da misafirin gördüğü fiyat hedefle aynı kalsın.

Sahibi: "bir daha bu olursa ETS çarpanını düzenle" (10.11), "her güncellemede kontrol et" (13.11).

Neden: Etstur kendi tarafında oda tipine göre ek indirim açıp kapatıyor. 03.11'den beri Deluxe/Suit'te
Elektra'da −%8,08 satırı vardı, Stüdyo/Superior'da yoktu (Etstur onlara kendi %8'ini uyguluyordu).
12.11'den beri Etstur o %8'i uygulamıyor: Stüdyo/Superior her gece +%8,8 pahalı göründü.

Kaldıraç: Elektra "Kanal Fiyat Çarpanları" (HOTEL_CHANNELMANAGER_PRICING), ETSTUR için ODA TİPİ BAŞINA
TEK uzun satır (bugün → 31.03.2027). Uzun satırın içine tek gecelik satır eklenemiyor: Elektra "başarılı"
diyor ama kaydetmiyor (13.11 denendi). 1. sürümün tek gecelik satırları bu yüzden yalnız uzun satırı
olmayan odalarda işliyordu ve okuma gecikmesiyle saatte bir 0 ↔ %8,8 arasında gidip geldi (12.11 GetLog).

Çalışma (fiyat-bandi.yml, yarım saatte bir), oda türü başına (Stüdyo, Superior, Deluxe, Suit):
  1. Son TAZE_SAAT içindeki Etstur okumaları (trivago ya da etstur.com) — yalnız bugün+YAKIN_GUN ve
     sonrası (yakın gecede Etstur oda doldukça başka oda gösteriyor; 13.11: Stüdyo +%20, Deluxe −%12)
     ve yalnız o odanın satırı EN SON değiştikten (GetLog) BEKLE_DK sonra alınmış okumalar.
  2. Oran = görülen ÷ hedef (panel hedefi: liste + doluluk). En az EN_AZ_OKUMA okuma, ortanca.
  3. |oran − 1| > ESIK ise yeni çarpan = (1 + eski%) ÷ oran − 1, [ALT, UST] içinde. Satır güncellenir
     (yoksa eklenir), kanal önbelleği temizlenir (resetcache) ve o oda Etstur'a yeniden gönderilir.
Hiçbir satır silinmez. --kuru: yazmadan göster.
"""
import argparse
import datetime as dt
import statistics
import sys
import time

import requests

import checks
import elektra_api as E
import fiyat_bandi as FB

KANAL, HCM = 147, 50099          # ETSTUR: CHANNELMANAGERID, HOTELCHANNELMANAGERID
RATETYPE = 44257
SON = dt.date(2027, 3, 31)       # fiyatların bittiği gün
ESIK = 0.03                      # ±%3'ten küçük sapma "hedefte"
ALT, UST = -25.0, 12.0           # % — satırın gidebileceği sınırlar
TAZE_SAAT = 6
YAKIN_GUN = 3                    # bugün, yarın, öbür gün sayılmaz
UFUK_GUN = 60
EN_AZ_OKUMA = 2
BEKLE_DK = 20                    # satır değiştikten sonra Etstur'un yeni fiyatı alması için pay
ODALAR = ("stu", "sup", "dlx", "sui")


def satirlar(e, hid, bugun):
    """{oda tipi ID: bugünü kapsayan uzun satır}."""
    r = e._post("Select/HOTEL_CHANNELMANAGER_PRICING",
                {"Object": "HOTEL_CHANNELMANAGER_PRICING",
                 "Where": [{"Column": "HOTELID", "Operator": "=", "Value": hid},
                           {"Column": "CHANNELID", "Operator": "=", "Value": KANAL}], "Select": [],
                 # Sayfalama verilmezse Elektra yalnız ilk 10 satırı döndürür. 1. sürüm bu yüzden kendi
                 # satırlarını göremeyip aynı geceye 12 kez satır ekledi (12–13.11.2026).
                 "Paging": {"ItemsPerPage": 1000, "Current": 1}},
                action_name="Select")
    out = {}
    for s in ((r or {}).get("ResultSets") or [[]])[0]:
        a, b = str(s["FROMDATE"])[:10], str(s["TODATE"])[:10]
        if a <= bugun.isoformat() <= b and b > a:
            out[s["ROOMTYPEID"]] = s
    return out


def son_degisim(e, hid, satir):
    """Satırın en son değiştiği an, İstanbul saatiyle 'YYYY-AA-GG SS:DD' (okuma zamanıyla kıyas için)."""
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
        return "9999"     # kayıt okunamadı → hiçbir okuma sayılmaz (güvenli taraf)
    ts = [x.get("LOGTIMEUTC", "") for x in ((r or {}).get("ResultSets") or [[]])[0]]
    if not ts:
        return ""
    t = dt.datetime.strptime(max(ts)[:16], "%Y-%m-%d %H:%M") + dt.timedelta(hours=3)   # TR = UTC+3
    return t.strftime("%Y-%m-%d %H:%M")


def yaz(e, hid, rt, yuzde, eski, bugun):
    row = {"HOTELID": hid, "CHANNELID": KANAL, "ROOMTYPEID": rt,
           "FROMDATE": (str(eski["FROMDATE"])[:10] if eski else bugun.isoformat()), "TODATE": SON.isoformat(),
           "WEEKDAYPERCENT": yuzde, "WEEKDAYAMOUNT": 0, "WEEKENDPERCENT": yuzde, "WEEKENDAMOUNT": 0,
           "AVAILABILITYOFFSET": 0}
    if eski:
        r = e._post("Update/HOTEL_CHANNELMANAGER_PRICING",
                    {"Object": "HOTEL_CHANNELMANAGER_PRICING", "Row": {**row, "ID": eski["ID"]}},
                    action_name="Update")
    else:
        r = e._post("Insert/HOTEL_CHANNELMANAGER_PRICING",
                    {"Object": "HOTEL_CHANNELMANAGER_PRICING", "Row": row}, action_name="Insert")
    if not (r or {}).get("Success"):
        raise E.ElektraError(f"HOTEL_CHANNELMANAGER_PRICING {rt}: {r}")
    # Kanal yöneticisi bu satırları önbellekte tutar; ekran kaydedince bunu çağırır (10.11.2026 ağ kaydı).
    # Çağrılmazsa yeniden gönderim eski değerle gider. Önbellek zaten boşsa 500 "No keys" döner.
    requests.get(f"https://channelmanager.elektraweb.com/booking?hotelId={hid}&action=resetcache"
                 "&resetCacheByHotel=true", headers={"Authorization": e.token}, timeout=60)
    bas = bugun
    while bas <= SON:      # yeniden gönderim parça parça (≤90 gün)
        son = min(SON, bas + dt.timedelta(days=89))
        p = {"FROM": bas.isoformat(), "TO": son.isoformat(), "ROOMTYPEID": rt, "RATETYPEID": RATETYPE,
             "CHANNELMANAGERID": KANAL, "HOTELCHANNELMANAGERID": HCM, "WHATTOREFRESH": 1, "HOTELID": hid}
        for o in ("SP_RESEND_HOTEL_ROOMTYPE_AVAILABILITY", "SP_RESEND_CHANGE_COMMAND"):
            e._post("Execute/" + o, {"Object": o, "Parameters": p}, action_name="Execute")
        bas = son + dt.timedelta(days=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kuru", action="store_true", help="yazmadan ne yapacağını göster")
    kuru = ap.parse_args().kuru
    e, env = E.connect()
    hid = int(env.get("ELEKTRA_HOTELID", E.DEFAULT_TENANT))
    simdi = dt.datetime.now(FB.ZoneInfo("Europe/Istanbul")).replace(tzinfo=None)
    bugun = simdi.date()
    ilk, son = bugun + dt.timedelta(days=YAKIN_GUN), bugun + dt.timedelta(days=UFUK_GUN)
    dol = checks.gece_doluluk(env, ilk, son)
    oda = {r[0]: r for r in checks.FIYAT_ODALAR}
    sinir = (simdi - dt.timedelta(hours=TAZE_SAAT)).strftime("%Y-%m-%d %H:%M")
    okuma = {}
    for g in checks.fiyat_tum_gozlemler():
        d, k, f, z = checks.pdate(g.get("tarih")), g.get("oda"), g.get("fiyat"), g.get("zaman", "")
        if g.get("kanal") == "etstur" and k in ODALAR and f and d and ilk <= d <= son and z >= sinir:
            okuma.setdefault(k, {})[(d, z)] = f / checks.gece_hedef(oda[k], d, dol.get(d, 0), bugun)
    mevcut = satirlar(e, hid, bugun)
    for k in ODALAR:
        tipler = [rt for rt, _ in FB.ODA_TIPLERI[k]]
        eski = [mevcut.get(rt) for rt in tipler]
        c = float(eski[0]["WEEKDAYPERCENT"]) if eski[0] else 0.0
        degisim = max(son_degisim(e, hid, s) for s in eski) if any(eski) else ""
        if degisim:
            degisim = (dt.datetime.strptime(degisim, "%Y-%m-%d %H:%M")
                       + dt.timedelta(minutes=BEKLE_DK)).strftime("%Y-%m-%d %H:%M")
        oranlar = [o for (d, z), o in okuma.get(k, {}).items() if z > degisim]
        if len(oranlar) < EN_AZ_OKUMA:
            print(f"{k}: çarpan %{c:g} · yeterli yeni okuma yok ({len(oranlar)}; son değişim {degisim or '-'})")
            continue
        oran = statistics.median(oranlar)
        if abs(oran - 1) <= ESIK:
            print(f"{k}: çarpan %{c:g} · {len(oranlar)} okuma, görülen÷hedef {oran:.3f} → hedefte")
            continue
        yeni = round(max(ALT, min(UST, ((1 + c / 100) / oran - 1) * 100)), 2)
        print(f"{k}: çarpan %{c:g} · {len(oranlar)} okuma, görülen÷hedef {oran:.3f} → %{yeni:g}")
        if kuru or abs(yeni - c) < 0.5:
            continue
        for rt, s in zip(tipler, eski):
            yaz(e, hid, rt, yeni, s, bugun)
        print("   yazıldı, Etstur'a yeniden gönderildi")


if __name__ == "__main__":
    sys.exit(main())
