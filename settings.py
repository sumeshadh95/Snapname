from __future__ import annotations

import json
import logging
import os
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)
VALID_ENGINES = {"tesseract"}
DEFAULT_EXTENSIONS = [".png", ".jpg", ".jpeg"]


def get_app_dir() -> Path:
    """Return the writable directory beside the source file or frozen EXE."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_resource_path(relative_path: str) -> Path:
    """Return a bundled resource path, supporting PyInstaller one-file mode."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        candidate = Path(frozen_root).resolve() / relative_path
        if candidate.exists():
            return candidate
    return get_app_dir() / relative_path


def default_watch_folder() -> str:
    """Return the standard Windows screenshots folder for the current user."""
    user_profile = Path(os.environ.get("USERPROFILE", str(Path.home())))
    candidates = [
        user_profile / "Pictures" / "Screenshots",
        user_profile / "OneDrive" / "Pictures" / "Screenshots",
        user_profile / "OneDrive" / "Pictures" / "Screenshots 1",
    ]
    for env_name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        one_drive = os.environ.get(env_name)
        if one_drive:
            candidates.extend(
                [
                    Path(one_drive) / "Pictures" / "Screenshots",
                    Path(one_drive) / "Pictures" / "Screenshots 1",
                ]
            )

    existing_candidates = [
        candidate
        for candidate in candidates
        if candidate.exists()
    ]
    if existing_candidates:
        newest = max(
            existing_candidates,
            key=lambda candidate: candidate.stat().st_mtime,
        )
        return str(newest)
    return str(user_profile / "Pictures")


@dataclass(frozen=True)
class AppSettings:
    watch_folder: str
    destination_folder: str
    prefix: str
    append_timestamp: bool
    timestamp_format: str
    max_filename_length: int
    engine: str
    confidence_threshold: float
    fallback_name_template: str
    file_extensions: list[str]
    delay_seconds: float
    use_active_window: bool
    enabled: bool

    @classmethod
    def defaults(cls) -> "AppSettings":
        return cls(
            watch_folder=default_watch_folder(),
            destination_folder="",
            prefix="",
            append_timestamp=False,
            timestamp_format="%Y%m%d_%H%M%S",
            max_filename_length=60,
            engine="tesseract",
            confidence_threshold=0.4,
            fallback_name_template="screenshot_{timestamp}",
            file_extensions=DEFAULT_EXTENSIONS.copy(),
            delay_seconds=1.5,
            use_active_window=True,
            enabled=True,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppSettings":
        defaults = cls.defaults()
        merged = asdict(defaults)
        merged.update(
            {key: value for key, value in data.items() if key in merged}
        )

        watch_folder = _clean_path(str(merged["watch_folder"]))
        destination_folder = (
            _clean_path(str(merged["destination_folder"]))
            if merged.get("destination_folder")
            else ""
        )
        prefix = str(merged["prefix"]).strip()
        timestamp_format = _valid_timestamp_format(
            str(merged["timestamp_format"]),
            defaults.timestamp_format,
        )
        max_filename_length = _clamp_int(
            merged["max_filename_length"],
            minimum=24,
            maximum=180,
            fallback=defaults.max_filename_length,
        )
        engine = str(merged["engine"]).strip().lower()
        if engine not in VALID_ENGINES:
            LOGGER.warning(
                "Unknown engine %s; falling back to tesseract",
                engine,
            )
            engine = defaults.engine

        confidence_threshold = _clamp_float(
            merged["confidence_threshold"],
            minimum=0.1,
            maximum=0.9,
            fallback=defaults.confidence_threshold,
        )
        file_extensions = _clean_extensions(merged["file_extensions"])
        delay_seconds = _clamp_float(
            merged["delay_seconds"],
            minimum=0.1,
            maximum=30.0,
            fallback=defaults.delay_seconds,
        )

        return cls(
            watch_folder=watch_folder,
            destination_folder=destination_folder,
            prefix=prefix,
            append_timestamp=bool(merged["append_timestamp"]),
            timestamp_format=timestamp_format,
            max_filename_length=max_filename_length,
            engine=engine,
            confidence_threshold=confidence_threshold,
            fallback_name_template=(
                str(merged["fallback_name_template"]).strip()
                or defaults.fallback_name_template
            ),
            file_extensions=file_extensions,
            delay_seconds=delay_seconds,
            use_active_window=bool(merged.get("use_active_window", True)),
            enabled=bool(merged["enabled"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SettingsManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_app_dir() / "settings.json"
        self._lock = threading.RLock()

    def load(self) -> AppSettings:
        with self._lock:
            if not self.path.exists():
                settings = AppSettings.defaults()
                self._write(settings)
                return settings

            try:
                raw_data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                LOGGER.exception(
                    "Could not read settings; defaults will be used"
                )
                settings = AppSettings.defaults()
                self._write(settings)
                return settings

            if not isinstance(raw_data, dict):
                LOGGER.warning("settings.json did not contain an object")
                settings = AppSettings.defaults()
                self._write(settings)
                return settings

            settings = AppSettings.from_dict(raw_data)
            if raw_data != settings.to_dict():
                self._write(settings)
            return settings

    def save(self, settings: AppSettings) -> AppSettings:
        with self._lock:
            cleaned = AppSettings.from_dict(settings.to_dict())
            self._write(cleaned)
            return cleaned

    def update(self, **changes: Any) -> AppSettings:
        with self._lock:
            current = self.load().to_dict()
            current.update(changes)
            settings = AppSettings.from_dict(current)
            self._write(settings)
            return settings

    def ensure_watch_folder(self) -> Path:
        settings = self.load()
        folder = Path(settings.watch_folder)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _write(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".json.tmp")
        data = json.dumps(settings.to_dict(), indent=2)
        temp_path.write_text(data + "\n", encoding="utf-8")
        temp_path.replace(self.path)


def _clean_path(value: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(value.strip()))
    return str(Path(expanded))


def _valid_timestamp_format(value: str, fallback: str) -> str:
    if not value:
        return fallback
    try:
        datetime.now().strftime(value)
    except ValueError:
        LOGGER.warning("Invalid timestamp format %s; using default", value)
        return fallback
    return value


def _clean_extensions(value: Any) -> list[str]:
    if not isinstance(value, list):
        return DEFAULT_EXTENSIONS.copy()

    cleaned: list[str] = []
    for item in value:
        extension = str(item).strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = "." + extension
        if extension not in cleaned:
            cleaned.append(extension)
    return cleaned or DEFAULT_EXTENSIONS.copy()


def _clamp_int(
    value: Any,
    minimum: int,
    maximum: int,
    fallback: int,
) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))


def _clamp_float(
    value: Any,
    minimum: float,
    maximum: float,
    fallback: float,
) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, parsed))
