#!/usr/bin/env python3
"""Fiyat bandı — Elektra'daki oda temel fiyatlarını fiyat listesine göre tutar.

Kural (sahibin onayı 27.10.2026, docs/pricelist/fiyat-listesi.md; tablo checks.FIYAT_ODALAR, basamak
seçimi checks.basamak): her odanın üç fiyat basamağı var. İleri tarihli Pazar–Cuma gecesi 1. basamakta
başlar, 30 oda satılınca 2., 40 oda satılınca 3. basamağa çıkar; ileri tarihli Cumartesi 2.'de başlar,
30 odada 3.'ye çıkar. Gece "aynı gün" olunca (gece yarısı) Pazar–Cuma en az 2., Cumartesi 3. basamaktır;
40 odada 3. Elektra'ya giden temel fiyat EUR'dur: € = TL ÷ günün kuru (iki ondalık, YUKARI). Kur,
Elektra'nın kendi günlük kurudur (TCMB döviz alış; rezervasyon motoru da TL'yi bununla hesaplar).
Kanallara Elektra kendisi gönderir (temel fiyat × kanal çarpanı).

Kullanım:
  python fiyat_bandi.py                          # otomatik (bulutta yarım saatte bir)
  python fiyat_bandi.py --tablo 2026-10-27 2027-03-31   # aralığın bütün gecelerini tabloya yazar
  ... --kuru                                     # yazmadan ne yapacağını göster

Otomatik mod, her gece × oda tipi için:
  1. TABAN: gecenin bugünkü basamağı (tarih, Cumartesi, doluluk). Elektra fiyatı günün kuruyla
     tabanın altındaysa (gece yarısı aynı güne geçti, 30/40 oda doldu ya da kur düştü) hemen tabana çıkar.
  2. KUR: fiyat tabandaki ya da daha yüksek bir basamağa yakınsa (±%6), euro yükseldiği için misafir
     KUR_PAYI TL'den fazla öderse € o basamağa indirilir. Yükselmiş gece iptallerle boşalsa da
     basamağı düşmez.
  3. Hiçbir basamağa yakın olmayan fiyat (elle girilmiş özel fiyat: bayram, etkinlik) olduğu gibi kalır,
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


def hedefler(dol, frm, to, bugun):
    """{(gece, oda tipi ID): hedef €} tablo, tarih ve doluluğa göre."""
    out, d = {}, frm
    while d <= to:
        for rt, (oda, _) in ODA.items():
            out[(d, rt)] = euro(checks.gece_hedef(oda, d, dol.get(d, 0), bugun))
        d += GUN
    return out


def kontrol(e, hid, frm, to, bekle):
    """Elektra'yı yeniden oku; beklenenden farklı gece/oda tipi listesi."""
    simdi = elektra_fiyatlar(e, hid, frm, to)
    return [(d, rt, simdi.get((d, rt)), v) for (d, rt), v in sorted(bekle.items())
            if simdi.get((d, rt)) is None or abs(simdi[(d, rt)] - v) > PAY]


def tablo(e, env, hid, frm, to, bugun, kuru):
    """Aralığın bütün gecelerini tarih, Cumartesi ve doluluğa göre tabloya yazar."""
    dol = checks.gece_doluluk(env, frm, to)
    bekle = hedefler(dol, frm, to, bugun)
    simdi = elektra_fiyatlar(e, hid, frm, to)
    yaz_hedefler(e, hid, bekle, simdi, kuru, hepsi=True)
    return bekle


