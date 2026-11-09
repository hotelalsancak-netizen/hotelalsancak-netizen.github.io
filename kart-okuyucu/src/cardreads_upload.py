#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cardreads_upload  -  Haftalik kart okuma klasorunu ZIP'leyip sifreleyerek
                     GitHub'a yukler.

Akis:
    cardreads/<HAFTA>/*.pdf
        -> tek ZIP (icinde sadece dosya adlari, tam yol yok)
        -> AES-256-GCM ile sifrele
        -> site_data/cardreads-incoming/<HAFTA>.zip.enc olarak GitHub'a PUT

Sifreli dosya formati (evdeki analiz programi bunu bekliyor - DEGISTIRMEYIN):
    [ salt: 16 bayt ][ nonce: 12 bayt ][ ciphertext + 16 baytlik GCM tag ]
    anahtar = PBKDF2-HMAC-SHA256(parola, salt, 200000 tur, 32 bayt)

Derleme:
    pyinstaller --onefile --name cardreads_upload cardreads_upload.py
"""

import base64
import datetime
import hashlib
import io
import os
import re
import sys
import zipfile

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# =====================================================================
# SABITLER  (bu bilgisayari baska personel de kullandigi icin gomulu)
# =====================================================================

GITHUB_TOKEN = ""  # GİZLİ — gerçek değer yalnız resepsiyondaki kopyada; repoya YAZMAYIN
CARD_ZIP_PASSWORD = ""  # GİZLİ — gerçek değer yalnız resepsiyondaki kopyada; repoya YAZMAYIN

GITHUB_REPO = "hotelalsancak-netizen/hotelalsancak-netizen.github.io"
GITHUB_DIZIN = "site_data/cardreads-incoming"
GITHUB_DAL = "main"

PBKDF2_TUR = 200000
PBKDF2_ANAHTAR_UZUNLUK = 32
SALT_UZUNLUK = 16
NONCE_UZUNLUK = 12


# =====================================================================
# Yardimcilar
# =====================================================================

def gizle(metin):
    """Ciktida token'in kazara gorunmesini onler."""
    if not metin:
        return metin
    return metin.replace(GITHUB_TOKEN, "<TOKEN GIZLENDI>")


def yaz(mesaj=""):
    print(mesaj, flush=True)


def hafta_kodu_bul(klasor_yolu):
    """
    Klasor adindan HAFTA kodunu (YYYYMMDD) uretir.

    Desteklenen adlar:
        20260727      -> 20260727   (zaten dogru bicimde)
        27.07.2026    -> 20260727   (OdaKartOku'nun urettigi bicim)
        2026-07-27    -> 20260727
    """
    ad = os.path.basename(os.path.normpath(klasor_yolu))

    if re.fullmatch(r"\d{8}", ad):
        return ad

    m = re.fullmatch(r"(\d{2})[.\-/](\d{2})[.\-/](\d{4})", ad)
    if m:
        gun, ay, yil = m.groups()
        return "{}{}{}".format(yil, ay, gun)

    m = re.fullmatch(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", ad)
    if m:
        yil, ay, gun = m.groups()
        return "{}{}{}".format(yil, ay, gun)

    raise ValueError(
        "Klasor adindan hafta kodu cikarilamadi: '{}'\n"
        "Beklenen bicimler: 20260727  ya da  27.07.2026".format(ad)
    )


# =====================================================================
# 2) ZIP
# =====================================================================

def zip_olustur(klasor_yolu):
    """Klasordeki tum PDF'leri tek ZIP'e koyar. Arsivde SADECE dosya adlari olur."""
    pdfler = sorted(
        d for d in os.listdir(klasor_yolu)
        if d.lower().endswith(".pdf") and os.path.isfile(os.path.join(klasor_yolu, d))
    )
    if not pdfler:
        raise RuntimeError("Klasorde hic PDF yok: " + klasor_yolu)

    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for ad in pdfler:
            tam = os.path.join(klasor_yolu, ad)
            z.write(tam, arcname=ad)          # arcname = sadece dosya adi

    veri = tampon.getvalue()
    yaz("  ZIP olusturuldu : {} dosya, {:.1f} KB".format(len(pdfler), len(veri) / 1024))
    return veri, pdfler


# =====================================================================
# 3) SIFRELEME
# =====================================================================

def sifrele(zip_baytlari):
    """
    salt(16) + nonce(12) + AESGCM ciphertext(+16 bayt tag)  -> ham binary
    """
    salt = os.urandom(SALT_UZUNLUK)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        CARD_ZIP_PASSWORD.encode("utf-8"),
        salt,
        PBKDF2_TUR,
        dklen=PBKDF2_ANAHTAR_UZUNLUK,
    )
    nonce = os.urandom(NONCE_UZUNLUK)
    ct = AESGCM(key).encrypt(nonce, zip_baytlari, None)

    sifreli = salt + nonce + ct
    yaz("  Sifrelendi      : {:.1f} KB  (AES-256-GCM, PBKDF2-SHA256 x{})".format(
        len(sifreli) / 1024, PBKDF2_TUR))
    return sifreli


def sifre_dogrula(sifreli, beklenen_zip):
    """
    Yuklemeden ONCE format dogrulamasi: evdeki analiz programinin yapacagi
    ayristirmanin aynisini yapip icerigin birebir geri geldigini kontrol eder.
    """
    salt = sifreli[:SALT_UZUNLUK]
    nonce = sifreli[SALT_UZUNLUK:SALT_UZUNLUK + NONCE_UZUNLUK]
    ct = sifreli[SALT_UZUNLUK + NONCE_UZUNLUK:]

    key = hashlib.pbkdf2_hmac(
        "sha256", CARD_ZIP_PASSWORD.encode("utf-8"), salt,
        PBKDF2_TUR, dklen=PBKDF2_ANAHTAR_UZUNLUK,
    )
    cozulen = AESGCM(key).decrypt(nonce, ct, None)

    if cozulen != beklenen_zip:
        raise RuntimeError("Dogrulama BASARISIZ: cozulen veri orijinal ZIP ile ayni degil!")

    # ZIP gercekten acilabiliyor mu?
    with zipfile.ZipFile(io.BytesIO(cozulen)) as z:
        bozuk = z.testzip()
        if bozuk:
            raise RuntimeError("Dogrulama BASARISIZ: ZIP icinde bozuk dosya: " + bozuk)
        adet = len(z.namelist())

    yaz("  Dogrulama       : TAMAM (geri cozuldu, {} dosya okunabiliyor)".format(adet))


# =====================================================================
# 4) GITHUB'A YUKLEME  (Contents API - git gerekmez)
# =====================================================================

def github_yukle(hafta, sifreli):
    yol = "{}/{}.zip.enc".format(GITHUB_DIZIN, hafta)
    url = "https://api.github.com/repos/{}/contents/{}".format(GITHUB_REPO, yol)

    basliklar = {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "cardreads-upload/1.0",
    }

    # --- Dosya zaten var mi? Varsa uzerine yazmak icin sha gerekir ---
    mevcut_sha = None
    try:
        r = requests.get(url, headers=basliklar, params={"ref": GITHUB_DAL}, timeout=60)
        if r.status_code == 200:
            mevcut_sha = r.json().get("sha")
            yaz("  Dosya zaten var : uzerine yazilacak")
        elif r.status_code == 404:
            yaz("  Dosya yeni      : ilk kez yuklenecek")
        else:
            yaz("  UYARI: mevcut dosya sorgusu HTTP {} dondu".format(r.status_code))
    except requests.RequestException as e:
        yaz("  UYARI: mevcut dosya sorgulanamadi: " + gizle(str(e)))

    govde = {
        "message": "cardreads {}".format(hafta),
        "content": base64.b64encode(sifreli).decode("ascii"),
        "branch": GITHUB_DAL,
    }
    if mevcut_sha:
        govde["sha"] = mevcut_sha

    yaz("  Yukleniyor      : {}".format(yol))
    r = requests.put(url, headers=basliklar, json=govde, timeout=300)

    if r.status_code not in (200, 201):
        yaz("")
        yaz("  YUKLEME BASARISIZ")
        yaz("  HTTP durum : {}".format(r.status_code))
        yaz("  Yanit      : {}".format(gizle(r.text)[:1500]))
        return None

    veri = r.json()
    commit_sha = (veri.get("commit") or {}).get("sha")
    icerik_yolu = (veri.get("content") or {}).get("path", yol)
    return icerik_yolu, commit_sha


# =====================================================================
# Ana akis
# =====================================================================

def klasor_belirle(argv):
    """1) GIRDI: cardreads/<HAFTA>/ klasorunun yolu."""
    if len(argv) > 1:
        return argv[1].strip().strip('"')

    # Arguman verilmediyse: exe'nin yanindaki cardreads/ icinden en yenisini oner
    kok = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    aday_kok = os.path.join(kok, "cardreads")
    if os.path.isdir(aday_kok):
        altlar = [os.path.join(aday_kok, d) for d in os.listdir(aday_kok)
                  if os.path.isdir(os.path.join(aday_kok, d))]
        if altlar:
            en_yeni = max(altlar, key=os.path.getmtime)
            yaz("Klasor verilmedi, bulunan en yeni klasor kullanilacak:")
            yaz("  " + en_yeni)
            return en_yeni

    yaz("Yuklenecek klasorun tam yolunu yazin (veya klasoru bu pencereye surukleyin):")
    return input("> ").strip().strip('"')


def main(argv):
    yaz("=" * 60)
    yaz("  CARDREADS UPLOAD  -  haftalik kart okuma yukleyici")
    yaz("=" * 60)
    yaz()

    try:
        klasor = klasor_belirle(argv)
        if not klasor or not os.path.isdir(klasor):
            yaz("HATA: Klasor bulunamadi: {}".format(klasor))
            return 2

        hafta = hafta_kodu_bul(klasor)
        yaz("Klasor : {}".format(klasor))
        yaz("Hafta  : {}".format(hafta))
        yaz("Hedef  : {}/{}.zip.enc".format(GITHUB_DIZIN, hafta))
        yaz()

        zip_baytlari, pdfler = zip_olustur(klasor)
        sifreli = sifrele(zip_baytlari)
        sifre_dogrula(sifreli, zip_baytlari)

        yaz()
        sonuc = github_yukle(hafta, sifreli)
        if sonuc is None:
            return 3

        yol, commit_sha = sonuc
        yaz()
        yaz("-" * 60)
        yaz("  YUKLEME BASARILI")
        yaz("-" * 60)
        yaz("  Yuklenen yol : {}".format(yol))
        yaz("  Commit sha   : {}".format(commit_sha))
        yaz("  Dosya sayisi : {}".format(len(pdfler)))
        yaz("  Boyut        : {:.1f} KB".format(len(sifreli) / 1024))
        yaz()
        return 0

    except Exception as e:
        yaz()
        yaz("HATA: " + gizle(str(e)))
        return 1


if __name__ == "__main__":
    kod = main(sys.argv)
    # Cift tiklamayla acildiysa pencere hemen kapanmasin
    if sys.stdin is not None and sys.stdin.isatty():
        try:
            input("\nKapatmak icin Enter'a basin...")
        except Exception:
            pass
    sys.exit(kod)
