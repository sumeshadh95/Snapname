@echo off
setlocal
cd /d "%~dp0"

echo Building SnapName.exe...
python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name SnapName ^
  --icon assets\icon.ico ^
  --add-data "assets\icon.ico;assets" ^
  --hidden-import plyer.platforms.win.notification ^
  --hidden-import active_window ^
  main.py

if errorlevel 1 (
  echo Build failed.
  exit /b 1
)

echo Done. Your executable is dist\SnapName.exe
