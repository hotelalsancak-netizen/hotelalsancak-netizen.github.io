@echo off
title KART PROGRAMI GUNCELLEME
rem 18.11.2026 - KartKayitGondere TAM EKRAN sonuc penceresi ekler.
rem Cift tiklayin. Yeni iki dosyayi GitHubdan indirir, programi yeniden derler,
rem sonra /test ile dener. cardreads_upload.py (gizli anahtarlar) DEGISMEZ.
echo.
echo ==============================================================
echo    KART PROGRAMI GUNCELLENIYOR - lutfen bekleyin (1-3 dakika)
echo ==============================================================
echo.
if not exist "C:\OdaKartOku\src\cardreads_upload.py" (
  echo HATA: C:\OdaKartOku\src\cardreads_upload.py bulunamadi.
  echo Bu dosya bu bilgisayarda calismiyor olabilir. Yoneticiye haber verin.
  pause
  exit /b 1
)
cd /d C:\OdaKartOku\src
set BASE=https://raw.githubusercontent.com/hotelalsancak-netizen/hotelalsancak-netizen.github.io/main/kart-okuyucu/src
echo [1/4] Yedek aliniyor...
copy /y kart_kayit_gonder.py kart_kayit_gonder.py.yedek >nul
copy /y C:\OdaKartOku\KartKayitGonder.exe C:\OdaKartOku\KartKayitGonder.exe.yedek >nul
echo [2/4] Yeni dosyalar indiriliyor...
curl.exe -fsSL -o kart_kayit_gonder.py.yeni "%BASE%/kart_kayit_gonder.py" || goto indirmehata
curl.exe -fsSL -o sonuc_ekrani.py.yeni "%BASE%/sonuc_ekrani.py" || goto indirmehata
move /y kart_kayit_gonder.py.yeni kart_kayit_gonder.py >nul
move /y sonuc_ekrani.py.yeni sonuc_ekrani.py >nul
echo [3/4] Program derleniyor...
call derle.bat
findstr /c:"EXITCODE=0" derle.log >nul || goto derlemehata
if not exist C:\OdaKartOku\KartKayitGonder.exe goto derlemehata
echo [4/4] Test calistiriliyor - ekran YESIL "TEST TAMAM" olmali...
C:\OdaKartOku\KartKayitGonder.exe /test
exit /b 0

:indirmehata
echo.
echo HATA: Dosyalar indirilemedi (internet?). Hicbir sey degismedi.
del /q kart_kayit_gonder.py.yeni sonuc_ekrani.py.yeni 2>nul
pause
exit /b 2

:derlemehata
echo.
echo HATA: Derleme basarisiz. ESKI program geri yukleniyor...
copy /y kart_kayit_gonder.py.yedek kart_kayit_gonder.py >nul
copy /y C:\OdaKartOku\KartKayitGonder.exe.yedek C:\OdaKartOku\KartKayitGonder.exe >nul
echo Eski program geri yuklendi, eskisi gibi calisir.
echo C:\OdaKartOku\src\derle.log dosyasinin fotografini yoneticiye gonderin.
pause
exit /b 3
