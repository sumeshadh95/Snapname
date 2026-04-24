from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from settings import AppSettings


LOGGER = logging.getLogger(__name__)
MAX_KEYWORDS = 4
TRUSTED_LOW_CONFIDENCE_SOURCES = {
    "active_window",
    "ai_model",
    "chat_context",
    "file_title",
    "file_language",
    "window_title",
}

COMMAND_WORDS = {
    "sudo",
    "git",
    "docker",
    "kubectl",
    "aws",
    "pip",
    "npm",
    "python",
    "java",
    "gcc",
    "curl",
    "wget",
    "ssh",
    "scp",
    "grep",
    "awk",
    "sed",
    "ls",
    "cd",
    "growpart",
    "lsblk",
    "df",
    "mount",
    "fdisk",
    "mkfs",
    "systemctl",
    "journalctl",
}

LOW_VALUE_COMMANDS = {"cd"}
COMMAND_LAUNCHERS = {"sudo"}

ERROR_KEYWORDS = {
    "failed",
    "error",
    "warning",
    "exception",
    "traceback",
    "404",
    "500",
    "denied",
    "changed",
    "success",
    "completed",
}

ERROR_CONTEXT_WORDS = {
    "cannot",
    "undefined",
    "permission",
    "timeout",
    "refused",
    "missing",
    "invalid",
    "crash",
    "fatal",
    "read",
    "property",
    "module",
    "import",
    "syntax",
}

DOMAIN_KEYWORDS = {
    "aws",
    "ec2",
    "s3",
    "docker",
    "kubernetes",
    "nginx",
    "mysql",
    "postgres",
    "postgresql",
    "react",
    "flask",
    "django",
    "ubuntu",
    "debian",
    "windows",
    "linux",
    "python",
    "java",
    "node",
    "express",
    "mongodb",
    "redis",
    "github",
    "gitlab",
    "vscode",
    "powershell",
    "terminal",
    "bash",
    "html",
    "css",
    "javascript",
    "typescript",
    "api",
    "server",
    "database",
    "disk",
    "partition",
    "volume",
    "filesystem",
    "network",
    "router",
    "vm",
    "virtualbox",
    "vmware",
    "azure",
    "gcp",
    "lambda",
    "terraform",
    "ansible",
}

APP_KEYWORDS = {
    "visual studio code": "vscode",
    "vs code": "vscode",
    "powershell": "powershell",
    "command prompt": "cmd",
    "windows terminal": "terminal",
    "terminal": "terminal",
    "chrome": "chrome",
    "firefox": "firefox",
    "edge": "edge",
    "chatgpt": "chat",
    "openai": "chat",
    "codex": "codex",
    "claude": "claude",
    "gemini": "gemini",
    "copilot": "copilot",
    "pycharm": "pycharm",
    "intellij": "intellij",
    "notepad": "notepad",
}

LANGUAGE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "react",
    ".ts": "typescript",
    ".tsx": "react",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".php": "php",
    ".rb": "ruby",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
}

FALLBACK_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "your",
    "have",
    "has",
    "are",
    "was",
    "were",
    "will",
    "shall",
    "can",
    "could",
    "would",
    "should",
    "you",
    "all",
    "not",
    "but",
    "chat",
    "new",
    "screenshot",
    "image",
    "open",
    "folder",
}

CHAT_CONTEXT_WORDS = {
    "chat",
    "newchat",
    "chatgpt",
    "claude",
    "gemini",
    "copilot",
    "openai",
    "codex",
}

