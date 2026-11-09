# Kart Okuyucu (resepsiyon) — kaynak kod

Resepsiyon bilgisayarındaki **KartKayitGonder** programının kaynağı (C:\OdaKartOku). Kale Kilit'ten
odaların kilit kayıtlarını okur, PDF yapar, **55 odanın hepsi alınmadıysa göndermez** (`odalar.txt`),
ZIP'i şifreleyip `site_data/cardreads-incoming/<HAFTA>.zip.enc` olarak bu repoya yükler. Ayrıntı: `OKUBENI.txt`.

**Gizli değerler bu kopyada BOŞTUR** (repo herkese açık): `src/cardreads_upload.py` içindeki
`GITHUB_TOKEN` ve `CARD_ZIP_PASSWORD`, `src/dogrula_indir.py` içindeki `CARD_ZIP_PASSWORD`,
`src/OdaKartOku.cs` içindeki `_sifre` (Kale Kilit operatör şifresi). Yeniden derlerken bu değerleri
resepsiyondaki çalışan kopyadan alın; dolu hâliyle buraya **commit etmeyin**. `CARD_ZIP_PASSWORD`,
sunucudaki GitHub Secret ile birebir aynı olmalı.

.exe dosyaları, `build/` klasörü ve `log/` (işlem günlüğü) bilerek repoya alınmadı.
