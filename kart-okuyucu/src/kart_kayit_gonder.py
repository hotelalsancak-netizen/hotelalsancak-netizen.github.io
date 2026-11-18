#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KartKayitGonder  -  TEK PROGRAM

Resepsiyonistin cift tikladigi tek dosya. Sirayla:

    1) Kale Kilit'ten tum odalarin kapi acilis kayitlarini okur
       (gomulu OdaKartOku.exe calistirilir)
    2) Gunun klasorunu tek ZIP'e sikistirir
    3) AES-256-GCM ile sifreler
    4) GitHub'a yukler

Sifreleme bicimi ve yukleme adresi cardreads_upload.py icinde tanimlidir;
burada tekrar edilmez.

Derleme (OdaKartOku.exe gomulu olarak):
    pyinstaller --onefile --name KartKayitGonder ^
        --add-binary "C:\\OdaKartOku\\OdaKartOku.exe;." ^
        kart_kayit_gonder.py
"""

import datetime
import os
import re
import subprocess
import sys

import cardreads_upload as yuk
import sonuc_ekrani


OKUYUCU_ADI = "OdaKartOku.exe"
ODA_LISTESI_ADI = "odalar.txt"

# Islem sonucu: program bitince TAM EKRAN gosterilir (sonuc_ekrani.goster).
# 18.11.2026: 16 Kasim okumasi sunucuya gitmedi ve kimse fark etmedi - sonuc
# siyah pencerede kucuk bir satirdi. Her cikis noktasi artik buraya sebep yazar.
SONUC = None
CIKTI = []          # yukleyicinin ekrana yazdiklari (HTTP kodu vb. icin)


def sonuc_belirle(durum, baslik, aciklama="", ayrintilar=None, yapilacaklar=None):
    global SONUC
    SONUC = dict(durum=durum, baslik=baslik, aciklama=aciklama,
                 ayrintilar=list(ayrintilar or []), yapilacaklar=list(yapilacaklar or []))


def _yakala(mesaj=""):
    CIKTI.append(str(mesaj))
    print(mesaj, flush=True)


yuk.yaz = _yakala   # cardreads_upload'un ciktisini da topla (gizli degerlere dokunmadan)


TR_AY = ["", "Ocak", "Subat", "Mart", "Nisan", "Mayis", "Haziran", "Temmuz",
         "Agustos", "Eylul", "Ekim", "Kasim", "Aralik"]


def hafta_etiketi(hafta):
    """Okuma tarihi (YYYYMMDD) -> panoda gorunecek hafta: okumadan ONCEKI son
    Pazartesi-Pazar (sunucudaki kart_yukle.week_of ile ayni kural)."""
    try:
        d = datetime.date(int(hafta[:4]), int(hafta[4:6]), int(hafta[6:8]))
    except Exception:
        return ""
    pazar = d - datetime.timedelta(days=d.weekday() + 1)
    pzt = pazar - datetime.timedelta(days=6)
    return "{} {} - {} {} {}".format(pzt.day, TR_AY[pzt.month], pazar.day,
                                     TR_AY[pazar.month], pazar.year)


def http_aciklamasi(kod):
    return {
        401: "GitHub izin anahtari (token) GECERSIZ veya SURESI DOLMUS.",
        403: "GitHub erisimi REDDETTI (anahtarin yazma izni yok ya da gecici engel).",
        404: "Depo bulunamadi ya da anahtarin bu depoya erisimi yok.",
        409: "Sunucuda cakisma oldu (ayni anda baska bir guncelleme).",
        422: "Sunucu dosyayi kabul etmedi (cakisma ya da gecersiz istek).",
    }.get(kod, "Sunucu beklenmeyen bir yanit verdi.")


def yukleme_hata_ayrintisi():
    """CIKTI'dan HTTP durum kodunu ve yanit metnini cikarir."""
    kod, yanit = None, ""
    for s in CIKTI:
        m = re.search(r"HTTP durum\s*:\s*(\d+)", s)
        if m:
            kod = int(m.group(1))
        m = re.search(r"Yanit\s*:\s*(.*)", s)
        if m:
            yanit = m.group(1).strip()
    return kod, yanit


def yaz(mesaj=""):
    print(mesaj, flush=True)


# =====================================================================
# Eksik oda kontrolu
# =====================================================================

