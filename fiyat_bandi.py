#!/usr/bin/env python3
"""Fiyat bandı — Elektra'daki oda temel fiyatlarını fiyat listesine göre tutar.

Kural (sahibin onayı 24.10.2026, tablo checks.FIYAT_ODALAR): o gece ESIK_ODA'dan (30) az oda
satılmışsa BAŞLANGIÇ fiyatı, 30 ve üstünde NORMAL plan. Elektra'ya giden temel fiyat EUR'dur:
€ = TL ÷ günün kuru (iki ondalık, YUKARI). Kur, Elektra'nın kendi günlük kurudur (TCMB döviz alış;
rezervasyon motoru da TL'yi bununla hesaplar). Kanallara Elektra kendisi gönderir (temel fiyat × kanal
çarpanı); fiyat değişince ayrıca "Kanalları Manuel Olarak Tekrar Güncelle" gerekmez.

Kullanım:
  python fiyat_bandi.py                          # otomatik (bulutta yarım saatte bir)
  python fiyat_bandi.py --tablo 2026-10-24 2027-03-31   # aralığın bütün gecelerini tabloya yazar
  ... --kuru                                     # yazmadan ne yapacağını göster

Otomatik mod, her gece × oda tipi için (sahibi 26.10.2026: "euro artıp azalıyor, otomatik güncellesin,
3.200'ün altına düşmesin"):
  1. TABAN: gece 30+ oda ise normal plan, değilse başlangıç fiyatı. Elektra fiyatı günün kuruyla
     tabanın altına düştüyse (kur düştü ya da gece 30 odayı buldu) hemen tabana çıkarır.
  2. KUR: fiyat tablodaki bir değere yakınsa (±%6; başlangıç ya da normal plan) ve euro yükseldiği için
     misafir KUR_PAYI TL'den fazla öderse, € o tablo değerine indirilir (TL yine tablonun altına inmez).
     Normal plana çıkmış gece iptallerle 30'un altına inse de normal planda kalır (bant düşmez).
  3. Tablodan %6'dan fazla uzak fiyat (elle girilmiş özel fiyat: bayram, etkinlik) olduğu gibi kalır,
     yalnız tabanın altındaysa 1. kural uygulanır.
Elektra'da fiyatı hiç girilmemiş (0) geceye dokunmaz: o tarih satışa kapalıdır (24.10.2026'da
31.03.2027 sonrası böyle). Günün kuru okunamazsa hiçbir şey yazmaz.

Elektra çağrısı, ekrandaki "Fiyat ve Doluluk → ⚡ → Toplu Güncelleme" formunun yaptığıdır:
  Execute/SP_AVAILABILITY_UPDATE {FROMDATE, TODATE, ROOMTYPEID, DBLPRICE (= Temel Fiyat), gün bayrakları}
Diğer alanlar (kontenjan, stop-sale, kısıtlama) null gider ve değişmez (24.10.2026 canlı denendi:
yalnız RATE değişti). ROOMTYPEID boş giderse işlem BÜTÜN oda tiplerine uygulanır; burada zorunlu.
Form bir çağrıda en fazla 90 günlük aralık kabul ediyor, burada da parçalanır.
"""
import argparse
import datetime as dt
import math
import sys
from zoneinfo import ZoneInfo

import checks
import elektra_api as E

KUR = None   # 1 € kaç TL — main() günün Elektra kurunu yazar (elektra_kur). 26.10.2026: 55,4997.
KUR_PAYI = 5       # TL — euro yükselince misafir tablodan bu kadar fazla öderse € indirilir (sahibi: tam 3.200)
PENCERE = 0.06     # tablo değerine bu kadar yakın fiyat "tablodaki fiyat" sayılır; uzağı elle girilmiş
ODA_TIPLERI = {  # FIYAT_ODALAR anahtarı → Elektra HOTEL_ROOMTYPE (ID, ad)
    "eko": ((442638, "Ekonomik Oda - Balkonlu"),),
    "stu": ((442639, "Studio Oda - Mutfaklı"),),
    "sup": ((455224, "Superior Oda"), (455223, "Superior Oda - Mutfaklı")),
    "dlx": ((442634, "Deluxe Oda - Mutfaklı"), (442637, "Deluxe Oda - Balkonlu")),
    "sui": ((442636, "1+1 Suit Oda - Mutfaklı"),),
}
UFUK = 180         # otomatik mod bugünden bu kadar gece ileriye bakar
PAY = 0.005        # € — Elektra fiyatı float saklıyor (57.66 → 57.65999); iki ondalık için yeterince dar
GUNLER = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
BAS_GUNLER = ((6, 0, 1, 2, 3), (4, 5))   # başlangıç fiyatı grupları (Python weekday)
ODA = {rt: (oda, ad) for oda in checks.FIYAT_ODALAR for rt, ad in ODA_TIPLERI[oda[0]]}
GUN = dt.timedelta(days=1)


