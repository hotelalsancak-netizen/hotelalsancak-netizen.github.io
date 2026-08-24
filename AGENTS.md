# AGENTS.md — Riva Hotel Alsancak Dashboard

Bu dosya, bu proje üzerinde çalışacak yapay zekâ asistanı (Claude Code vb.) içindir.
Kullanıcı **Riva Hotel Alsancak'ın sahibi**, teknik değil — **Türkçe** ve **sade** yanıt ver.

## Ne bu proje
Otel sahibinin **resepsiyon kaynaklı kaçağı/hırsızlığı** kontrol etmesi için, **şifreli** ve
**otomatik güncellenen** bir web dashboard. Kilit soru: "ödeme alınmadı mı, eksik mi alındı,
boş oda satılıp cebe mi atıldı?"

- **Canlı adres:** https://hotelalsancak-netizen.github.io/  (girişte parola sorar)
- **Repo (public):** `hotelalsancak-netizen/hotelalsancak-netizen.github.io` — GitHub Pages
- **11 bölüm (tile):** `gunsonu` (Gün Sonu), `odeme` (Günlük Ödeme Kontrolü — **tarih-seçimli**
  son 7 gün giriş ödemeleri + **açık bakiye paneli** res-guest-balance-list), `kasa` (Kasa & POS
  mutabakatı — **haftalık, çok-dövizli** TL/EUR/USD, banka **xlsx yükleme**, Elektra kart↔banka
  POS T+1), `iptal` (İptal/Silinen), `indirim`, `bakiye` (Açık bakiye), `parite` (Parite Kontrolü —
  tarayıcı-içi fiyat girişi), `kart` (Haftalık Kart Güvenliği — çok-haftalı, hafta seçicili;
  güçlü/zayıf ayrımı), `stats` (Doluluk/ADR/grafikler), `satis` (Aylık satışlar), `vergi` (**Vergi Sayfası** —
  muhasebe mizanından aylık KDV + konaklama vergisi + dönemsel kurumlar/geçici vergi).

## Mimari
- **Tek yayıncı = bulut GitHub Actions** (`.github/workflows/dashboard.yml`). Her `main` push'unda
  ve günlük cron'da (TR 21:00/23:00/01:00/03:00/05:00) çalışır. Bilgisayara bağlı DEĞİL.
- `python dashboard.py --build`: Elektra'dan canlı bölümleri üretir → **şifreler** → `public/`
  yazar → Pages'e deploy. Kart bölümü `site_data/kart/` içindeki commit'li şifreli haftalardan gelir.
- **Şifreleme:** `dashcrypto.encrypt_multi` (PBKDF2-SHA256 + AES-256-GCM, `v2` çok-alıcılı).
  Yayınlanan her şey **ciphertext**; tarayıcı doğru parolayla bellekte çözer (`dashboard_shell.html`).
- **İKİ ROL:** `DASH_PW_MANAGER` (yönetim/sahip — her şeyi görür), `DASH_PW_RECEPTION`
  (resepsiyon — yalnızca `dashboard.py` içindeki `RECEPTION_SECTIONS`, şu an
  `{"gunsonu", "odeme", "bakiye"}`). Denetim sayfaları (`kart`, `iptal`, `indirim`, `kasa`,
  `parite`) ve finans sayfaları (`vergi`, `satis`, `stats`) **yönetime özeldir** — bunlar
  resepsiyon kaynaklı kaçağı yakalamak için var, resepsiyon görürse neyin yakalandığını da
  görür (sahibin kararı, 24.08.2026). Parolalar **Secrets/.env**'de; **repoda ASLA yok.**

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
Folio `TOTAL` **her zaman TL** (ana para); `CTOTAL` = **orijinal para birimi** (EUR satırında EUR).
`USERFULLNAME/CANCELUSER` ile her anomali personele bağlanır.

## Kasa & POS + Günlük Ödeme — özel notlar
- **Kasa (`checks.build_kasa`)** haftalık. Elektra kart tahsilatı **döviz-başına** (native) bloğa
  gömülür: `cardTRY`(TL), `cardEUR`/`cardUSD`(=CTOTAL). Kullanıcı banka **Hesap Hareketleri xlsx**'ini
  (TL/EUR/USD ayrı dosya) sürükle-bırak yükler. **Mutabakat tamamen tarayıcıda** (`KASA_RECON_JS`):
  xlsx `DecompressionStream('deflate-raw')` ile açılır (kütüphanesiz), "Döviz Cinsi" satırından
  para birimi tanınır; POS = `AKPOS PES ODE` (net + `KS:` komisyon = brüt), Elektra kart **T+1**
  hizalanır. Elektra verisi olmayan gün "karşılaştırma dışı" (yanıltıcı fark yok). Banka verisi
  dışarı gitmez. Ayrıntı: [[folio-banka-para-modeli]].
- **Günlük Ödeme (`checks.build_odeme`)** tarih-seçimli: son 7 günün girişleri `paycheck.classify`
  ile ayrı ayrı bloğa gömülür (JS `daySel` ile değişir) + üstte **açık bakiye paneli**.
