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


OKUYUCU_ADI = "OdaKartOku.exe"
ODA_LISTESI_ADI = "odalar.txt"


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
        return 2

    if not os.path.isdir(klasor):
        yaz()
        yaz("HATA: Kayit klasoru olusmamis: {}".format(klasor))
        return 2

    pdf_sayisi = len([d for d in os.listdir(klasor) if d.lower().endswith(".pdf")])
    if pdf_sayisi == 0:
        yaz()
        yaz("HATA: Klasorde hic PDF yok, gonderilecek bir sey yok.")
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
        return 3

    yaz()
    sonuc = yuk.github_yukle(hafta, sifreli)
    if sonuc is None:
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

    return 0 if okuma_kodu == 0 else 10


if __name__ == "__main__":
    try:
        kod = main()
    except KeyboardInterrupt:
        yaz("\nKullanici tarafindan durduruldu.")
        kod = 130
    except Exception as e:
        yaz("\nBEKLENMEYEN HATA: " + yuk.gizle(str(e)))
        kod = 1

    try:
        input("\nKapatmak icin Enter'a basin...")
    except Exception:
        pass
    sys.exit(kod)
