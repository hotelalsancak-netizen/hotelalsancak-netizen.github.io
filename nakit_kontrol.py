"""
Nakit Tahsilat Kontrol — veri tarafı (checks.build_nakit sayfayı çizer).

Sahibi 23.11.2026: "Geçen hafta boyunca nakit tahsilatları listele, özellikle liste fiyatı altında
kalanları. Teker teker kameradan kontrol ediyorum, o saatte gerçekten o miktarı almışlar mı diye."
Bu yüzden her satırın başında tahsilatın GERÇEK yerel tarihi-saati ve alan kişi durur.

Yöntem (16.11.2026'da yerel nakit_supheli.py ile kuruldu, burada aynısı):
- Kaynak: Ön Kasa defteri (QA_EASYPMS_DAILYCASHDETAIL), TYPE = 'Folio Cash'.
- Liste kıyası yalnız resepsiyonun kendi fiyatladığı satışlarda (Walk-in / Telefon / acentasız);
  acenta kontrat fiyatı düşük olabilir, bu normaldir.
- "Olması gereken" = SATIŞ ANINDAKİ doluluğa göre liste basamağı (checks.basamak, 25/30/35 oda;
  Cuma–Cmt bir üst). Doluluk = o geceyi kapsayan, satıştan ÖNCE açılmış, o an iptal edilmemiş
  gerçek (sayısal) odalı rezervasyonlar. 7+ gece ve 04.11 öncesi satış: yalnız liste tabanı.

Elektra tuzakları:
- Ön Kasa TIME = UTC (+3 saat).
- Ön Kasa DATE = İŞ GÜNÜ: gün sonu öğlene kadar sürebildiği için gece/sabah tahsilatı bir önceki
  güne yazılır. TIME'ın kendi tarih kısmı tutarlıysa onu, değilse iş günü + saat kullanılır; sonuç
  rezervasyonun açılışından önceye düşerse +1 gün.
- Kasa kullanıcı adı folyodaki tam addan farklı olabilir: ikisi de gösterilir.
- Bakiye 0 olsa da misafirden fazlası alınıp fark cebe atılmış olabilir; sistem bunu GÖSTEREMEZ —
  bu yüzden kamera kontrolü.
"""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

import checks
import elektra_api as E

TR = dt.timedelta(hours=3)
IPTAL = {6, 7, 8}
RES_COLS = ["RESID", "ROOMNO", "ROOMTYPE", "CHECKIN", "CHECKOUT", "NIGHT", "CREATEDATE", "MCTOTALPRICE",
            "AGENCY", "ADULT", "RESSTATEID", "CANCEL_DATE", "GUESTNAMES", "GENERALBALANCE"]
ODA_AD = {"eko": "Ekonomik", "stu": "Stüdyo", "sup": "Superior", "dlx": "Deluxe", "sui": "Suit"}


def P(s):
    try:
        return dt.datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def vardiya(t):
    return "Gündüz" if 8 <= t.hour < 16 else ("Akşam" if t.hour >= 16 else "Gece")


def _kasa(bas, bit, env):
    rows, a = [], bas
    while a <= bit:                         # Elektra uzun aralıkta zaman aşımına düşüyor: 7 günlük parçalar
        b = min(bit, a + dt.timedelta(days=6))
        rows += E.fetch_cash_detail(a.isoformat(), b.isoformat(), env=env)
        a = b + dt.timedelta(days=1)
    seen, out = set(), []
    for r in rows:
        if r.get("TYPE") != "Folio Cash":
            continue
        key = r.get("TRANSACTIONID") or (r.get("DATE"), r.get("TIME"), r.get("RESID"), r.get("LOCALAMOUNT"))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _dolu(rezler, gece, an, haric):
    n = 0
    for r in rezler:
        if r["RESID"] == haric or not str(r.get("ROOMNO") or "").isdigit():
            continue
        ci, co, cr = P(r["CHECKIN"]), P(r["CHECKOUT"]), P(r["CREATEDATE"])
        if not (ci and co and ci.date() <= gece < co.date()) or (cr and cr >= an):
            continue
        if r.get("RESSTATEID") in IPTAL:
            cd = P(r.get("CANCEL_DATE"))
            if not (cd and cd > an):
                continue
        n += 1
    return n


