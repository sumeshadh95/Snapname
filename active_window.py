from __future__ import annotations

import ctypes
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from ctypes import wintypes

LOGGER = logging.getLogger(__name__)
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_CHAT_APPS = {"chatgpt", "codex", "claude", "gemini", "copilot"}

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
    "chatgpt": "chatgpt",
    "openai": "chatgpt",
    "codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "copilot": "copilot",
}

_PROCESS_NAME_MAP = {
    "code": "vscode",
    "chrome": "chrome",
    "firefox": "firefox",
    "msedge": "edge",
    "brave": "chrome",
    "opera": "chrome",
    "powershell": "powershell",
    "pwsh": "powershell",
    "cmd": "cmd",
    "windowsterminal": "terminal",
    "explorer": "explorer",
    "chatgpt": "chatgpt",
    "codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "copilot": "copilot",
}

_TITLE_STOP_WORDS = {
    "new",
    "chat",
    "openai",
    "chatgpt",
    "google",
    "chrome",
    "microsoft",
    "edge",
    "mozilla",
    "firefox",
    "visual",
    "studio",
    "code",
    "gpt",
    "claude",
    "gemini",
    "llama",
}

_AI_MODEL_PATTERN = re.compile(
    r"\b(?P<family>gpt|claude|gemini|llama|mistral|qwen|deepseek|o[0-9])"
    r"[\s_-]?"
    r"(?P<version>[0-9]+(?:\.[0-9]+)?[a-z]?)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ActiveWindowInfo:
    raw_title: str
    app_name: str
    keywords: list[str]
    process_name: str = ""
    executable_path: str = ""


def get_active_window_title() -> str:
    """Return the title text of the currently focused window."""
    hwnd = _get_foreground_hwnd()
    return _get_window_title(hwnd)


def _get_foreground_hwnd() -> int:
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        return int(user32.GetForegroundWindow())
    except Exception:
        LOGGER.debug("Could not read active window handle", exc_info=True)
        return 0


def _get_window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
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
    hwnd = _get_foreground_hwnd()
    title = _get_window_title(hwnd)
    process_name, executable_path = _get_window_process(hwnd)
    if not title and not process_name:
        return ActiveWindowInfo(raw_title="", app_name="", keywords=[])

    app_name = _detect_app_name(title, process_name)
    keywords = _extract_title_keywords(title, app_name)

    return ActiveWindowInfo(
        raw_title=title,
        app_name=app_name,
        keywords=keywords,
        process_name=process_name,
        executable_path=executable_path,
    )


def _get_window_process(hwnd: int) -> tuple[str, str]:
    if not hwnd:
        return "", ""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == 0:
            return "", ""

        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            process_id.value,
        )
        if not handle:
            return "", ""

        try:
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            ok = kernel32.QueryFullProcessImageNameW(
                handle,
                0,
                buffer,
                ctypes.byref(size),
            )
            if not ok:
                return "", ""
            executable_path = buffer.value
            return Path(executable_path).stem.lower(), executable_path
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        LOGGER.debug("Could not read active process name", exc_info=True)
        return "", ""


def _detect_app_name(title: str, process_name: str = "") -> str:
    """Detect the application name from the window title."""
    process_key = process_name.lower().replace(" ", "")
    if process_key in _PROCESS_NAME_MAP:
        return _PROCESS_NAME_MAP[process_key]
    for process_phrase, short_name in _PROCESS_NAME_MAP.items():
        if process_phrase in process_key:
            return short_name

    lower_title = title.lower()
    for phrase, short_name in _APP_NAME_MAP.items():
        if phrase in lower_title:
            return short_name
    return ""


def _extract_title_keywords(title: str, app_name: str) -> list[str]:
    """Extract meaningful keywords from the window title."""
    keywords: list[str] = []

    if app_name in _CHAT_APPS:
        _add_model_keywords(title, keywords)
        if app_name == "chatgpt" or re.search(r"\bchat\b", title, re.I):
            _append_keyword("chat", keywords)
        _add_clean_keyword(title, keywords)
        if app_name != "chatgpt":
            _append_keyword(app_name, keywords)
        return keywords[:5]

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
        _add_model_keywords(page_title, keywords)
        if re.search(r"\b(chatgpt|openai|new\s+chat|chat)\b", page_title, re.I):
            _append_keyword("chat", keywords)
        _add_browser_keywords(page_title, keywords)
        if app_name and app_name not in keywords:
            keywords.append(app_name)
        return keywords[:5]

    # Explorer: just the folder name
    # Check if this looks like a simple folder name (no dashes/separators)
    if app_name == "explorer":
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
        if cleaned in _TITLE_STOP_WORDS:
            continue
        if cleaned and len(cleaned) > 1:
            _append_keyword(cleaned, keywords)


def _add_browser_keywords(page_title: str, keywords: list[str]) -> None:
    """Extract keywords from a browser page title."""
    # Take the most meaningful words from the page title
    words = re.findall(r"[A-Za-z0-9]+", page_title)
    stop_words = {
        "the", "and", "for", "with", "this", "that", "from", "are",
        "was", "has", "have", "you", "your", "new", "how", "what",
        "why", "when", "where", "who", "all", "not", "but", "can",
        "chatgpt", "openai",
    }
    for word in words[:6]:
        cleaned = _sanitize_keyword(word)
        if (
            cleaned
            and len(cleaned) > 2
            and cleaned not in stop_words
            and cleaned not in keywords
        ):
            _append_keyword(cleaned, keywords)
            if len(keywords) >= 3:
                break


def _add_model_keywords(text: str, keywords: list[str]) -> None:
    for match in _AI_MODEL_PATTERN.finditer(text):
        model = _normalize_model_match(match)
        if model:
            _append_keyword(model, keywords)


def _normalize_model_match(match: re.Match[str]) -> str:
    family = match.group("family").lower()
    version = (match.group("version") or "").lower()
    if family.startswith("o") and family[1:].isdigit():
        return family
    if family == "gpt" and not version:
        return ""
    if family == "gpt":
        return f"gpt{version}"
    if version:
        return f"{family}{version}"
    return family


def _append_keyword(keyword: str, keywords: list[str]) -> None:
    cleaned = _sanitize_keyword(keyword)
    if cleaned and cleaned not in keywords:
        keywords.append(cleaned)


def _sanitize_keyword(value: str) -> str:
    """Clean a value into a safe keyword string."""
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_.]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    normalized = normalized.strip(".")
    return normalized