def oda_listesi_yolu():
    """odalar.txt dosyasinin yolu (once C:\\OdaKartOku, sonra exe'nin yani)."""
    adaylar = [os.path.join(r"C:\OdaKartOku", ODA_LISTESI_ADI)]
    kok = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    adaylar.append(os.path.join(kok, ODA_LISTESI_ADI))
    for a in adaylar:
        if os.path.isfile(a):
            return a
    return adaylar[0]          # yoksa ilk adaya yazilacak


def beklenen_odalari_oku():
    """Beklenen oda listesini doner. Dosya yoksa None."""
    yol = oda_listesi_yolu()
    if not os.path.isfile(yol):
        return None, yol
    odalar = []
    with open(yol, "r", encoding="utf-8-sig") as f:
        for satir in f:
            s = satir.strip()
            if not s or s.startswith("#"):
                continue
            odalar.append(s)
    return odalar, yol


def oda_listesi_olustur(yol, odalar):
    """Referans listeyi ilk kez olusturur."""
    with open(yol, "w", encoding="utf-8-sig") as f:
        f.write("# RIVA HOTEL ALSANCAK - beklenen oda listesi\n")
        f.write("# Her satirda bir oda adi. # ile baslayan satirlar aciklamadir.\n")
        f.write("# Otele oda eklenir/cikarilirsa bu dosyayi guncelleyin.\n\n")
        for o in odalar:
            f.write(o + "\n")


def hedef_klasor_belirle(argv):
    """Okuma yapilmadan ONCE hedef klasoru hesaplar (OdaKartOku ile ayni kural)."""
    for a in argv:
        if a.lower().startswith("/klasor:"):
            return a.split(":", 1)[1].strip('"')
    masaustu = os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(masaustu, datetime.datetime.now().strftime("%d.%m.%Y"))


def eksikleri_yazdir(eksik, beklenen_sayisi, bulunan_sayisi):
    yaz("  Beklenen oda : {}".format(beklenen_sayisi))
    yaz("  Elde edilen  : {}".format(bulunan_sayisi))
    yaz("  EKSIK        : {} oda".format(len(eksik)))
    yaz()
    # eksikleri 10'arli satirlar halinde yaz
    for i in range(0, len(eksik), 10):
        yaz("      " + ", ".join(eksik[i:i + 10]))


def klasordeki_odalar(klasor):
    return sorted(
        os.path.splitext(d)[0]
        for d in os.listdir(klasor)
        if d.lower().endswith(".pdf")
    )


def eksik_oda_kontrolu(klasor):
    """
    Gonderim oncesi butunluk kontrolu.
    Doner: (tamam_mi, eksik_listesi, fazla_listesi, beklenen_sayisi, bulunan_listesi)
    """
    bulunan = klasordeki_odalar(klasor)
    beklenen, yol = beklenen_odalari_oku()

    if beklenen is None:
        # Referans liste yok: bu calistirmadan uret, kullaniciyi uyar
        oda_listesi_olustur(yol, bulunan)
        yaz("UYARI: Beklenen oda listesi yoktu, bu calistirmadan olusturuldu:")
        yaz("       " + yol)
        yaz("       Lutfen icindeki oda listesinin DOGRU oldugunu kontrol edin.")
        yaz()
        return True, [], [], len(bulunan), bulunan

    bulunan_kume = set(bulunan)
    eksik = [o for o in beklenen if o not in bulunan_kume]
    fazla = sorted(bulunan_kume - set(beklenen))
    return (len(eksik) == 0), eksik, fazla, len(beklenen), bulunan


def gomulu_yol(ad):
    """PyInstaller paketi icindeki dosyanin gercek yolu."""
    kok = getattr(sys, "_MEIPASS", None)
    if kok:
        aday = os.path.join(kok, ad)
        if os.path.exists(aday):
            return aday
    # paketlenmemis calistirma / yedek: exe'nin yanina bak
    kok2 = os.path.dirname(os.path.abspath(
        sys.executable if getattr(sys, "frozen", False) else __file__))
    for aday in (os.path.join(kok2, ad), os.path.join(r"C:\OdaKartOku", ad)):
        if os.path.exists(aday):
            return aday
    return None


