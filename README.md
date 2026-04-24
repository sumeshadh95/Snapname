# SnapName

Your screenshots, finally named like a human wrote them.

SnapName is a Windows 10/11 tray app for students who collect screenshots while documenting technical projects. It watches your screenshots folder, reads each new image locally, generates a meaningful filename, renames the file safely, and records every rename in a local SQLite history database.

## What It Does

- Watches your chosen screenshot folder in the background.
- Uses Win32 foreground-window metadata plus local Tesseract OCR.
- Extracts app names, chat/model labels, commands, errors, file names, and technical keywords.
- Never overwrites existing files. Duplicate names become `_2`, `_3`, and so on.
- Falls back to timestamp filenames only when no useful window or OCR context is found.
- Lets you pause, resume, configure settings, view history, and undo renames from the tray.
- Includes a lightweight dashboard for setup, recent history, and live active-window diagnostics.

## Prerequisites

1. Install Python 3.10 or newer for development.
2. Keep the bundled `tesseract_engine` folder beside the source tree for development builds. The released EXE embeds the English OCR runtime, so end users do not install Tesseract.

All screenshot processing stays offline on your computer. SnapName does not use Ollama, cloud APIs, or downloaded NLTK models.

## Install For Development

Open PowerShell in the `snapname` folder:

```powershell
pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

SnapName starts in the Windows system tray. Right-click the tray icon to open settings, view rename history, pause watching, undo the last rename, or quit.

## Configure

Open Settings from the tray menu. You can change:

- Screenshot folder
- Filename prefix, such as `cs301`
- Timestamp behavior
- Offline engine: foreground window context plus Tesseract
- OCR confidence threshold

Settings are saved to `settings.json` beside the app.

## Dashboard

Open **Open Dashboard** from the tray menu to configure SnapName interactively. Closing the dashboard hides it back to the tray; screenshot watching continues in the background.

The Windows tab shows the current foreground window and visible top-level windows using direct Win32 calls. SnapName does not load pywin32, PyWinCtl, or a .NET helper process, which keeps the background memory footprint low.

## Build The EXE

From the `snapname` folder:

```powershell
.\build.bat
```

The build verifies embedded OCR and creates:

```text
dist\SnapName.exe
dist\SnapName-portable.zip
```

Copy `SnapName.exe` wherever you want to run it, or upload `SnapName-portable.zip` to a GitHub Release. The build embeds `tesseract_engine`, so the EXE can run on a machine without a separate Tesseract install.

To verify a packaged build without starting the tray app:

```powershell
.\dist\SnapName.exe --self-test
```

## Start With Windows

1. Build or locate `SnapName.exe`.
2. Press `Win + R`.
3. Type `shell:startup` and press Enter.
4. Create a shortcut to `SnapName.exe` in that folder.

SnapName will start automatically the next time you sign in.

## Files Created At Runtime

- `settings.json`: user settings
- `data\snapname.db`: rename history and undo state
- `snapname.log`: timestamped errors and operational logs

## Troubleshooting

If screenshots are renamed as `screenshot_YYYYMMDD_HHMMSS.png`, SnapName could not find useful foreground-window context and OCR also returned no useful text. Check `snapname.log`, then verify that the bundled Tesseract exists:

```powershell
.\tesseract_engine\tesseract.exe --version
```

If the tray icon says Tesseract is missing during development, restore the `tesseract_engine` folder or install Tesseract to the normal Windows location, then quit and restart SnapName. Packaged releases include the English OCR runtime inside the EXE.

## Privacy

SnapName does not upload screenshots. Foreground-window detection, Tesseract OCR, keyword extraction, and SQLite history all run on your computer.
