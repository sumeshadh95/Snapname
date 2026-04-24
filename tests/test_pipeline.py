from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from ocr_engine import OcrResult
from pipeline import ScreenshotPipeline
from settings import AppSettings


class _SettingsManager:
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def load(self) -> AppSettings:
        return self._settings


class _HistoryDatabase:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []

    def log_rename(self, **kwargs: object) -> int:
        self.records.append(kwargs)
        return len(self.records)


class _OcrEngine:
    def read_image(self, image_path: Path) -> OcrResult:
        return OcrResult("$ git status failed", 0.91, ["git", "status"])

    def read_header(self, image_path: Path) -> OcrResult:
        return OcrResult("", 0.0, [])


class PipelineTests(unittest.TestCase):
    def test_destination_move_is_reflected_in_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            watch_dir = root / "watch"
            dest_dir = root / "renamed"
            watch_dir.mkdir()
            source = watch_dir / "Screenshot 1.png"
            source.write_bytes(b"not a real image; OCR is mocked")
            settings = replace(
                AppSettings.defaults(),
                watch_folder=str(watch_dir),
                destination_folder=str(dest_dir),
                append_timestamp=False,
                confidence_threshold=0.4,
            )
            history = _HistoryDatabase()
            pipeline = ScreenshotPipeline(_SettingsManager(settings), history)
            pipeline.ocr_engine = _OcrEngine()  # type: ignore[assignment]
            pipeline._notify = lambda new_name: None  # type: ignore[method-assign]
            pipeline._wait_for_file_ready = lambda path: True  # type: ignore[method-assign]

            result = pipeline.process_file(source)

            self.assertTrue(result.processed)
            self.assertIsNotNone(result.new_path)
            assert result.new_path is not None
            self.assertEqual(result.new_path.parent, dest_dir)
            self.assertTrue(result.new_path.exists())
            self.assertFalse(source.exists())
            self.assertEqual(len(history.records), 1)
            self.assertEqual(history.records[0]["folder_path"], str(dest_dir))
            self.assertEqual(history.records[0]["new_name"], result.new_path.name)


if __name__ == "__main__":
    unittest.main()
