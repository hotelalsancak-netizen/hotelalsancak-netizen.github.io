@echo off
REM Windows'ta bir kez calistirin -> dist\GunSonuKontrol.exe olusur.
REM Bu tek dosyayi (istege bagli ayarlar.ini ile) resepsiyon bilgisayarina kopyalayin.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)

echo [1/2] Gerekli paketler kuruluyor...
%PY% -m pip install --quiet --disable-pip-version-check requests pyinstaller || goto :err

echo [2/2] EXE olusturuluyor...
REM Yerel modullerimiz kismen fonksiyon icinde import edildiginden hidden-import ile
REM garantiye aliyoruz. gizli.py varsa gomulur; yoksa uygulama giris sorar.
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name GunSonuKontrol ^
  --hidden-import elektra_api ^
  --hidden-import paycheck ^
  --hidden-import audit ^
  --hidden-import nightaudit ^
  --hidden-import gizli ^
  gunsonu_app.py || goto :err

echo.
echo TAMAM. Uygulama: dist\GunSonuKontrol.exe
echo Ilk acilista Otel Kodu / Kullanici / Sifre girip Kaydet'e basin.
pause
exit /b 0

:err
echo.
echo HATA: derleme basarisiz. Python 3 kurulu mu ve internet var mi?
pause
exit /b 1