def euro(tl):
    """TL → Elektra temel fiyatı (€, iki ondalık, YUKARI yuvarlanır ki motor TL'nin altına düşmesin:
    3.200 TL → 57,66 € → 3.200,13 TL). Sahibi 26.10: "3.180 değil 3.200 olsun"."""
    return math.ceil(tl / KUR * 100 - 1e-9) / 100


def elektra_kur(e, hid, gun):
    """Elektra'nın o günkü EUR→TL kuru: Günlük Kur ekranının fonksiyonu, BUYRATE = TCMB döviz alış.
    Rezervasyon motoru TL'yi bununla hesaplıyor (26.10.2026: 57,3 € → 3.180,13 TL = 55,4997)."""
    rows = E.Elektra.function(e, "FN_HOTEL_EXCHANGERATES_WITHCOMMISSION_BETWEENDATES",
                              {"DATE": (gun - dt.timedelta(days=7)).isoformat(), "DATE2": gun.isoformat(),
                               "CURRIDS": [44], "HOTELID": int(hid)})
    kur = [(checks.pdate(r.get("DATE")), float(r.get("BUYRATE") or 0)) for r in rows
           if r.get("BASECURRENCYID") == 44 and r.get("TARGETCURRENCYID") == 142]
    kur = [(d, k) for d, k in kur if d and d <= gun and 30 < k < 150]
    if not kur:
        raise SystemExit("günün euro kuru Elektra'dan okunamadı — hiçbir şey yazılmadı")
    return max(kur)[1]


def elektra_fiyatlar(e, hid, frm, to):
    """{(gece, oda tipi ID): Temel Fiyat €} — Fiyat ve Doluluk ekranının okuduğu görünüm."""
    w = [True, {"Column": "HOTELID", "Operator": "=", "Value": hid},
         {"Column": "DATE", "Operator": ">=", "Value": frm.isoformat()},
         {"Column": "DATE", "Operator": "<=", "Value": to.isoformat()},
         {"Column": "ROOMTYPECODE", "Operator": "IS NOT NULL", "Value": ""}]
    d = e._post("Select/VW_EASYPMS_AVAILABILITY",
                {"Object": "VW_EASYPMS_AVAILABILITY", "Select": ["DATE", "HOTELROOMTYPEID", "RATE"],
                 "Where": w, "Paging": {"Current": 1, "ItemsPerPage": 99999}}, action_name="Select")
    return {(checks.pdate(r["DATE"]), int(r["HOTELROOMTYPEID"])): float(r["RATE"] or 0)
            for r in (d.get("ResultSets") or [[]])[0]}