def kayitlari_oku(ek_argumanlar=None):
    """
    Gomulu OdaKartOku.exe'yi calistirir, ciktisini canli gosterir.
    ek_argumanlar: bu programa verilen argumanlar oldugu gibi aktarilir
                   (orn. /ilk:12 /son:12 ile sadece bir odayi tekrar almak).
    Doner: (cikis_kodu, hedef_klasor)  -  klasor bulunamazsa None
    """
    okuyucu = gomulu_yol(OKUYUCU_ADI)
    if not okuyucu:
        yaz("HATA: {} bulunamadi (pakete gomulmemis).".format(OKUYUCU_ADI))
        return 1, None

    klasor = None
    desen = re.compile(r"Hedef klasor\s*:\s*(.+?)\s*$")

    # OdaKartOku.exe kendi klasorunden calismali (gunlugu oraya yazar)
    calisma_dizini = r"C:\OdaKartOku" if os.path.isdir(r"C:\OdaKartOku") \
        else os.path.dirname(okuyucu)

    argv = [okuyucu, "/beklemeden"]
    if ek_argumanlar:
        argv.extend(ek_argumanlar)

    surec = subprocess.Popen(
        argv,
        cwd=calisma_dizini,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    for satir in surec.stdout:
        satir = satir.rstrip("\r\n")
        print(satir, flush=True)
        if klasor is None:
            m = desen.search(satir)
            if m:
                klasor = m.group(1).strip()

    surec.wait()
    return surec.returncode, klasor


def main():
    yaz("#" * 62)
    yaz("#  KART KAYIT GONDER  -  okuma + sifreleme + sunucuya yukleme")
    yaz("#" * 62)
    yaz()
    yaz("  Program calisirken FARE VE KLAVYEYE DOKUNMAYIN.")
    yaz("  Kale Kilit penceresi kullanilacak.")
    yaz()

    # ---------- 0) OKUMA ONCESI KONTROL ----------
    yaz("=" * 62)
    yaz("  ADIM 1/3  -  Eksik oda kontrolu")
    yaz("=" * 62)
    yaz()

    bayraklar = [a.lower() for a in sys.argv[1:]]
    zorla = "/zorla" in bayraklar
    tumunu = "/tumunu" in bayraklar

    on_klasor = hedef_klasor_belirle(sys.argv[1:])
    yaz("Bugunun klasoru : {}".format(on_klasor))

    beklenen, liste_yolu = beklenen_odalari_oku()
    if beklenen is None:
        yaz("Beklenen oda listesi henuz yok ({}).".format(liste_yolu))
        yaz("Ilk calistirmadan sonra olusturulacak.")
        yaz()
    elif os.path.isdir(on_klasor):
        on_bulunan = klasordeki_odalar(on_klasor)
        on_eksik = [o for o in beklenen if o not in set(on_bulunan)]
        if len(on_bulunan) > 0:
            yaz("Bu gun icin daha once alinmis: {} oda".format(len(on_bulunan)))
        if not on_eksik and len(on_bulunan) > 0 and not tumunu:
            yaz()
            yaz("TUM ODALAR ZATEN ALINMIS - okuma adimi atlaniyor.")
            yaz("(Bastan okumak icin:  KartKayitGonder.exe /tumunu)")
            yaz()
            return gonderim_yap(on_klasor, 0)
        if on_eksik and len(on_bulunan) > 0:
            yaz("Eksik olan {} oda okunacak, digerleri atlanacak.".format(len(on_eksik)))
    else:
        yaz("Klasor henuz yok, tum odalar okunacak.")
    yaz()

    # ---------- 1) OKUMA ----------
    yaz("=" * 62)
    yaz("  ADIM 2/3  -  Oda kayitlari okunuyor")
    yaz("=" * 62)
    yaz()

    okuma_kodu, klasor = kayitlari_oku(sys.argv[1:])

    if klasor is None:
        klasor = on_klasor           # okuma ciktisindan okunamadiysa hesaplanani kullan
    if klasor is None:
        yaz()
        yaz("HATA: Kayit klasoru belirlenemedi, gonderim yapilamiyor.")
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Kart okuma programi kayit klasorunu olusturamadi.",
                      ["Okuma programinin cikis kodu: {}".format(okuma_kodu)],
                      OKUMA_YAPILACAK)
        return 2

    if not os.path.isdir(klasor):
        yaz()
        yaz("HATA: Kayit klasoru olusmamis: {}".format(klasor))
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Kart kayitlari okunamadi - kayit klasoru olusmadi.",
                      ["Beklenen klasor: " + klasor,
                       "Okuma programinin cikis kodu: {}".format(okuma_kodu)],
                      OKUMA_YAPILACAK)
        return 2

    pdf_sayisi = len([d for d in os.listdir(klasor) if d.lower().endswith(".pdf")])
    if pdf_sayisi == 0:
        yaz()
        yaz("HATA: Klasorde hic PDF yok, gonderilecek bir sey yok.")
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Hicbir odanin kaydi alinamadi (klasor bos).",
                      ["Klasor: " + klasor,
                       "Okuma programinin cikis kodu: {}".format(okuma_kodu)],
                      OKUMA_YAPILACAK)
        return 2

    # ---------- GONDERIM ONCESI BUTUNLUK KAPISI ----------
    tamam, eksik, fazla, beklenen_sayisi, bulunan = eksik_oda_kontrolu(klasor)

    if fazla:
        yaz()
        yaz("NOT: Listede olmayan {} oda bulundu: {}".format(len(fazla), ", ".join(fazla)))
        yaz("     Otele yeni oda eklendiyse {} dosyasini guncelleyin.".format(
            oda_listesi_yolu()))

    if not tamam and zorla:
        yaz()
        yaz("UYARI: {} oda eksik ama /zorla verildigi icin yine de gonderiliyor.".format(len(eksik)))
        tamam = True

    if not tamam:
        yaz()
        yaz("#" * 62)
        yaz("#  EKSIK ODA VAR  -  SUNUCUYA GONDERILMEDI")
        yaz("#" * 62)
        yaz()
        eksikleri_yazdir(eksik, beklenen_sayisi, len(bulunan))
        yaz()
        yaz("  Bu odalarin kilitleri el terminaline OKUTULMAMIS.")
        yaz()
        yaz("  YAPILACAKLAR:")
        yaz("    1) El terminaliyle yukaridaki odalarin kilitlerini okutun")
        yaz("    2) Terminali USB ile bilgisayara takin")
        yaz("    3) Bu programi tekrar calistirin")
        yaz()
        yaz("  Zaten alinmis {} oda korunuyor; tekrar calistirdiginizda".format(len(bulunan)))
        yaz("  yalnizca eksikler okunacak, bastan baslamayacak.")
        yaz()
        yaz("  (Eksik olsa da gondermek icin:  KartKayitGonder.exe /zorla)")
        yaz()
        sonuc_belirle(
            "basarisiz", "GONDERILEMEDI",
            "{} odanin kilit kaydi EKSIK. Sunucuya HICBIR SEY gonderilmedi.".format(len(eksik)),
            ["Eksik odalar:  " + ", ".join(eksik),
             "Beklenen {} oda, alinan {} oda.".format(beklenen_sayisi, len(bulunan)),
             "Kayit klasoru: " + klasor],
            ["El terminaliyle yukaridaki odalarin kilitlerini okutun.",
             "Terminali USB ile bilgisayara takin.",
             "Masaustundeki KART KAYITLARINI AL VE GONDER'e tekrar cift tiklayin "
             "(alinan odalar korunur, yalnizca eksikler okunur).",
             "Yine olmazsa bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
        return 5

    yaz()
    yaz("Butunluk kontrolu TAMAM: beklenen {} odanin hepsi var.".format(beklenen_sayisi))

    return gonderim_yap(klasor, okuma_kodu)


def gonderim_yap(klasor, okuma_kodu):
    """Klasoru zipleyip sifreleyerek sunucuya gonderir."""
    # ---------- GONDERIM ----------
    yaz()
    yaz("=" * 62)
    yaz("  ADIM 3/3  -  Sifrelenip sunucuya gonderiliyor")
    yaz("=" * 62)
    yaz()

    try:
        hafta = yuk.hafta_kodu_bul(klasor)
    except ValueError as e:
        yaz("HATA: " + str(e))
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Klasor adindan tarih anlasilamadi.",
                      [str(e), "Klasor: " + klasor],
                      ["Klasor adi GG.AA.YYYY bicimde olmali (orn. 16.11.2026).",
                       "Bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
        return 3

    yaz("Klasor : {}".format(klasor))
    yaz("Hafta  : {}".format(hafta))
    yaz("Hedef  : {}/{}.zip.enc".format(yuk.GITHUB_DIZIN, hafta))
    yaz()

    try:
        zip_baytlari, pdfler = yuk.zip_olustur(klasor)
        sifreli = yuk.sifrele(zip_baytlari)
        yuk.sifre_dogrula(sifreli, zip_baytlari)
    except Exception as e:
        yaz()
        yaz("HATA: " + yuk.gizle(str(e)))
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Dosya hazirlanirken (zip / sifreleme) hata oldu. Hicbir sey gonderilmedi.",
                      [yuk.gizle(str(e))[:300], "Klasor: " + klasor],
                      ["Programi bir kez daha calistirin.",
                       "Yine olmazsa bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
        return 3

    yaz()
    try:
        sonuc = yuk.github_yukle(hafta, sifreli)
    except Exception as e:                      # internet yok, zaman asimi...
        yaz("HATA: " + yuk.gizle(str(e)))
        sonuc_belirle("basarisiz", "YUKLEME BASARISIZ",
                      "Sunucuya ulasilamadi - INTERNET baglantisi yok ya da koptu.",
                      ["Kart kayitlari bilgisayarda DURUYOR, kaybolmadi ({} oda).".format(len(pdfler)),
                       "Hafta: " + hafta_etiketi(hafta),
                       "Hata: " + yuk.gizle(str(e))[:200]],
                      ["Internetin calistigini kontrol edin (bir web sitesi acin).",
                       "Masaustundeki KART KAYITLARINI AL VE GONDER'e tekrar cift tiklayin "
                       "(okuma TEKRARLANMAZ, yalnizca gonderilir).",
                       "Yine olmazsa bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
        return 4
    if sonuc is None:
        kod, yanit = yukleme_hata_ayrintisi()
        sonuc_belirle("basarisiz", "YUKLEME BASARISIZ",
                      "Kartlar okundu ama SUNUCUYA GONDERILEMEDI.",
                      [http_aciklamasi(kod),
                       "HTTP kodu: {}   Yanit: {}".format(kod, yanit[:160]),
                       "Kart kayitlari bilgisayarda DURUYOR, kaybolmadi ({} oda).".format(len(pdfler)),
                       "Hafta: " + hafta_etiketi(hafta)],
                      ["Bu ekranin FOTOGRAFINI cekip HEMEN yoneticiye gonderin."
                       if kod in (401, 403, 404) else
                       "Masaustundeki KART KAYITLARINI AL VE GONDER'e tekrar cift tiklayin "
                       "(okuma TEKRARLANMAZ, yalnizca gonderilir).",
                       "Bu sorun cozulmeden bu haftanin kart kontrolu PANODA GORUNMEZ."])
        return 4

    yol, commit_sha = sonuc

    # ---------- OZET ----------
    yaz()
    yaz("#" * 62)
    yaz("#  ISLEM TAMAMLANDI")
    yaz("#" * 62)
    yaz("  Okunan oda    : {}".format(len(pdfler)))
    yaz("  Klasor        : {}".format(klasor))
    yaz("  Yuklenen yol  : {}".format(yol))
    yaz("  Commit sha    : {}".format(commit_sha))
    yaz("  Boyut         : {:.1f} KB".format(len(sifreli) / 1024))
    yaz()

    ayr = ["Okunan oda: {}".format(len(pdfler)),
           "Hafta: " + hafta_etiketi(hafta),
           "Analiz birkac dakika icinde panoda (Haftalik Kart Guvenligi) gorunur."]
    if okuma_kodu == 0:
        sonuc_belirle("basarili", "GONDERILDI",
                      "Kart kayitlari sunucuya ulasti.", ayr)
    else:
        sonuc_belirle("uyari", "GONDERILDI",
                      "Kayitlar sunucuya ulasti, ama okuma sirasinda bazi hatalar oldu.",
                      ayr + ["Okuma programinin cikis kodu: {}".format(okuma_kodu)],
                      ["Siyah penceredeki yazilarin FOTOGRAFINI yoneticiye gonderin."])
    return 0 if okuma_kodu == 0 else 10


OKUMA_YAPILACAK = [
    "El terminalinin USB ile TAKILI oldugunu kontrol edin.",
    "Kale Kilit programini kapatin, sonra KART KAYITLARINI AL VE GONDER'e tekrar cift tiklayin.",
    "Yine olmazsa bu ekranin FOTOGRAFINI cekip yoneticiye gonderin.",
]


def kurulum_testi():
    """KartKayitGonder.exe /test  ->  okuma YAPMADAN kurulumu dener ve sonucu
    tam ekranda gosterir: oda listesi, gizli degerler, internet + GitHub anahtari."""
    import requests
    sorunlar, iyiler = [], []
    beklenen, yol = beklenen_odalari_oku()
    if beklenen is None:
        sorunlar.append("Oda listesi yok: " + yol)
    else:
        iyiler.append("Oda listesi: {} oda ({})".format(len(beklenen), yol))
    if not yuk.GITHUB_TOKEN:
        sorunlar.append("GitHub anahtari (GITHUB_TOKEN) BOS - program derlenirken girilmemis.")
    if not yuk.CARD_ZIP_PASSWORD:
        sorunlar.append("Sifreleme parolasi (CARD_ZIP_PASSWORD) BOS.")
    if not gomulu_yol(OKUYUCU_ADI):
        sorunlar.append("Kart okuma programi ({}) bulunamadi.".format(OKUYUCU_ADI))
    if yuk.GITHUB_TOKEN:
        url = "https://api.github.com/repos/{}/contents/{}".format(yuk.GITHUB_REPO, yuk.GITHUB_DIZIN)
        try:
            r = requests.get(url, params={"ref": yuk.GITHUB_DAL}, timeout=30, headers={
                "Authorization": "Bearer " + yuk.GITHUB_TOKEN,
                "Accept": "application/vnd.github+json",
                "User-Agent": "cardreads-upload/1.0"})
            if r.status_code == 200:
                adlar = sorted(x.get("name", "") for x in r.json())
                iyiler.append("Internet ve GitHub anahtari: TAMAM")
                if adlar:
                    iyiler.append("Sunucudaki son kart dosyasi: " + adlar[-1])
            else:
                sorunlar.append("GitHub: HTTP {} - {}".format(r.status_code, http_aciklamasi(r.status_code)))
        except Exception as e:
            sorunlar.append("Internet / GitHub'a ulasilamadi: " + yuk.gizle(str(e))[:150])
    if sorunlar:
        sonuc_belirle("basarisiz", "TEST BASARISIZ",
                      "Program bu haliyle kartlari sunucuya GONDEREMEZ.",
                      sorunlar + iyiler,
                      ["Bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
        return 6
    sonuc_belirle("basarili", "TEST TAMAM",
                  "Program kullanima hazir. (Bu bir denemeydi - kart okunmadi, bir sey gonderilmedi.)",
                  iyiler)
    return 0


if __name__ == "__main__":
    try:
        if "/test" in [a.lower() for a in sys.argv[1:]]:
            kod = kurulum_testi()
        else:
            kod = main()
    except KeyboardInterrupt:
        yaz("\nKullanici tarafindan durduruldu.")
        kod = 130
        sonuc_belirle("basarisiz", "GONDERILEMEDI", "Program yarida durduruldu (Ctrl+C).",
                      [], ["Programi bastan tekrar calistirin."])
    except Exception as e:
        yaz("\nBEKLENMEYEN HATA: " + yuk.gizle(str(e)))
        kod = 1
        sonuc_belirle("basarisiz", "GONDERILEMEDI",
                      "Programda beklenmeyen bir hata oldu. Hicbir sey gonderilmemis olabilir.",
                      [yuk.gizle(str(e))[:300]],
                      ["Programi bir kez daha calistirin.",
                       "Yine olmazsa bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])

    if SONUC is None:                          # hicbir cikis noktasi sebep yazmadiysa
        if kod in (0, 10):
            sonuc_belirle("basarili" if kod == 0 else "uyari", "GONDERILDI")
        else:
            sonuc_belirle("basarisiz", "GONDERILEMEDI",
                          "Program hata koduyla bitti: {}".format(kod), [],
                          ["Bu ekranin FOTOGRAFINI cekip yoneticiye gonderin."])
    try:
        sonuc_ekrani.goster(alt_bilgi="KartKayitGonder  -  " +
                            datetime.datetime.now().strftime("%d.%m.%Y %H:%M") +
                            "  -  cikis kodu {}".format(kod), **SONUC)
    except Exception as e:
        yaz("(Sonuc ekrani gosterilemedi: {})".format(e))

    try:
        input("\nKapatmak icin Enter'a basin...")
    except Exception:
        pass
    sys.exit(kod)