def _olmasi_gereken(x, rezler):
    """(liste tabanı, satış anındaki doluluğa göre gecelik ortalama liste fiyatı, ilk gecenin dolu sayısı)."""
    k = checks.ODA_KOD.get(str(x.get("ROOMTYPE") or "").strip().upper())
    oda = next((o for o in checks.FIYAT_ODALAR if o[0] == k), None)
    ci, co, satis = P(x["CHECKIN"]), P(x["CHECKOUT"]), P(x["CREATEDATE"])
    taban = checks.satis_liste_fiyati(x)
    if not (oda and ci and satis) or taban is None:
        return taban, taban, None
    n = max(1, (co.date() - ci.date()).days if co else 1)
    if n >= 7 or satis.date() < checks.ILK_BASAMAK_04_11:
        return taban, taban, None
    fn = checks.basamak_eski if satis.date() < checks.YENI_LISTE else checks.basamak
    fiyatlar, ilk = [], None
    for i in range(min(n, 31)):
        g = ci.date() + dt.timedelta(days=i)
        d = _dolu(rezler, g, satis, x["RESID"])
        ilk = d if ilk is None else ilk
        fiyatlar.append(checks.ELLE_FIYAT.get((g, k))
                        or oda[3][fn(g, satis.date(), d)] - checks.GECE_INDIRIM.get(g, 0))
    return taban, round(sum(fiyatlar) / len(fiyatlar)), ilk


def _gercek_an(r, acilis):
    """Tahsilatın gerçek yerel tarihi-saati (bkz. modül notu)."""
    t_utc = P(r.get("TIME"))
    is_gunu = P(str(r.get("DATE"))[:10] + " 00:00:00")
    if t_utc and is_gunu and abs((t_utc.date() - is_gunu.date()).days) <= 2:
        return t_utc + TR, "time"
    if not (t_utc and is_gunu):
        return is_gunu, "tarih"
    t = P(str(r["DATE"])[:10] + " " + str(r["TIME"])[11:19]) + TR
    if acilis and t < acilis - dt.timedelta(minutes=5):
        t += dt.timedelta(days=1)
    return t, "is_gunu"