def yaz(e, hid, rt, frm, to, eur, gunler=None, kuru=False):
    """Bir oda tipinin [frm, to] gecelerine (gunler verilirse yalnız o hafta günlerine) temel fiyat."""
    if rt not in ODA:
        raise ValueError(f"bilinmeyen oda tipi {rt!r} — boş giderse bütün oda tiplerine uygulanır")
    if not 20 <= eur <= 250:
        raise ValueError(f"şüpheli fiyat: {eur} €")
    if not 0 <= (to - frm).days <= 90:
        raise ValueError(f"aralık 0–90 gün olmalı: {frm} – {to}")
    if kuru:
        return
    p = {"FROMDATE": frm.isoformat(), "TODATE": to.isoformat(), "ROOMTYPEID": rt, "DBLPRICE": eur,
         "RATE_SNG": None, "RATE_DBL": None, "RATE_TRP": None, "RATE_QUAD": None, "RATE_EXBED": None,
         "PRICETYPE": None, "MARKUPTYPE": None, "MARKUP": None, "AVAILABLECOUNT": None,
         "EXTRAROOM": None, "MINLOS": None, "MAXLOS": None, "STOPSELL": None, "REMOVESTOPSELL": None,
         "RATECODEID": None, "HOTELID": int(hid)}
    for i, g in enumerate(GUNLER):
        p[g] = gunler is None or i in gunler
    r = e._post("Execute/SP_AVAILABILITY_UPDATE",
                {"Object": "SP_AVAILABILITY_UPDATE", "BaseObject": "HOTEL_ROOMTYPE_AVAILABILITY",
                 "Parameters": p}, action_name="Execute")
    s = ((r or [[{}]])[0] or [{}])[0]
    if not s.get("SUCCESS"):
        raise E.ElektraError(f"SP_AVAILABILITY_UPDATE {ODA[rt][1]} {frm}–{to}: "
                             f"{s.get('MESSAGE') or s.get('MSGCODE')}")


def hedefler(dol, frm, to):
    """{(gece, oda tipi ID): hedef €} tablo ve doluluğa göre."""
    out, d = {}, frm
    while d <= to:
        for rt, (oda, _) in ODA.items():
            out[(d, rt)] = euro(checks.gece_hedef(oda, d, dol.get(d, 0)))
        d += GUN
    return out


def kontrol(e, hid, frm, to, bekle):
    """Elektra'yı yeniden oku; beklenenden farklı gece/oda tipi listesi."""
    simdi = elektra_fiyatlar(e, hid, frm, to)
    return [(d, rt, simdi.get((d, rt)), v) for (d, rt), v in sorted(bekle.items())
            if simdi.get((d, rt)) is None or abs(simdi[(d, rt)] - v) > PAY]


def tablo(e, env, hid, frm, to, kuru):
    """Aralığın bütün gecelerini tabloya yazar: önce başlangıç fiyatı (90 günlük parçalar, gün grubu
    başına bir çağrı), sonra 30+ oda geceleri tek tek normal plana."""
    dol = checks.gece_doluluk(env, frm, to)
    n, parca = 0, frm
    while parca <= to:
        son = min(to, parca + dt.timedelta(days=90))
        for rt, (oda, ad) in ODA.items():
            for g, gunler in enumerate(BAS_GUNLER):
                yaz(e, hid, rt, parca, son, euro(oda[4][g]), gunler, kuru)
                n += 1
        print(f"başlangıç fiyatı: {parca} – {son}")
        parca = son + GUN
    for d in sorted(x for x in dol if frm <= x <= to and dol[x] >= checks.ESIK_ODA):
        for rt, (oda, ad) in ODA.items():
            yaz(e, hid, rt, d, d, euro(checks.gece_hedef(oda, d, dol[d])), None, kuru)
            n += 1
        print(f"normal plan: {d}")
    print(f"{n} çağrı" + (" (kuru)" if kuru else ""))
    return hedefler(dol, frm, to)


def otomatik(e, env, hid, bugun, kuru):
    son = bugun + dt.timedelta(days=UFUK)
    dol = checks.gece_doluluk(env, bugun, son)
    simdi = elektra_fiyatlar(e, hid, bugun, son)
    bekle, neden = {}, {}
    for (d, rt), p in simdi.items():
        if rt not in ODA or p <= 0:
            continue    # fiyatı girilmemiş gece satışa kapalıdır; açma
        oda, ad = ODA[rt]
        bas, nor = euro(oda[4][checks.bas_grubu(d)]), euro(oda[3][checks.gun_grubu(d)])
        otuz = dol.get(d, 0) >= checks.ESIK_ODA
        taban = nor if otuz else bas
        if p < taban - PAY:
            bekle[(d, rt)], neden[(d, rt)] = taban, ("30+ oda" if otuz and p < bas + PAY * 2 else "taban")
            continue
        aday = [c for c in (bas, nor) if c >= taban - PAY and abs(p - c) <= PENCERE * c]
        if aday:
            c = min(aday, key=lambda c: abs(p - c))
            if (p - c) * KUR > KUR_PAYI:
                bekle[(d, rt)], neden[(d, rt)] = c, "kur"
    if not bekle:
        print(f"değişiklik yok (kur {KUR})")
        return bekle
    sayi = {}
    for k, v in neden.items():
        sayi.setdefault((ODA[k[1]][1], v), []).append(k[0])
    for (ad, v), gunler in sorted(sayi.items()):
        aciklama = {"30+ oda": "30+ oda · normal plan", "taban": "kur düştü · tabana çıkarıldı",
                    "kur": "euro yükseldi · € indirildi"}[v]
        print(f"{ad}: {len(gunler)} gece ({min(gunler)} – {max(gunler)}) · {aciklama}")
    yaz_toplu(e, hid, bekle, simdi, kuru)
    return bekle