AI_MODEL_PATTERN = re.compile(
    r"\b(?P<family>gpt|claude|gemini|llama|mistral|qwen|deepseek|o[0-9])"
    r"[\s_-]?"
    r"(?P<version>[0-9]+(?:\.[0-9]+)?[a-z]?)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class KeywordCandidate:
    keyword: str
    priority: int
    weight: float
    source: str
    order: int


@dataclass(frozen=True)
class KeywordResult:
    keywords: list[str]
    candidates: list[KeywordCandidate]


@dataclass(frozen=True)
class FilenameResult:
    filename: str
    used_fallback: bool
    keywords: list[str]


def extract_keywords(
    raw_text: str,
    header_text: str = "",
    active_window_title: str = "",
    active_window_keywords: list[str] | None = None,
) -> KeywordResult:
    candidates: list[KeywordCandidate] = []
    seen: set[str] = set()
    combined_text = "\n".join(part for part in (header_text, raw_text) if part)

    if active_window_keywords:
        _add_active_window_candidates(
            active_window_keywords, candidates, seen
        )
    _add_ai_model_candidates(combined_text, candidates, seen)
    _add_chat_context_candidates(combined_text, candidates, seen)
    _add_cli_candidates(raw_text, candidates, seen)
    _add_error_candidates(combined_text, candidates, seen)
    _add_header_candidates(header_text, candidates, seen)
    _add_domain_candidates(combined_text, candidates, seen)
    _add_noun_candidates(combined_text, candidates, seen)

    sorted_candidates = sorted(
        candidates,
        key=lambda candidate: (
            candidate.priority,
            -candidate.weight,
            candidate.order,
        ),
    )
    keyword_pool = sorted_candidates
    trusted_signal = [
        candidate
        for candidate in sorted_candidates
        if (
            candidate.source in TRUSTED_LOW_CONFIDENCE_SOURCES
            and candidate.priority <= 1
        )
    ]
    if (
        any(candidate.source == "ai_model" for candidate in trusted_signal)
        and any(candidate.keyword == "chat" for candidate in trusted_signal)
    ):
        keyword_pool = trusted_signal

    keywords = [
        candidate.keyword
        for candidate in keyword_pool[:MAX_KEYWORDS]
    ]
    return KeywordResult(keywords=keywords, candidates=sorted_candidates)


def build_filename(
    keyword_result: KeywordResult,
    settings: AppSettings,
    extension: str,
    confidence: float,
    now: datetime | None = None,
    force_fallback: bool = False,
) -> FilenameResult:
    timestamp = (now or datetime.now()).strftime(settings.timestamp_format)
    if extension.startswith("."):
        extension = extension.lower()
    else:
        extension = f".{extension.lower()}"
    sanitized_prefix = sanitize_fragment(settings.prefix)
    sanitized_keywords = [
        keyword
        for keyword in (
            sanitize_fragment(item)
            for item in keyword_result.keywords
        )
        if keyword
    ]
    trusted_keywords = _trusted_keywords(keyword_result)
    has_trusted_keywords = bool(trusted_keywords)
    if confidence < settings.confidence_threshold and has_trusted_keywords:
        sanitized_keywords = trusted_keywords
    used_fallback = (
        force_fallback
        or not sanitized_keywords
        or (
            confidence < settings.confidence_threshold
            and not has_trusted_keywords
        )
    )

    if used_fallback:
        stem = _fallback_stem(settings, sanitized_prefix, timestamp)
        filename = _fit_plain_stem(
            stem,
            settings.max_filename_length,
            timestamp,
        )
        return FilenameResult(
            filename=f"{filename}{extension}",
            used_fallback=True,
            keywords=[],
        )

    keyword_section = "_".join(sanitized_keywords[:MAX_KEYWORDS])
    stem = _keyword_stem(
        prefix=sanitized_prefix,
        keyword_section=keyword_section,
        timestamp=timestamp if settings.append_timestamp else "",
        max_length=settings.max_filename_length,
    )
    return FilenameResult(
        filename=f"{stem}{extension}",
        used_fallback=False,
        keywords=sanitized_keywords[:MAX_KEYWORDS],
    )


def sanitize_fragment(value: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    normalized = re.sub(r"[^a-z0-9_.]", "", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    normalized = normalized.strip(".")
    return normalized


def sanitize_keywords(values: Iterable[str]) -> list[str]:
    return [
        keyword
        for keyword in (sanitize_fragment(value) for value in values)
        if keyword
    ]


def _add_active_window_candidates(
    window_keywords: list[str],
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    """Add keywords from the active window title with highest priority."""
    order = len(candidates)
    for keyword in window_keywords:
        weight = 3.0
        if keyword == "folder":
            weight = 2.5
        elif keyword.startswith("gpt") or keyword in {"chat", "codex"}:
            weight = 3.4
        order = _add_candidate(
            candidates,
            seen,
            keyword,
            priority=0,
            weight=weight,
            source="active_window",
            order=order,
        )


def _add_ai_model_candidates(
    text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    for match in AI_MODEL_PATTERN.finditer(text):
        model = _normalize_model_match(match)
        if not model:
            continue
        order = _add_candidate(
            candidates,
            seen,
            model,
            priority=0,
            weight=3.6,
            source="ai_model",
            order=order,
        )


def _add_chat_context_candidates(
    text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    lower_text = text.lower()
    if re.search(r"\bnew\s*chat\b|\bchat\b", lower_text):
        order = _add_candidate(
            candidates,
            seen,
            "chat",
            priority=0,
            weight=3.2,
            source="chat_context",
            order=order,
        )

    for token in _tokenize(text):
        if token in CHAT_CONTEXT_WORDS:
            keyword = "chat" if token in {"chatgpt", "openai"} else token
            order = _add_candidate(
                candidates,
                seen,
                keyword,
                priority=1,
                weight=2.4,
                source="chat_context",
                order=order,
            )


def _add_cli_candidates(
    raw_text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    for line in raw_text.splitlines():
        prompt_match = re.search(r"(?:^|\s)(?:[$#>])\s*(.+)$", line)
        if prompt_match:
            segment = prompt_match.group(1)
            for token in _tokenize(segment):
                if token in COMMAND_WORDS:
                    if token in COMMAND_LAUNCHERS:
                        continue
                    weight = 2.0 if token not in LOW_VALUE_COMMANDS else 0.4
                    order = _add_candidate(
                        candidates,
                        seen,
                        token,
                        priority=1,
                        weight=weight,
                        source="cli_prompt",
                        order=order,
                    )

    lower_text = raw_text.lower()
    for match in re.finditer(r"\b[a-z][a-z0-9_-]*\b", lower_text):
        token = match.group(0)
        if token in COMMAND_WORDS:
            if token in COMMAND_LAUNCHERS:
                continue
            weight = 1.6 if token not in LOW_VALUE_COMMANDS else 0.3
            order = _add_candidate(
                candidates,
                seen,
                token,
                priority=1,
                weight=weight,
                source="cli_command",
                order=order,
            )


def _add_error_candidates(
    text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    for line in text.splitlines():
        line_tokens = _tokenize(line)
        if not any(token in ERROR_KEYWORDS for token in line_tokens):
            continue

        for token in line_tokens:
            if token in ERROR_KEYWORDS:
                order = _add_candidate(
                    candidates,
                    seen,
                    token,
                    priority=2,
                    weight=1.8,
                    source="error_status",
                    order=order,
                )
            elif token in ERROR_CONTEXT_WORDS:
                order = _add_candidate(
                    candidates,
                    seen,
                    token,
                    priority=2,
                    weight=1.1,
                    source="error_context",
                    order=order,
                )

    for token in _tokenize(text):
        if token in ERROR_KEYWORDS:
            order = _add_candidate(
                candidates,
                seen,
                token,
                priority=2,
                weight=1.5,
                source="error_keyword",
                order=order,
            )


def _add_header_candidates(
    header_text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    lower_header = header_text.lower()
    for phrase, keyword in APP_KEYWORDS.items():
        if phrase in lower_header:
            order = _add_candidate(
                candidates,
                seen,
                keyword,
                priority=3,
                weight=1.3,
                source="window_title",
                order=order,
            )

    for match in re.finditer(r"\b[\w.-]+\.[a-zA-Z0-9]{1,6}\b", header_text):
        filename = match.group(0)
        path = Path(filename)
        stem = sanitize_fragment(path.stem)
        extension_keyword = LANGUAGE_EXTENSIONS.get(path.suffix.lower())
        if stem:
            order = _add_candidate(
                candidates,
                seen,
                stem,
                priority=3,
                weight=1.6,
                source="file_title",
                order=order,
            )
        if extension_keyword:
            order = _add_candidate(
                candidates,
                seen,
                extension_keyword,
                priority=3,
                weight=1.1,
                source="file_language",
                order=order,
            )


def _add_domain_candidates(
    text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    for token in _tokenize(text):
        mapped = "postgres" if token == "postgresql" else token
        if mapped in DOMAIN_KEYWORDS:
            order = _add_candidate(
                candidates,
                seen,
                mapped,
                priority=4,
                weight=1.0,
                source="domain_keyword",
                order=order,
            )


def _add_noun_candidates(
    text: str,
    candidates: list[KeywordCandidate],
    seen: set[str],
) -> None:
    order = len(candidates)
    nouns = _extract_nouns(text)
    for noun in nouns:
        order = _add_candidate(
            candidates,
            seen,
            noun,
            priority=5,
            weight=0.8,
            source="noun_fallback",
            order=order,
        )


def _extract_nouns(text: str) -> list[str]:
    return [
        token
        for token in _tokenize(text)
        if (
            token not in FALLBACK_STOPWORDS
            and len(token) > 3
            and not _looks_like_model_noise(token)
        )
    ][:20]


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


def _looks_like_model_noise(token: str) -> bool:
    return bool(
        re.fullmatch(
            r"(?:gpt|claude|gemini|llama|mistral|qwen|deepseek)"
            r"[_-]?[0-9]+(?:\.[0-9]+)?[a-z]?",
            token,
        )
    )


def _trusted_keywords(keyword_result: KeywordResult) -> list[str]:
    selected = set(keyword_result.keywords)
    trusted = [
        candidate.keyword
        for candidate in keyword_result.candidates
        if (
            candidate.keyword in selected
            and candidate.source in TRUSTED_LOW_CONFIDENCE_SOURCES
        )
    ]
    return _merge_keywords(trusted)


def _merge_keywords(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group:
            keyword = sanitize_fragment(item)
            if keyword and keyword not in seen:
                seen.add(keyword)
                merged.append(keyword)
    return merged


def _add_candidate(
    candidates: list[KeywordCandidate],
    seen: set[str],
    raw_keyword: str,
    priority: int,
    weight: float,
    source: str,
    order: int,
) -> int:
    keyword = sanitize_fragment(raw_keyword)
    if not keyword or keyword in seen:
        return order
    seen.add(keyword)
    candidates.append(
        KeywordCandidate(
            keyword=keyword,
            priority=priority,
            weight=weight,
            source=source,
            order=order,
        )
    )
    return order + 1


def _tokenize(text: str) -> list[str]:
    return [
        sanitize_fragment(match.group(0))
        for match in re.finditer(r"[A-Za-z0-9_+.-]+", text.lower())
        if sanitize_fragment(match.group(0))
    ]


def _fallback_stem(
    settings: AppSettings,
    prefix: str,
    timestamp: str,
) -> str:
    template = settings.fallback_name_template or "screenshot_{timestamp}"
    try:
        base = template.format(timestamp=timestamp)
    except (KeyError, ValueError):
        base = f"screenshot_{timestamp}"
    sanitized = sanitize_fragment(base) or f"screenshot_{timestamp}"
    if "{timestamp}" not in template and settings.append_timestamp:
        sanitized = f"{sanitized}_{timestamp}"
    if prefix:
        sanitized = f"{prefix}_{sanitized}"
    return sanitized


def _keyword_stem(
    prefix: str,
    keyword_section: str,
    timestamp: str,
    max_length: int,
) -> str:
    pieces = [piece for piece in (prefix, keyword_section, timestamp) if piece]
    stem = "_".join(pieces)
    if len(stem) <= max_length:
        return stem

    protected_pieces = [piece for piece in (prefix, timestamp) if piece]
    separator_count = len(protected_pieces)
    reserved = sum(len(piece) for piece in protected_pieces) + separator_count
    allowed_keyword_length = max(1, max_length - reserved)
    trimmed_keywords = keyword_section[:allowed_keyword_length].rstrip("_")
    pieces = [
        piece
        for piece in (prefix, trimmed_keywords, timestamp)
        if piece
    ]
    stem = "_".join(pieces)
    if len(stem) <= max_length:
        return stem

    return _fit_plain_stem(stem, max_length, timestamp)


def _fit_plain_stem(stem: str, max_length: int, timestamp: str) -> str:
    if len(stem) <= max_length:
        return stem
    if timestamp and stem.endswith(timestamp):
        prefix_length = max(1, max_length - len(timestamp) - 1)
        prefix = stem[:prefix_length].rstrip("_")
        return f"{prefix}_{timestamp}"[:max_length]
    return stem[:max_length].rstrip("_") or "screenshot"
