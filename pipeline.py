from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from history import HistoryDatabase
from llava_engine import LlavaEngine
from nlp_namer import KeywordResult, build_filename, extract_keywords
from ocr_engine import OcrUnavailableError, TesseractOcrEngine
from settings import SettingsManager


LOGGER = logging.getLogger(__name__)
StatusCallback = Callable[[str], None]


@dataclass(frozen=True)
class PipelineResult:
    processed: bool
    original_path: Path
    new_path: Path | None
    engine_used: str
    confidence: float | None
    keywords: list[str]
    message: str


class ScreenshotPipeline:
    def __init__(
        self,
        settings_manager: SettingsManager,
        history_database: HistoryDatabase,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self.settings_manager = settings_manager
        self.history_database = history_database
        self.status_callback = status_callback
        self.ocr_engine = TesseractOcrEngine()
        self.llava_engine = LlavaEngine()
        self._lock = threading.RLock()

    def process_file(
        self,
        file_path: Path,
        window_keywords: list[str] | None = None,
    ) -> PipelineResult:
        with self._lock:
            settings = self.settings_manager.load()
            path = file_path.resolve()

            if not settings.enabled:
                return PipelineResult(
                    False,
                    path,
                    None,
                    settings.engine,
                    None,
                    [],
                    "Watching is paused.",
                )
            if path.suffix.lower() not in settings.file_extensions:
                return PipelineResult(
                    False,
                    path,
                    None,
                    settings.engine,
                    None,
                    [],
                    "Unsupported extension.",
                )
            if not self._wait_for_file_ready(path):
                LOGGER.warning("File was not ready for processing: %s", path)
                return PipelineResult(
                    False,
                    path,
                    None,
                    settings.engine,
                    None,
                    [],
                    "File was not ready.",
                )

            keyword_result = KeywordResult([], [])
            confidence = 0.0
            engine_used = "tesseract"
            force_fallback = False

            if settings.engine == "llava":
                llava_result = self.llava_engine.describe_image(path, settings)
                if llava_result.success:
                    keyword_result = KeywordResult(llava_result.keywords, [])
                    confidence = llava_result.confidence
                    engine_used = "llava"
                else:
                    self._set_status("LLaVA unavailable; using Tesseract")

            if engine_used != "llava":
                try:
                    ocr_result = self.ocr_engine.read_image(path)
                    header_result = self.ocr_engine.read_header(path)
                    keyword_result = extract_keywords(
                        raw_text=ocr_result.raw_text,
                        header_text=header_result.raw_text,
                        active_window_keywords=window_keywords or [],
                    )
                    confidence = ocr_result.avg_confidence
                    engine_used = "tesseract"
                except OcrUnavailableError as exc:
                    LOGGER.error("%s", exc)
                    self._set_status("Tesseract missing; using fallback names")
                    force_fallback = True
                    engine_used = "tesseract"
                    confidence = 0.0
                except Exception:
                    LOGGER.exception("Unexpected OCR failure for %s", path)
                    self._set_status("OCR error; using fallback names")
                    force_fallback = True
                    engine_used = "tesseract"
                    confidence = 0.0

            filename_result = build_filename(
                keyword_result=keyword_result,
                settings=settings,
                extension=path.suffix,
                confidence=confidence,
                force_fallback=force_fallback,
            )
            target_path = _unique_target_path(
                path.with_name(filename_result.filename),
                max_stem_length=settings.max_filename_length,
            )

            if _same_path(path, target_path):
                return PipelineResult(
                    False,
                    path,
                    None,
                    engine_used,
                    confidence,
                    filename_result.keywords,
                    "Generated filename matched the original name.",
                )

            original_name = path.name
            try:
                path.rename(target_path)
            except OSError as exc:
                LOGGER.exception(
                    "Could not rename %s to %s",
                    path,
                    target_path,
                )
                self._set_status("Rename failed; see snapname.log")
                return PipelineResult(
                    False,
                    path,
                    None,
                    engine_used,
                    confidence,
                    filename_result.keywords,
                    f"Rename failed: {exc}",
                )

            try:
                self.history_database.log_rename(
                    original_name=original_name,
                    new_name=target_path.name,
                    folder_path=str(target_path.parent),
                    engine_used=engine_used,
                    confidence=confidence,
                    keywords_found=filename_result.keywords,
                )
            except Exception:
                LOGGER.exception("Rename succeeded but history logging failed")

            # Move to destination folder if configured
            final_path = target_path
            dest_folder = settings.destination_folder.strip()
            if dest_folder and Path(dest_folder) != target_path.parent:
                dest_dir = Path(dest_folder)
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = _unique_target_path(
                    dest_dir / target_path.name,
                    max_stem_length=settings.max_filename_length,
                )
                try:
                    shutil.move(str(target_path), str(dest_path))
                    final_path = dest_path
                    LOGGER.info(
                        "Moved %s -> %s", target_path.name, dest_path
                    )
                except OSError as exc:
                    LOGGER.warning(
                        "Rename succeeded but move failed: %s", exc
                    )
                    # File stays in original location with new name

            self._notify(final_path.name)
            self._set_status("Active")
            return PipelineResult(
                True,
                path,
                final_path,
                engine_used,
                confidence,
                filename_result.keywords,
                f"Renamed to {final_path.name}",
            )

    def _wait_for_file_ready(
        self,
        path: Path,
        timeout_seconds: float = 8.0,
        interval_seconds: float = 0.2,
    ) -> bool:
        deadline = time.monotonic() + timeout_seconds
        previous_size = -1
        stable_reads = 0

        while time.monotonic() < deadline:
            if not path.exists():
                time.sleep(interval_seconds)
                continue
            try:
                current_size = path.stat().st_size
                with path.open("rb") as handle:
                    handle.read(1)
            except OSError:
                time.sleep(interval_seconds)
                continue

            if current_size > 0 and current_size == previous_size:
                stable_reads += 1
                if stable_reads >= 2:
                    return True
            else:
                stable_reads = 0
                previous_size = current_size
            time.sleep(interval_seconds)

        return False

    def _notify(self, new_name: str) -> None:
        try:
            from plyer import notification

            notification.notify(
                title="SnapName",
                message=f"Renamed -> {new_name}",
                timeout=3,
                app_name="SnapName",
            )
        except Exception:
            LOGGER.debug("Desktop notification failed", exc_info=True)

    def _set_status(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception:
            LOGGER.debug("Status callback failed", exc_info=True)


def _unique_target_path(path: Path, max_stem_length: int) -> Path:
    if not path.exists():
        return path

    original_stem = path.stem
    suffix = path.suffix
    for index in range(2, 10000):
        dedupe_suffix = f"_{index}"
        allowed_length = max(1, max_stem_length - len(dedupe_suffix))
        stem = original_stem[:allowed_length].rstrip("_")
        candidate = path.with_name(f"{stem}{dedupe_suffix}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find a unique filename for {path}")


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return str(left).lower() == str(right).lower()