def yaz_toplu(e, hid, bekle, simdi, kuru):
    """Başlangıç fiyatına giden geceleri gün grubu bayraklarıyla toplu yazar: (oda tipi, grup) başına
    ardışık takvim parçaları, her biri ≤ 91 gece. Parça, o gruptaki her geceyi ancak güvenliyse kapsar:
    yazılacak gece ya da fiyatı zaten aynı olan gece. Arada özel/normal plan fiyatlı gece varsa parça
    orada bölünür, ona dokunulmaz. Normal plana giden geceler tek tek yazılır."""
    n = 0
    for rt, (oda, ad) in ODA.items():
        tek = []
        for g, gunler in enumerate(BAS_GUNLER):
            v = euro(oda[4][g])
            hedef = {d for (d, r), x in bekle.items() if r == rt and d.weekday() in gunler and abs(x - v) <= PAY}
            if not hedef:
                continue
            guvenli = hedef | {d for (d, r), x in simdi.items()
                               if r == rt and d.weekday() in gunler and abs(x - v) <= PAY}
            d, son = min(hedef), max(hedef)
            parca = None
            while d <= son + GUN:
                grupta = d.weekday() in gunler
                if d > son or (grupta and d not in guvenli) or (parca and (d - parca[0]).days >= 91):
                    if parca and any(parca[0] <= x <= parca[1] for x in hedef):
                        yaz(e, hid, rt, parca[0], parca[1], v, gunler, kuru)
                        n += 1
                    parca = None
                    if d > son:
                        break
                    if grupta and d not in guvenli:
                        d += GUN
                        continue
                if grupta:
                    parca = (parca[0] if parca else d, d)
                d += GUN
        tek = sorted(d for (d, r), x in bekle.items()
                     if r == rt and abs(x - euro(oda[4][checks.bas_grubu(d)])) > PAY)
        for d in tek:
            yaz(e, hid, rt, d, d, bekle[(d, rt)], None, kuru)
            n += 1
    print(f"{n} çağrı" + (" (kuru)" if kuru else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tablo", nargs=2, metavar=("BAŞ", "SON"), help="aralığı tabloya yaz (YYYY-AA-GG)")
    ap.add_argument("--kuru", action="store_true", help="Elektra'ya yazma, yalnız göster")
    a = ap.parse_args()
    global KUR
    e, env = E.connect()
    hid = int(env.get("ELEKTRA_HOTELID") or E.DEFAULT_TENANT)
    bugun = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date()
    KUR = elektra_kur(e, hid, bugun)
    print(f"günün euro kuru (Elektra): {KUR}")
    if a.tablo:
        frm, to = (dt.date.fromisoformat(x) for x in a.tablo)
        if frm < bugun:
            raise SystemExit("geçmiş gece yazılamaz")
        bekle = tablo(e, env, hid, frm, to, a.kuru)
    else:
        bekle = otomatik(e, env, hid, bugun, a.kuru)
    if a.kuru or not bekle:
        return
    hata = kontrol(e, hid, min(d for d, _ in bekle), max(d for d, _ in bekle), bekle)
    for d, rt, var, v in hata:
        print(f"UYUŞMUYOR {d} {ODA[rt][1]}: Elektra {var} €, beklenen {v} €")
    if hata:
        sys.exit(1)
    print(f"kontrol tamam: {len(bekle)} gece × oda tipi tabloda")


if __name__ == "__main__":
    main()
