from __future__ import annotations

import logging
import msvcrt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from settings import get_app_dir
from tray_app import TrayApp


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
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main() -> None:
    setup_logging()
    lock = SingleInstanceLock(get_app_dir() / "snapname.lock")
    if not lock.acquire():
        logging.getLogger(__name__).warning(
            "SnapName is already running; exiting duplicate instance"
        )
        return

    try:
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


if __name__ == "__main__":
    main()
