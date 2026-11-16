"""Elle girilen borç ve vergiler — Borçlar / Vergiler sayfaları için.

Elektra'da olmayan kalemler (şahsi kredi, kredi kartı, elden borç, emlak vergisi, MTV)
site_data/elle.enc.json'da YÖNETİM parolasıyla şifreli durur; depo herkese açık olduğu
için düz metin ASLA commit edilmez. Panel her derlemede bu dosyayı DASH_PW_MANAGER ile açar.

Kullanım (parola .env'deki DASH_PW_MANAGER'dan okunur):
    python3 elle_kayit.py goster              # şifreyi çözüp JSON'u yazdırır
    python3 elle_kayit.py yaz kayit.json      # kayit.json'u şifreleyip site_data'ya yazar

JSON biçimi:
    {"borclar":  [{"ad": "Ziraat taşıt kredisi", "vade": "aylık 5'i", "tutar": 120000}],
     "vergiler": [{"ad": "Emlak vergisi 2. taksit", "vade": "2026-11-30", "tutar": 18500,
                   "odendi": false}]}
Vergilerde vade YYYY-AA-GG olmalı; o ayın "ödemeler" tablosuna girer.
Yönetim parolası değişirse bu dosya da yeni parolayla yeniden yazılmalı (goster → yaz).
"""
import json
import os
import sys
from pathlib import Path

import dashcrypto
from elektra_api import load_env

DOSYA = Path(__file__).resolve().parent / "site_data" / "elle.enc.json"


def parola():
    env = {**load_env(), **os.environ}
    pw = (env.get("DASH_PW_MANAGER") or env.get("DASH_PASSWORD") or "").strip()
    if not pw:
        sys.exit("DASH_PW_MANAGER yok (.env)")
    return pw


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("goster", "yaz"):
        sys.exit(__doc__)
    if sys.argv[1] == "goster":
        if not DOSYA.exists():
            print(json.dumps({"borclar": [], "vergiler": []}, ensure_ascii=False, indent=2))
            return
        print(dashcrypto.decrypt_multi(json.loads(DOSYA.read_text()), parola()))
        return
    veri = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    for k in ("borclar", "vergiler"):
        veri.setdefault(k, [])
    DOSYA.parent.mkdir(parents=True, exist_ok=True)
    DOSYA.write_text(json.dumps(dashcrypto.encrypt_multi(
        json.dumps(veri, ensure_ascii=False), [parola()])), encoding="utf-8")
    print(f"{DOSYA} yazıldı: {len(veri['borclar'])} borç, {len(veri['vergiler'])} vergi")


if __name__ == "__main__":
    main()
