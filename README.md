# SnapName

Your screenshots, finally named like a human wrote them.

SnapName is a Windows 10/11 tray app for students who collect screenshots while documenting technical projects. It watches your screenshots folder, reads each new image locally, generates a meaningful filename, renames the file safely, and records every rename in a local SQLite history database.

## What It Does

- Watches your chosen screenshot folder in the background.
- Uses local Tesseract OCR by default.
- Extracts commands, errors, app names, file names, and technical keywords.
- Optionally uses local Ollama with LLaVA for richer image understanding.
- Never overwrites existing files. Duplicate names become `_2`, `_3`, and so on.
- Falls back to timestamp filenames when confidence is low.
- Lets you pause, resume, configure settings, view history, and undo renames from the tray.

## Prerequisites

1. Install Python 3.10 or newer for development.
2. Install Tesseract 5 for Windows from [UB Mannheim's Tesseract builds](https://github.com/UB-Mannheim/tesseract/wiki).
3. During Tesseract setup, enable the option that adds Tesseract to PATH. If you skip that option, add the install folder, usually `C:\Program Files\Tesseract-OCR`, to PATH manually.

Tesseract is required on the end user's machine even when running the packaged EXE. All screenshot processing stays local.

## Install For Development

Open PowerShell in the `snapname` folder:

```powershell
pip install -r requirements.txt
python -m nltk.downloader stopwords punkt punkt_tab averaged_perceptron_tagger averaged_perceptron_tagger_eng
```

The prompt only needs `stopwords` and `punkt` for the baseline setup, but the tagger packages improve noun phrase fallback names. Newer NLTK versions may also require `punkt_tab` and `averaged_perceptron_tagger_eng`.

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
- Engine: Tesseract or LLaVA
- OCR confidence threshold

Settings are saved to `settings.json` beside the app.

## Build The EXE

From the `snapname` folder:

```powershell
.\build.bat
```

The packaged app is created at:

```text
dist\SnapName.exe
```

Copy the EXE wherever you want to run it. Keep Tesseract installed on the machine.

## Optional LLaVA

LLaVA runs locally through Ollama.

1. Install Ollama from [ollama.com](https://ollama.com).
2. Pull the local model:

```powershell
ollama pull llava
```

3. Open SnapName Settings and switch the engine to `LLaVA`.

If Ollama is not running or the model is unavailable, SnapName falls back to Tesseract and logs the issue.

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

If screenshots are renamed as `screenshot_YYYYMMDD_HHMMSS.png`, OCR confidence is below your threshold or Tesseract is unavailable. Check `snapname.log`, then verify that Tesseract is installed and available from PowerShell:

```powershell
tesseract --version
```

If the tray icon says Tesseract is missing, install Tesseract or repair PATH, then quit and restart SnapName.

## Privacy

SnapName does not upload screenshots. Tesseract OCR, NLTK keyword extraction, SQLite history, and optional Ollama/LLaVA processing all run on your computer.
