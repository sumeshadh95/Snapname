@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=python"
if exist "%~dp0.venv\Scripts\python.exe" set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

echo Building SnapName.exe...
"%PYTHON_EXE%" -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name SnapName ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --add-data "tesseract_engine;tesseract_engine" ^
  --exclude-module nltk ^
  --exclude-module requests ^
  --hidden-import plyer.platforms.win.notification ^
  --hidden-import active_window ^
  main.py

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo Verifying embedded OCR...
start /wait "" "%~dp0dist\SnapName.exe" --self-test
if errorlevel 1 (
  echo Embedded OCR self-test failed. Check snapname.log for details.
  exit /b 1
)

echo Creating portable release zip...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\SnapName.exe' -DestinationPath 'dist\SnapName-portable.zip' -Force"
if errorlevel 1 (
  echo Zip packaging failed.
  exit /b 1
)

echo Done. Your executable is dist\SnapName.exe
echo Release zip is dist\SnapName-portable.zip