def otomatik(e, env, hid, bugun, kuru):
    son = bugun + dt.timedelta(days=UFUK)
    dol = checks.gece_doluluk(env, bugun, son)
    simdi = elektra_fiyatlar(e, hid, bugun, son)
    bekle, neden = {}, {}
    for (d, rt), p in simdi.items():
        if rt not in ODA or p <= 0:
            continue    # fiyatı girilmemiş gece satışa kapalıdır; açma
        oda, ad = ODA[rt]
        b0 = checks.basamak(d, bugun, dol.get(d, 0))
        ind = checks.GECE_INDIRIM.get(d, 0)      # sahibin tek gecelik indirimi tabloyu aşağı çeker
        adaylar = [euro(oda[3][i] - ind) for i in range(b0, 3)]
        taban = adaylar[0]
        if p < taban - PAY:
            if b0 > checks.basamak(d, bugun, 0):
                why = "doluluk"
            elif d <= bugun and checks.basamak(d, bugun, 0) > checks.basamak(d, d - GUN, 0):
                why = "aynı gün"
            else:
                why = "taban"
            bekle[(d, rt)], neden[(d, rt)] = taban, why
            continue
        yakin = [c for c in adaylar if abs(p - c) <= PENCERE * c]
        if yakin:
            c = min(yakin, key=lambda c: abs(p - c))
            if (p - c) * KUR > KUR_PAYI:
                bekle[(d, rt)], neden[(d, rt)] = c, "kur"
    if not bekle:
        print(f"değişiklik yok (kur {KUR})")
        return bekle
    sayi = {}
    for k, v in neden.items():
        sayi.setdefault((ODA[k[1]][1], v), []).append(k[0])
    for (ad, v), gunler in sorted(sayi.items()):
        aciklama = {"aynı gün": "gece yarısı aynı gün fiyatına geçti", "doluluk": "30/40 oda · üst basamak",
                    "taban": "tabanın altındaydı (yeni liste ya da kur) · tabana çıkarıldı", "kur": "euro yükseldi · € indirildi"}[v]
        print(f"{ad}: {len(gunler)} gece ({min(gunler)} – {max(gunler)}) · {aciklama}")
    yaz_hedefler(e, hid, bekle, simdi, kuru)
    return bekle


def yaz_hedefler(e, hid, bekle, simdi, kuru, hepsi=False):
    """Hedef €'ları en az çağrıyla yazar. Her oda tipi için 91 gecelik pencereler; pencerede bir hafta
    günü (ör. bütün Salılar) aynı değere gidiyorsa ve o günlerin hepsi güvenliyse (yazılacak ya da zaten
    o değerde) aynı değere giden hafta günleri tek çağrıda bayrakla yazılır. Güvenli olmayan (özel fiyatlı,
    fiyatsız) gece varsa o hafta gününün gecileri tek tek yazılır; aradaki geceye dokunulmaz.
    hepsi=True (--tablo): aralıktaki her gece hedeftir, fiyatsız gece de yazılır."""
    n = 0
    for rt in ODA:
        geceler = sorted(d for (d, r) in bekle if r == rt)
        if not geceler:
            continue
        w0, son = geceler[0], geceler[-1]
        while w0 <= son:
            w1 = min(son, w0 + dt.timedelta(days=90))
            gruplar, tek = {}, []
            for wd in range(7):
                ds = [w0 + dt.timedelta(days=i) for i in range((w1 - w0).days + 1)]
                ds = [d for d in ds if d.weekday() == wd]
                gerek = [d for d in ds if (d, rt) in bekle]
                if not gerek:
                    continue
                degerler = {bekle[(d, rt)] for d in gerek}
                if len(degerler) == 1:
                    v = degerler.pop()
                    if hepsi or all((d, rt) in bekle or abs(simdi.get((d, rt), -1) - v) <= PAY for d in ds):
                        gruplar.setdefault(v, []).append(wd)
                        continue
                tek += gerek
            for v, wds in sorted(gruplar.items()):
                yaz(e, hid, rt, w0, w1, v, tuple(wds), kuru)
                n += 1
            for d in tek:
                yaz(e, hid, rt, d, d, bekle[(d, rt)], None, kuru)
                n += 1
            w0 = w1 + GUN
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
        bekle = tablo(e, env, hid, frm, to, bugun, a.kuru)
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
