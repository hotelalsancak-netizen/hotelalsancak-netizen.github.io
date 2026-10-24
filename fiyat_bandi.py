#!/usr/bin/env python3
"""Fiyat bandı — Elektra'daki oda temel fiyatlarını fiyat listesine göre tutar.

Kural (sahibin onayı 24.10.2026, tablo checks.FIYAT_ODALAR): o gece ESIK_ODA'dan (30) az oda
satılmışsa BAŞLANGIÇ fiyatı, 30 ve üstünde NORMAL plan. Elektra'ya giden temel fiyat EUR'dur:
€ = TL ÷ KUR (bir ondalık). Kanallara Elektra kendisi gönderir (temel fiyat × kanal çarpanı);
fiyat değişince ayrıca "Kanalları Manuel Olarak Tekrar Güncelle" gerekmez.

Kullanım:
  python fiyat_bandi.py                          # otomatik (bulutta yarım saatte bir): yalnız YÜKSELTİR
  python fiyat_bandi.py --tablo 2026-10-24 2027-03-31   # aralığın bütün gecelerini tabloya yazar
  ... --kuru                                     # yazmadan ne yapacağını göster

Otomatik mod hiçbir geceyi DÜŞÜRMEZ, elle yükseltilmiş gece (bayram, etkinlik) korunur:
  - gece 30+ oda ve Elektra fiyatı normal planın altında → normal plana çıkar
  - gece 30'un altında ama Elektra fiyatı başlangıç fiyatının da altında (hatalı giriş) → başlangıca
İptallerle gece 30'un altına inerse fiyat kendiliğinden inmez (elle ya da --tablo ile).
Elektra'da fiyatı hiç girilmemiş (0) geceye dokunmaz: o tarih satışa kapalıdır (24.10.2026'da
31.03.2027 sonrası böyle).

Elektra çağrısı, ekrandaki "Fiyat ve Doluluk → ⚡ → Toplu Güncelleme" formunun yaptığıdır:
  Execute/SP_AVAILABILITY_UPDATE {FROMDATE, TODATE, ROOMTYPEID, DBLPRICE (= Temel Fiyat), gün bayrakları}
Diğer alanlar (kontenjan, stop-sale, kısıtlama) null gider ve değişmez (24.10.2026 canlı denendi:
yalnız RATE değişti). ROOMTYPEID boş giderse işlem BÜTÜN oda tiplerine uygulanır; burada zorunlu.
Form bir çağrıda en fazla 90 günlük aralık kabul ediyor, burada da parçalanır.
"""
import argparse
import datetime as dt
import sys
from zoneinfo import ZoneInfo

import checks
import elektra_api as E

KUR = 55.8   # 1 € kaç TL (24.10.2026). Kur belirgin değişince güncellenir, sonra --tablo çalıştırılır.
ODA_TIPLERI = {  # FIYAT_ODALAR anahtarı → Elektra HOTEL_ROOMTYPE (ID, ad)
    "eko": ((442638, "Ekonomik Oda - Balkonlu"),),
    "stu": ((442639, "Studio Oda - Mutfaklı"),),
    "sup": ((455224, "Superior Oda"), (455223, "Superior Oda - Mutfaklı")),
    "dlx": ((442634, "Deluxe Oda - Mutfaklı"), (442637, "Deluxe Oda - Balkonlu")),
    "sui": ((442636, "1+1 Suit Oda - Mutfaklı"),),
}
UFUK = 180         # otomatik mod bugünden bu kadar gece ileriye bakar
PAY = 0.05         # € — Elektra fiyatı float saklıyor (57.3 → 57.29999)
GUNLER = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
BAS_GUNLER = ((6, 0, 1, 2, 3), (4, 5))   # başlangıç fiyatı grupları (Python weekday)
ODA = {rt: (oda, ad) for oda in checks.FIYAT_ODALAR for rt, ad in ODA_TIPLERI[oda[0]]}
GUN = dt.timedelta(days=1)


def euro(tl):
    return round(tl / KUR, 1)


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
    bekle = {}
    for (d, rt), eur in sorted(simdi.items()):
        if rt not in ODA or eur <= 0:
            continue    # fiyatı girilmemiş gece satışa kapalıdır (ör. sezonu açılmamış tarih); açma
        oda, ad = ODA[rt]
        hedef = euro(checks.gece_hedef(oda, d, dol.get(d, 0)))
        if eur < hedef - PAY:
            neden = "30+ oda · normal plan" if dol.get(d, 0) >= checks.ESIK_ODA else "başlangıç fiyatının altındaydı"
            print(f"{d} {ad}: {eur:.1f} → {hedef:.1f} € ({neden})")
            yaz(e, hid, rt, d, d, hedef, None, kuru)
            bekle[(d, rt)] = hedef
    if not bekle:
        print("değişiklik yok")
    return bekle


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tablo", nargs=2, metavar=("BAŞ", "SON"), help="aralığı tabloya yaz (YYYY-AA-GG)")
    ap.add_argument("--kuru", action="store_true", help="Elektra'ya yazma, yalnız göster")
    a = ap.parse_args()
    e, env = E.connect()
    hid = int(env.get("ELEKTRA_HOTELID") or E.DEFAULT_TENANT)
    bugun = dt.datetime.now(ZoneInfo("Europe/Istanbul")).date()
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