- **`checks.open_balances(env)`** paylaşımlı helper = res-guest-balance-list (net `GENERALBALANCE>0`
  ve `GUESTBALANCE>0`, konaklayan + son 180g çıkış). Hem `build_bakiye` hem `build_odeme` kullanır.

## Vergi Sayfası — özel notlar
- Kaynak **fatura listesi değil, MUHASEBE MİZANI**: `elektra_api.fetch_trial_balance` →
  `Execute/SP_EASYPMS_ACCOUNT_TRIALBALANCE4` (grid `acctrialbalance4`'ün arkasındaki proc,
  parametreler `FROMDATE/TODATE/FROMCODE/TOCODE/LNG/LEVEL`). Mizanda muhasebecinin işlediği
  **her şey** var (fatura + elden fiş + bordro + banka); fatura listesi bordroyu görmez.
- `checks.build_vergi` cari yılın **her ayı için bir mizan** çeker (+1 tane yıl başı–bugün),
  ~12 çağrı / ~15 sn. Tek düzen hesap planı **2 haneli GRUP** bazında okunur; grup kendi
  yansıtma hesabını netler (74 = 740 − 741), böylece gider iki kez sayılmaz:
  60/64/67 gelir · 61 satış iadesi (gelirden düş) · 62/63/65/66/68 + 7x gider · 689 K.K.E.G.
  (gidere girer, **matraha geri eklenir**).
- **KDV'de tek taraf alınır**: hesaplanan = `391` ALACAK, indirilecek = `191` BORÇ. Sebep:
  muhasebeci ay sonu kapanış fişi atıyor (391 borç / 191 alacak / 360 alacak); net alırsak
  kapanış kendi kendini götürür ve ay sıfırlanır. `191.03` = sorumlu sıfatıyla (KDV-2) dâhil.
- **Konaklama vergisi** = `360` altındaki "KONAKLAMA" yaprak hesabının **ALACAĞI** (tahakkuk).
  Net alınırsa o ay yapılan ödeme (borç) düşülüp eksiye döner.
- **YALNIZCA CARİ YIL** hesaplanır: kapanmış yılda 690/691/692 kapanış fişleri gelir/gider
  hesaplarının borcunu alacağına eşitler, o yüzden geçmiş yıl bu yöntemle hesaplanamaz.
- Kurumlar vergisi **tahminidir** — amortisman/kıdem/enflasyon düzeltmesi genelde yıl sonunda
  işlenir. Geçici vergi dönemleri kümülatif, 4. dönem 2024'te kaldırıldı. Oran `KV_RATE=0.25`.
- Sayfada **tarayıcı-içi düzeltme** kartı var (`VERGI_ADJUST_HTML`): yıl başı devreden KDV +
  Elektra'ya henüz girilmemiş fişler; localStorage (`riva_vergi_v1`), sunucuya hiçbir şey gitmez.

## Kart (haftalık) — özel notlar
- Kapı kilidi dökümleri **~2 aylık geçmiş** tutar; hafta veriden değil **export tarihinden** belirlenir.
- `build_report.build(cards, changes, occ, lo, hi)` haftaya göre **parametreli**.
- **Oda Değişimi (room changes)** — taşınan misafirlerin yanlışlıkla "şüpheli" görünmesini önler. Çok kritik:
  gerçek veri gelince 13-19 haftası **29 → 3 şüpheliye** düştü (26'sı taşınan misafirdi).
  - ✅ **OTOMATİK (Elektra'dan çekiliyor):** `elektra_api.fetch_room_changes(frm,to)` → view **`Q_HOTELROOMCHANGE`**
    (Oda Değişimi raporu `/app/grid/room-changerapor`'un arkasındaki tablo). Kolonlar: `RCDATE` (tarih),
    `ROOMNO_FIRSTROOMID` (ilk oda), `ROOMNO_LASTROOMID` (son oda), `GUESTNAMES`, `USERCODE`, `RESID`.
    `kart_yukle.py` oda değişimini **önce buradan** çeker — elle export GEREKMEZ.
  - Endpoint nasıl bulundu (başka rapor lazım olursa aynı yöntem): `GetConfig/menu` → grid `id`'sini bul
    (ör. Room Change → `room-changerapor`), sonra `GetConfig/grid.<id>.config` → arkadaki `Object`. Body:
    `{"Action":"GetConfig","ConfigName":"<name>","LoginToken":...}`. Elektra "izin yok"/"nesne yok" için aynı 403'ü döner.
  - **Yedek yollar** (Elektra çekilemezse): zip'in içinde/yanında Excel/CSV/JSON export ararsa kullanır
    (Türkçe başlık esnek eşleme: Tarih/Misafir/Eski Oda/Yeni Oda/Rez No; Excel için `pip install openpyxl`),
    o da yoksa `room_changes.json`, o da yoksa rapora uyarı. Hedef format: `{when,guest,from_room,to_room,rez_id}`.
