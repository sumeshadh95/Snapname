from __future__ import annotations

import ctypes
import logging
import re
from dataclasses import dataclass

LOGGER = logging.getLogger(__name__)

# Window title patterns for known applications
_EXPLORER_PATTERNS = [
    # Explorer shows just the folder name as the title
    re.compile(r"^(?P<folder>[^\\/:*?\"<>|]+)$"),
]

_VSCODE_PATTERN = re.compile(
    r"^(?P<file>[^\u2014\u2013–—]+?)\s*[\u2014\u2013–—-]\s*(?P<project>[^\u2014\u2013–—]+?)\s*[\u2014\u2013–—-]\s*Visual Studio Code",
    re.IGNORECASE,
)

_BROWSER_PATTERN = re.compile(
    r"^(?P<title>.+?)\s*[\u2014\u2013–—-]\s*(?:Google Chrome|Mozilla Firefox|Microsoft Edge|Brave|Opera)",
    re.IGNORECASE,
)

_GENERIC_TITLE_PATTERN = re.compile(
    r"^(?P<content>.+?)\s*[\u2014\u2013–—-]\s*(?P<app>[A-Za-z][\w\s.]+)$"
)

# Map of known process-like app names found in title bars
_APP_NAME_MAP = {
    "visual studio code": "vscode",
    "vs code": "vscode",
    "code": "vscode",
    "google chrome": "chrome",
    "mozilla firefox": "firefox",
    "microsoft edge": "edge",
    "windows powershell": "powershell",
    "command prompt": "cmd",
    "windows terminal": "terminal",
    "pycharm": "pycharm",
    "intellij idea": "intellij",
    "notepad++": "notepad_plus",
    "notepad": "notepad",
    "sublime text": "sublime",
    "file explorer": "explorer",
}


@dataclass(frozen=True)
class ActiveWindowInfo:
    raw_title: str
    app_name: str
    keywords: list[str]


def get_active_window_title() -> str:
    """Return the title text of the currently focused window."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        return buffer.value
    except Exception:
        LOGGER.debug("Could not read active window title", exc_info=True)
        return ""


def get_active_window_info() -> ActiveWindowInfo:
    """Capture the active window title and extract contextual keywords."""
    title = get_active_window_title()
    if not title:
        return ActiveWindowInfo(raw_title="", app_name="", keywords=[])

    app_name = _detect_app_name(title)
    keywords = _extract_title_keywords(title, app_name)

    return ActiveWindowInfo(
        raw_title=title, app_name=app_name, keywords=keywords
    )


def _detect_app_name(title: str) -> str:
    """Detect the application name from the window title."""
    lower_title = title.lower()
    for phrase, short_name in _APP_NAME_MAP.items():
        if phrase in lower_title:
            return short_name
    return ""


def _extract_title_keywords(title: str, app_name: str) -> list[str]:
    """Extract meaningful keywords from the window title."""
    keywords: list[str] = []

    # VS Code: "filename.py — project — Visual Studio Code"
    vscode_match = _VSCODE_PATTERN.match(title)
    if vscode_match:
        file_part = vscode_match.group("file").strip()
        project_part = vscode_match.group("project").strip()
        _add_file_keyword(file_part, keywords)
        _add_clean_keyword(project_part, keywords)
        if app_name and app_name not in keywords:
            keywords.append(app_name)
        return keywords[:5]

    # Browser: "Page Title — Google Chrome"
    browser_match = _BROWSER_PATTERN.match(title)
    if browser_match:
        page_title = browser_match.group("title").strip()
        _add_browser_keywords(page_title, keywords)
        if app_name and app_name not in keywords:
            keywords.append(app_name)
        return keywords[:5]

    # Explorer: just the folder name
    # Check if this looks like a simple folder name (no dashes/separators)
    if app_name == "explorer" or (
        app_name == ""
        and not any(sep in title for sep in ["—", "–", " - "])
        and len(title.split()) <= 3
    ):
        folder_name = _sanitize_keyword(title.strip())
        if folder_name:
            keywords.append(folder_name)
            keywords.append("folder")
        return keywords[:5]

    # Generic "Content — App Name"
    generic_match = _GENERIC_TITLE_PATTERN.match(title)
    if generic_match:
        content = generic_match.group("content").strip()
        _add_clean_keyword(content, keywords)
        if app_name and app_name not in keywords:
            keywords.append(app_name)
        return keywords[:5]

    # Last resort: just use cleaned title words
    _add_clean_keyword(title, keywords)
    if app_name and app_name not in keywords:
        keywords.append(app_name)
    return keywords[:5]


def _add_file_keyword(file_part: str, keywords: list[str]) -> None:
    """Extract a keyword from a filename (strip extension)."""
    # Could be "main.py" or "settings.json" etc.
    if "." in file_part:
        stem = file_part.rsplit(".", 1)[0]
    else:
        stem = file_part
    cleaned = _sanitize_keyword(stem)
    if cleaned and cleaned not in keywords:
        keywords.append(cleaned)


def _add_clean_keyword(text: str, keywords: list[str]) -> None:
    """Add cleaned words from text as keywords."""
    words = re.findall(r"[A-Za-z0-9]+", text)
    for word in words[:3]:
        cleaned = _sanitize_keyword(word)
        if cleaned and len(cleaned) > 1 and cleaned not in keywords:
            keywords.append(cleaned)


def _add_browser_keywords(page_title: str, keywords: list[str]) -> None:
    """Extract keywords from a browser page title."""
    # Take the most meaningful words from the page title
    words = re.findall(r"[A-Za-z0-9]+", page_title)
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "are",
        "was", "has", "have", "you", "your", "new", "how", "what",
        "why", "when", "where", "who", "all", "not", "but", "can",
    }
    for word in words[:6]:
        cleaned = _sanitize_keyword(word)
        if (
            cleaned
            and len(cleaned) > 2
            and cleaned not in stop_words
            and cleaned not in keywords
        ):
            keywords.append(cleaned)
            if len(keywords) >= 3:
                break


def _sanitize_keyword(value: str) -> str:
    """Clean a value into a safe keyword string."""
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized
