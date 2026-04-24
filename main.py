from __future__ import annotations

import logging
import msvcrt
import sys
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import BinaryIO

from settings import get_app_dir


@dataclass
class SingleInstanceLock:
    path: Path
    handle: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.handle.close()
            self.handle = None


def setup_logging() -> None:
    log_path = get_app_dir() / "snapname.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            RotatingFileHandler(
                log_path,
                maxBytes=1_000_000,
                backupCount=3,
                encoding="utf-8",
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> int:
    setup_logging()
    if "--self-test" in sys.argv:
        return _run_self_test()

    lock = SingleInstanceLock(get_app_dir() / "snapname.lock")
    if not lock.acquire():
        logging.getLogger(__name__).warning(
            "SnapName is already running; exiting duplicate instance"
        )
        return 0

    try:
        from tray_app import TrayApp

        app = TrayApp()
        app.run()
    except KeyboardInterrupt:
        logging.getLogger(__name__).info(
            "SnapName stopped by keyboard interrupt"
        )
    except Exception:
        logging.getLogger(__name__).exception("SnapName crashed")
        raise
    finally:
        lock.release()
    return 0


def _run_self_test() -> int:
    logger = logging.getLogger(__name__)
    try:
        from tempfile import TemporaryDirectory

        from PIL import Image, ImageDraw, ImageFont

        from ocr_engine import TesseractOcrEngine

        with TemporaryDirectory(prefix="snapname-self-test-") as temp_dir:
            image_path = Path(temp_dir) / "ocr-test.png"
            image = Image.new("RGB", (1200, 360), "white")
            draw = ImageDraw.Draw(image)
            try:
                font = ImageFont.truetype("arial.ttf", 72)
            except OSError:
                font = ImageFont.load_default()
            draw.text(
                (60, 120),
                "SnapName OCR Test 123",
                fill="black",
                font=font,
            )
            image.save(image_path)

            result = TesseractOcrEngine().read_image(image_path)
            normalized_text = result.raw_text.lower()
            if "snapname" in normalized_text and "test" in normalized_text:
                logger.info("Self-test passed: %s", result.raw_text)
                return 0
            logger.error("Self-test OCR mismatch: %s", result.raw_text)
            return 1
    except Exception:
        logger.exception("Self-test failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