def analiz(bas, bit, env=None):
    """[bas, bit] (yerel tarih) arasındaki TÜM nakit tahsilatlar, satır satır. Kasa iş günü olarak
    bir gün önceden ve bir gün sonrasına kadar çekilir; sonra gerçek yerel tarihe göre süzülür."""
    nakit = _kasa(bas - dt.timedelta(days=1), bit + dt.timedelta(days=1), env)
    ids = sorted({r["RESID"] for r in nakit if r.get("RESID")})
    res = {}
    for i in range(0, len(ids), 40):
        for r in E.fetch_reservations([{"Column": "RESID", "Operator": "IN", "Value": ids[i:i + 40]}],
                                      env=env, columns=RES_COLS):
            res[r["RESID"]] = r
    dogrudan = [i for i in ids if i in res and checks._is_direct_agency(res[i].get("AGENCY"))]

    rezler = []
    if dogrudan:
        girisler = [P(res[i]["CHECKIN"]) for i in dogrudan if P(res[i]["CHECKIN"])]
        rezler = E.fetch_reservations_between(
            "CHECKIN", (min(girisler) - dt.timedelta(days=45)).date().isoformat(),
            max(girisler).date().isoformat(), env=env, columns=RES_COLS)
    tam_ad = {}
    try:
        for f in E.fetch_folio((bas - dt.timedelta(days=2)).isoformat(),
                               (bit + dt.timedelta(days=2)).isoformat(), env=env):
            if f.get("DEPTTYPENAME") == "PAYMENT" and f.get("DEPNAME") == "Cash":
                tam_ad[(f.get("RESID"), round(abs(checks.num(f.get("TOTAL")))))] = f.get("USERFULLNAME")
    except Exception:
        pass
    loglar = {}
    if dogrudan:
        e, _ = E.connect(env)
        with ThreadPoolExecutor(6) as ex:
            loglar = dict(zip(dogrudan, ex.map(lambda i: E._reservation_log(e, i), dogrudan)))

    fiyat = {}
    for rid in dogrudan:
        x = res[rid]
        ci, co = P(x["CHECKIN"]), P(x["CHECKOUT"])
        n = max(1, (co.date() - ci.date()).days if (ci and co) else 1)
        gecelik = round(checks.num(x.get("MCTOTALPRICE")) / n)
        taban, hedef, d0 = _olmasi_gereken(x, rezler)
        ins = [l for l in loglar.get(rid, []) if l.get("ACTION") == "Insert"]
        acan = ins[-1] if ins else None
        acan_t = (P(acan.get("LOGTIMEUTC")) + TR) if acan and P(acan.get("LOGTIMEUTC")) else \
            ((P(x["CREATEDATE"]) + TR) if P(x["CREATEDATE"]) else None)
        fiyat[rid] = dict(n=n, gecelik=gecelik, taban=taban, hedef=hedef, d0=d0,
                          acan=(acan.get("USERID") if acan else None), acan_t=acan_t,
                          liste_alti=hedef is not None and gecelik < hedef - checks.SATIS_PAYI,
                          fark=(gecelik - hedef) if hedef is not None else None)

    satirlar, kaynak = [], {"time": 0, "is_gunu": 0, "tarih": 0}
    bugun = (dt.datetime.utcnow() + TR).date()
    for r in nakit:
        rid = r.get("RESID")
        x = res.get(rid) or {}
        f = fiyat.get(rid)
        acilis = f["acan_t"] if f else ((P(x.get("CREATEDATE")) + TR) if P(x.get("CREATEDATE")) else None)
        an, yol = _gercek_an(r, acilis)
        if not an or not (bas <= an.date() <= bit):
            continue
        kaynak[yol] += 1
        tutar = round(checks.num(r.get("LOCALAMOUNT")))
        ad = tam_ad.get((rid, abs(tutar)))
        kullanici = str(r.get("USER") or "?")
        # Kasa kullanıcısı ile folyoya işleyen ayrı yazılır: "Murat (X)" sanki Murat'ın tam adı X'miş
        # gibi okunuyordu; oysa bazen ödemeyi kasada biri alıp folyoya başkası işliyor (23.11).
        kim = kullanici + (f" · folyoda: {ad}" if ad and kullanici.split()[0].upper() not in str(ad).upper() else "")
        ci, co = P(x.get("CHECKIN")), P(x.get("CHECKOUT"))

        nedenler = []
        if tutar < 0:
            nedenler.append("Nakit İADE — kasadan para çıkmış")
        if 0 <= an.hour < 7:
            nedenler.append("Gece yarısından sonra alınmış (00–07): resepsiyonda genelde tek kişi")
        if not rid:
            nedenler.append("Hiçbir rezervasyona bağlı değil")
        elif x.get("RESSTATEID") in IPTAL:
            nedenler.append("Rezervasyon iptal / gelmedi olarak kapanmış ama nakit alınmış")
        if ci and co and ci.date() == co.date():
            nedenler.append("Günübirlik (0 gece) satış")
        if f and f["hedef"] is None and f["taban"] is None:
            nedenler.append("Liste fiyatı hesaplanamadı (oda tipi tanınmadı) — fiyatı elle kontrol edin")
        if co and tutar > 0 and an.date() > co.date():
            nedenler.append(f"Misafirin çıkış gününden ({co:%d.%m}) SONRA kasaya girilmiş")

        satirlar.append(dict(
            an=an, vardiya=vardiya(an), kim=kim, tutar=tutar,
            doviz=(r.get("CURRENCY") or "TRY"), doviz_tutar=checks.num(r.get("CASHTAKEN")) or None,
            rid=rid, oda=x.get("ROOMNO"), misafir=(x.get("GUESTNAMES") or "").strip(),
            kanal=(x.get("AGENCY") or "").strip(), oda_tipi=ODA_AD.get(
                checks.ODA_KOD.get(str(x.get("ROOMTYPE") or "").strip().upper()), x.get("ROOMTYPE") or ""),
            giris=ci.date() if ci else None, cikis=co.date() if co else None,
            dogrudan=rid in fiyat, fiyat=f, nedenler=nedenler, bakiye=checks.num(x.get("GENERALBALANCE"))))
    satirlar.sort(key=lambda s: s["an"])
    return {"bas": bas, "bit": bit, "satirlar": satirlar, "rez_sayisi": len(ids),
            "dogrudan_sayisi": len([i for i in dogrudan]), "kaynak": kaynak, "bugun": bugun}
