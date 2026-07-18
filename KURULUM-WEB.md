# Web'de gizli link kurulumu (ücretsiz, bulutta)

Amaç: resepsiyonun **tek bir linke** bakıp gün sonu durumunu görmesi. Rapor bu
bilgisayarda değil, **GitHub'ın bulutunda** üretilir — bu PC kapalıyken de çalışır.

> ⚠️ **Gizlilik / KVKK:** Bu link girişsizdir; adresi bilen misafir verisini görür.
> Adresteki gizli anahtarı (SITE_TOKEN) kimseyle paylaşmayın, sızarsa değiştirin.
> Girişe (Cloudflare Access) yükseltmek isterseniz söyleyin — yine ücretsiz.

## Bir kez kurulum (~15 dk)

### 1. Ücretsiz GitHub hesabı
github.com → **Sign up**.

### 2. Yeni depo (repository) oluşturun
- Sağ üst **+** → **New repository**.
- İsim: `riva-gunsonu` (fark etmez). **Public** seçin (ücretsiz Pages için gerekir).
- **Create repository**.

### 3. Proje dosyalarını yükleyin
Depo sayfasında **Add file → Upload files**. Şu dosyaları sürükleyin:
`publish_web.py`, `nightaudit.py`, `audit.py`, `paycheck.py`, `elektra_api.py`
ve `.github/workflows/gunsonu.yml` (klasör yapısıyla birlikte).
`.env`, `gizli.py` gibi şifre içeren dosyaları **YÜKLEMEYİN**. **Commit changes**.

### 4. Gizli bilgileri (Secrets) girin
Depo → **Settings → Secrets and variables → Actions → New repository secret**.
Şu dördünü tek tek ekleyin:

| İsim | Değer |
|---|---|
| `ELEKTRA_HOTELID` | `29481` |
| `ELEKTRA_USER` | **salt-okunur API kullanıcısı** |
| `ELEKTRA_PASS` | o kullanıcının şifresi |
| `SITE_TOKEN` | tahmin edilemez bir metin, örn. `k7f2p9x4qm3r8t1v` (kendiniz uydurun) |

> Şifre burada **şifreli** saklanır, kimse (siz bile) tekrar göremez — exe'ye gömmekten
> daha güvenli. Yine de **yönetici değil, salt-okunur API kullanıcısı** kullanın.

### 5. Pages'i açın
Depo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.

### 6. İlk raporu üretin
Depo → **Actions → "Gün Sonu Raporu" → Run workflow**.
Bir-iki dakikada yeşil tik gelir.

### 7. Linkiniz
Adres şu olur:
```
https://<KULLANICI-ADINIZ>.github.io/riva-gunsonu/<SITE_TOKEN>/
```
Örn. kullanıcı `rivaotel`, token `k7f2p9x4qm3r8t1v` ise:
`https://rivaotel.github.io/riva-gunsonu/k7f2p9x4qm3r8t1v/`

Bu linki resepsiyona verin / yer imine ekleyin. **Kökü** (`.../riva-gunsonu/`) açan
boş sayfa görür — sadece token'lı adres raporu gösterir.

## Ne sıklıkta güncellenir?
`gunsonu.yml` içindeki `cron` satırı belirler. Şu an TR saatiyle
**21:00 / 23:00 / 01:00 / 03:00 / 05:00**. Değiştirmek için o satırı düzenleyin
(saatler UTC; Türkiye = UTC+3).

## Sorun olursa
Actions sekmesinde kırmızı çalışma → tıklayın, log'a bakın. En sık: bir Secret eksik
ya da yanlış. Elle tekrar denemek için yine **Run workflow**.
