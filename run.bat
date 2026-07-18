@echo off
REM Riva Gun Sonu Kontrol - Python ile calistir (exe olmadan).
REM Ilk kullanimda: python.org'dan Python 3 kurun (kurulumda "Add to PATH" isaretli).
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py) || (set PY=python)
%PY% -m pip install --quiet --disable-pip-version-check requests
%PY% gunsonu_app.py
if errorlevel 1 (
  echo.
  echo Bir hata olustu. Ayrinti icin hata.log dosyasina bakin.
  pause
)
