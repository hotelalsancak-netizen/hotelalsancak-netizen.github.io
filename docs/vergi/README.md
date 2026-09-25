# Vergi hesaplama notu

`vergi-hesaplama.html` — panodaki **Vergi Sayfası**'nın her rakamını nereden
hesapladığını anlatan belge: hangi Elektra hesap kodu, hangi formül, hangi kural.
Muhasebeciye gösterilmek üzere yazıldı.

## Neden şifreli

Bu depo **herkese açık**. Belge otelin ciro, matrah, ödenecek vergi ve geçmiş yıl
rakamlarını içeriyor. Bu yüzden içerik, panodaki bölümlerle **aynı yöntemle**
şifrelendi (PBKDF2-SHA256 200k + AES-256-GCM) ve dosyaya gömüldü.

## Nasıl açılır

Dosyayı tarayıcıda aç (çift tıkla yeter, sunucu gerekmez), **yönetim parolasını**
gir. Çözme tamamen tarayıcıda yapılır; parola dosyada saklı değildir ve hiçbir
yere gönderilmez. Resepsiyon parolası bu belgeyi **açmaz**.

## Yeniden üretmek

İçerik değişirse belgeyi yeniden şifrelemek gerekir — düz metin sürümü depoda
tutulmaz. Yönetim parolası değişirse de bu dosya yeniden üretilmelidir, yoksa
sessizce açılmaz olur (kart haftalarındaki `site_data/kart/*.enc.json` ile aynı
durum).
