# AGENTS.md — Riva Hotel Alsancak Dashboard

Bu dosya, bu proje üzerinde çalışacak yapay zekâ asistanı (Claude Code vb.) içindir.
Kullanıcı **Riva Hotel Alsancak'ın sahibi**, teknik değil — **Türkçe** ve **sade** yanıt ver.

## Ne bu proje
Otel sahibinin **resepsiyon kaynaklı kaçağı/hırsızlığı** kontrol etmesi için, **şifreli** ve
**otomatik güncellenen** bir web dashboard. Kilit soru: "ödeme alınmadı mı, eksik mi alındı,
boş oda satılıp cebe mi atıldı?"

- **Canlı adres:** https://hotelalsancak-netizen.github.io/  (girişte parola sorar)
- **Repo (public):** `hotelalsancak-netizen/hotelalsancak-netizen.github.io` — GitHub Pages
- **9 bölüm (tile):** `gunsonu` (Gün Sonu), `odeme` (Dünün Ödemesi), `kasa` (Kasa & POS
  mutabakatı), `iptal` (İptal/Silinen), `indirim`, `bakiye` (Açık bakiye), `kart` (Haftalık
  Kart Güvenliği — çok-haftalı, hafta seçicili), `stats` (Doluluk/ADR/grafikler),
  `satis` (Aylık satışlar).

## Mimari
- **Tek yayıncı = bulut GitHub Actions** (`.github/workflows/dashboard.yml`). Her `main` push'unda
  ve günlük cron'da (TR 21:00/23:00/01:00/03:00/05:00) çalışır. Bilgisayara bağlı DEĞİL.
- `python dashboard.py --build`: Elektra'dan canlı bölümleri üretir → **şifreler** → `public/`
  yazar → Pages'e deploy. Kart bölümü `site_data/kart/` içindeki commit'li şifreli haftalardan gelir.
- **Şifreleme:** `dashcrypto.encrypt_multi` (PBKDF2-SHA256 + AES-256-GCM, `v2` çok-alıcılı).
  Yayınlanan her şey **ciphertext**; tarayıcı doğru parolayla bellekte çözer (`dashboard_shell.html`).
- **İKİ ROL:** `DASH_PW_MANAGER` (yönetim — her şeyi görür), `DASH_PW_RECEPTION` (resepsiyon —
  yalnızca `dashboard.py` içindeki `RECEPTION_SECTIONS`, şu an `{"gunsonu"}`). Kart yönetim-only.
  Parolalar **Secrets/.env**'de; **repoda ASLA yok.**

