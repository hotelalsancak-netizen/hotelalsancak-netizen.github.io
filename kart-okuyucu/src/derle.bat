@echo off
set PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe
"%PY%" -m PyInstaller --onefile --clean --noconfirm ^
  --name KartKayitGonder ^
  --add-binary "C:\OdaKartOku\OdaKartOku.exe;." ^
  --paths "C:\OdaKartOku\src" ^
  --distpath "C:\OdaKartOku" ^
  --workpath "C:\OdaKartOku\build" ^
  --specpath "C:\OdaKartOku\build" ^
  "C:\OdaKartOku\src\kart_kayit_gonder.py" > "C:\OdaKartOku\src\derle.log" 2>&1
echo EXITCODE=%ERRORLEVEL% >> "C:\OdaKartOku\src\derle.log"
