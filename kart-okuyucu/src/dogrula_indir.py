#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dogrula_indir.py - EVDEKI ANALIZ PROGRAMININ yapacagi islemin birebir taklidi.

GitHub'daki sifreli dosyayi indirir, cozer, ZIP'i acar ve icerigi listeler.
Amaci: yuklenen dosyanin dogru formatta oldugunu BAGIMSIZ olarak kanitlamak.
Token gerektirmez (depo herkese acik).
"""

import hashlib
import io
import sys
import zipfile

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CARD_ZIP_PASSWORD = ""  # GİZLİ — gerçek değer yalnız resepsiyondaki kopyada; repoya YAZMAYIN

HAM_URL = ("https://raw.githubusercontent.com/"
           "hotelalsancak-netizen/hotelalsancak-netizen.github.io/"
           "main/site_data/cardreads-incoming/{}.zip.enc")


def main(hafta):
    url = HAM_URL.format(hafta)
    print("Indiriliyor :", url)

    r = requests.get(url, timeout=120)
    if r.status_code != 200:
        print("HATA: HTTP {} - dosya bulunamadi".format(r.status_code))
        return 1

    sifreli = r.content
    print("Indirilen   : {:.1f} KB".format(len(sifreli) / 1024))

    # ---- Formatin ayristirilmasi: salt(16) + nonce(12) + ct ----
    salt = sifreli[:16]
    nonce = sifreli[16:28]
    ct = sifreli[28:]
    print("salt        : {} bayt".format(len(salt)))
    print("nonce       : {} bayt".format(len(nonce)))
    print("ciphertext  : {} bayt (son 16 bayt GCM tag)".format(len(ct)))

    key = hashlib.pbkdf2_hmac("sha256", CARD_ZIP_PASSWORD.encode(), salt, 200000, dklen=32)
    zip_baytlari = AESGCM(key).decrypt(nonce, ct, None)
    print("Cozuldu     : {:.1f} KB".format(len(zip_baytlari) / 1024))

    with zipfile.ZipFile(io.BytesIO(zip_baytlari)) as z:
        adlar = z.namelist()
        bozuk = z.testzip()
        if bozuk:
            print("HATA: bozuk dosya:", bozuk)
            return 1
        # ilk PDF gercekten PDF mi?
        ilk = z.read(adlar[0])[:5]

    print("ZIP icerigi : {} dosya".format(len(adlar)))
    print("Ilk dosya   : {}  ({} bayt basligi: {})".format(adlar[0], 5, ilk))
    print("Odalar      : " + ", ".join(sorted(a.replace(".pdf", "") for a in adlar)))
    print()
    print("SONUC: FORMAT DOGRU - evdeki program bu dosyayi sorunsuz cozebilir.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "20260727"))