## Dosyalar
**Repoda (public, bulut derlemesi kullanır):** `dashboard.py`, `checks.py`, `dashcrypto.py`,
`elektra_api.py`, `nightaudit.py`, `paycheck.py`, `audit.py`, `dashboard_shell.html`,
`requirements.txt`, `.github/workflows/dashboard.yml`, `site_data/kart/*.enc.json` + `index.json`
(hepsi şifreli/PII'siz — güvenli).

**YALNIZCA YEREL — `.gitignore`'da, public repoya ASLA girmez** (kimlik/PII):
`.env`, `cards.json`, `occupancy.json`, `room_changes.json`, `cardreads/`, `build_report.py`,
`analyze.py`, `parse_cards.py`, `kart_yukle.py`, `room_changes.py`, `discover/`, `testdata/`,
`report.*`, `public/`.

> ⚠️ **YENİ MAKİNE:** Yerel dosyalar `git clone` ile GELMEZ. Çalışmak için **tüm proje klasörünü**
> kopyala (USB/Drive) — özellikle `.env` (parolalar + Elektra bilgileri + GITHUB_TOKEN) ve kart
> araçları olmadan hiçbir şey çalışmaz.

## Kurulum (yeni bilgisayarda)
1. Python 3.11+ ve `pip install -r requirements.txt` (requests, cryptography).
2. Kart raporu için `pdftotext`: macOS `brew install poppler`, Linux `apt install poppler-utils`.
3. `.env` mevcut olmalı: `ELEKTRA_URL/HOTELID/USER/PASS`, `DASH_PW_MANAGER`, `DASH_PW_RECEPTION`,
   `GITHUB_TOKEN`. (Değerleri bu dosyada YAZMA — .env'de dururlar.)
4. Her komuttan önce ortamı yükle: `set -a; source .env; set +a`

## Sık işlemler
- **Dashboard güncelle:** otomatik (cron + her push). Elle test: `python3 dashboard.py --build`
  (yerelde `public/` üretir; canlıya gitmesi için commit + `git push`).
- **Haftalık kart yükle** (resepsiyon PC'sindeki zip'ten): `python3 kart_yukle.py "<hafta.zip>"`
  → zip'i açar, PDF'leri çözer, haftayı **dosya adındaki tarihten** belirler (biten hafta), Elektra'dan
  doluluğu çeker, raporu üretir, **yönetim parolasıyla** şifreler, `site_data/kart/`'a yazar, push + deploy.
  Seçenekler: `--week YYYY-MM-DD` (haftayı elle ver), `--no-publish` (sadece yerel).
- **Parola değiştir:** `.env` güncelle → GitHub Secret güncelle (`gh secret set DASH_PW_MANAGER ...`)
  → kart bloklarını yeniden üret (parola değişince eski bloklar açılmaz!) → push (bulut canlı
  bölümleri yeni parolayla yeniden şifreler).
- **Yeni liste ekle:** `checks.py`'de `build_<ad>(env)` yaz (bölüm dict döndürür:
  `{label,count,count_label,tone,sub,updated,html}`), sonra `dashboard.py`'de `live` tuple'ına +
  `SECTION_ORDER`'a `<ad>` ekle. Resepsiyonun da görmesini istersen `RECEPTION_SECTIONS`'a ekle.
  Grafik gerekiyorsa `checks.py`'deki `svg_bars/svg_line/svg_donut/svg_hbars` (harici kütüphane yok).

## Git — DİKKAT (paralel oturumlar)
Bu repoya **başka Claude oturumları da push edebiliyor** (kullanıcı birden çok makine/oturum kullanıyor).
- Push'tan **ÖNCE `git fetch`** + karşılaştır. Reddedilirse (non-fast-forward) **körlemesine
  force-push YOK** — gelen commit'i `git show` ile incele, kendi işini onun **üstüne** yeniden uygula,
  kullanıcıya bildir.
- Commit mesajları Türkçe.

## Güvenlik / KVKK
- Panel **misafir verisi (PII)** içerir. Public repoya **ASLA:** `.env`, `cards.json`,
  `occupancy.json`, `room_changes.json`, `cardreads/`, veya **yorumlarında isim geçen** yerel kod.
  Yeni kod eklerken PII taraması yap.
- Parola/token repoda olmamalı. Güvenlik **şifrelemeye** dayanır (parola), gizli adrese değil.

## Veri kaynağı (Elektra PMS)
`elektra_api.py` — `Select/QA_HOTEL_RESERVATION`, `QA_HOTEL_FOLIO`, `Function/FN_ROOMCALENDAR_BASIC`.
Önemli: fiyatlar **çok para birimli**; TL için `MCTOTALPRICE` (ana para) kullan. Doluluk = **room
calendar'dan fiziksel (numerik) oda**, iptal/silinen + sanal tur odaları hariç, tekilleştirilmiş;
bugünün doluluğuna **gelmemiş rezervasyonlar da** dahil (Elektra ile birebir). `ROOMS_TOTAL=55`.
Folio `TOTAL` alanı **TL**'ye çevrilmiştir (kasa/POS mutabakatı bununla). `USERFULLNAME/CANCELUSER`
ile her anomali personele bağlanır.

## Kart (haftalık) — özel notlar
- Kapı kilidi dökümleri **~2 aylık geçmiş** tutar; hafta veriden değil **export tarihinden** belirlenir.
- `build_report.build(cards, changes, occ, lo, hi)` haftaya göre **parametreli**.
- **Oda Değişimi (room changes)** — taşınan misafirlerin yanlışlıkla "şüpheli" görünmesini önler.
  - Elektra'nın "Oda Değişimi" raporunun **doğrudan API endpoint'i tespit edilemedi** (admin erişimi VAR
    ama nesne adı Elektra'nın lazy-yüklenen kodunda; QA_/HOTEL_/FN_ kör tahminleri hep 403; SP_EASYPMS_
    SWAPROOM/ASSIGNROOM taşımayı *yapar*, raporlamaz). Otomatik çekmek istenirse endpoint'i **bir kez
    yakala**: `python3 discover.py --headed` ile giriş yapıp "Oda Değişimi" raporunu aç → `discover/requests.jsonl`
    içindeki `Object` adını bul → `elektra_api.py`'ye `fetch_room_changes(frm,to)` olarak göm.
  - **Şu an ÇALIŞAN yol:** `kart_yukle.py`, "Oda Değişimi" export'unu (Elektra → Excel/CSV/JSON) zip'in
    İÇİNDE veya YANINDA otomatik bulur (harf-duyarsız), **Türkçe başlıkları esnek eşler**
    (Tarih/Saat, Misafir, Eski Oda, Yeni Oda, Rez No) ve analize katar. Excel için `pip install openpyxl`.
    Bulunamazsa `room_changes.json`'a düşer, o da yoksa rapora uyarı. Hedef format:
    `{when,guest,from_room,to_room,rez_id}`.
