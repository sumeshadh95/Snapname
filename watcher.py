from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import (
    FileCreatedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
    FileModifiedEvent,
    FileMovedEvent,
)
from watchdog.observers import Observer

from pipeline import ScreenshotPipeline
from settings import SettingsManager
from active_window import get_active_window_info


LOGGER = logging.getLogger(__name__)
StatusCallback = Callable[[str], None]


class ScreenshotCreatedHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ScreenshotWatcher") -> None:
        super().__init__()
        self.watcher = watcher

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory or not isinstance(event, FileCreatedEvent):
            return
        self.watcher.enqueue(Path(event.src_path))

    def on_moved(self, event: FileSystemEvent) -> None:
        if event.is_directory or not isinstance(event, FileMovedEvent):
            return
        self.watcher.enqueue(Path(event.dest_path))

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory or not isinstance(event, FileModifiedEvent):
            return
        self.watcher.enqueue(Path(event.src_path))


class ScreenshotWatcher:
    def __init__(
        self,
        settings_manager: SettingsManager,
        pipeline: ScreenshotPipeline,
        status_callback: StatusCallback | None = None,
    ) -> None:
        self.settings_manager = settings_manager
        self.pipeline = pipeline
        self.status_callback = status_callback
        self._queue: queue.Queue[tuple[Path, list[str]] | None] = queue.Queue()
        self._observer: Observer | None = None
        self._stop_event = threading.Event()
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="SnapNameWorker",
            daemon=True,
        )
        self._worker.start()
        self._observer_lock = threading.RLock()
        self._enqueue_lock = threading.RLock()
        self._recent_enqueue_times: dict[Path, float] = {}
        self._ignored_paths: dict[Path, float] = {}

    def start(self) -> None:
        with self._observer_lock:
            self._stop_observer()
            settings = self.settings_manager.load()
            if not settings.enabled:
                self._set_status("Paused")
                return

            watch_folder = Path(settings.watch_folder)
            watch_folder.mkdir(parents=True, exist_ok=True)
            handler = ScreenshotCreatedHandler(self)
            observer = Observer()
            observer.schedule(handler, str(watch_folder), recursive=False)
            observer.start()
            self._observer = observer
            self._set_status("Active")
            LOGGER.info("Watching folder: %s", watch_folder)

    def restart(self) -> None:
        LOGGER.info("Restarting watcher")
        self.start()

    def pause(self) -> None:
        self.settings_manager.update(enabled=False)
        with self._observer_lock:
            self._stop_observer()
        self._set_status("Paused")

    def resume(self) -> None:
        self.settings_manager.update(enabled=True)
        self.start()

    def shutdown(self) -> None:
        LOGGER.info("Shutting down watcher")
        with self._observer_lock:
            self._stop_observer()
        self._stop_event.set()
        self._queue.put(None)
        self._worker.join(timeout=3)

    def enqueue(self, path: Path) -> None:
        settings = self.settings_manager.load()
        if not settings.enabled:
            return
        if path.suffix.lower() not in settings.file_extensions:
            return
        if self._is_ignored(path):
            return
        if not self._should_enqueue(path):
            return
        # Capture active window info immediately — this is what the user
        # was looking at when the screenshot was taken.
        settings = self.settings_manager.load()
        window_keywords: list[str] = []
        if settings.use_active_window:
            try:
                info = get_active_window_info()
                window_keywords = info.keywords
                if info.raw_title:
                    LOGGER.info(
                        "Active window at capture: %s", info.raw_title
                    )
            except Exception:
                LOGGER.debug(
                    "Could not capture active window", exc_info=True
                )
        self._queue.put((path, window_keywords))

    def is_active(self) -> bool:
        return (
            self.settings_manager.load().enabled
            and self._observer is not None
        )

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                item = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break

            path, window_keywords = item
            settings = self.settings_manager.load()
            if not settings.enabled:
                continue
            if self._is_ignored(path):
                continue

            time.sleep(settings.delay_seconds)
            if self._is_ignored(path):
                continue
            try:
                result = self.pipeline.process_file(
                    path, window_keywords=window_keywords
                )
                if result.processed and result.new_path is not None:
                    self._mark_ignored(result.new_path)
                LOGGER.info("%s", result.message)
            except Exception:
                LOGGER.exception("Unhandled pipeline error for %s", path)
                self._set_status("Processing error; see snapname.log")

    def _stop_observer(self) -> None:
        if self._observer is None:
            return
        observer = self._observer
        self._observer = None
        observer.stop()
        observer.join(timeout=5)

    def _should_enqueue(self, path: Path) -> bool:
        now = time.monotonic()
        resolved = path.resolve()
        with self._enqueue_lock:
            old_entries = [
                item_path
                for item_path, timestamp in self._recent_enqueue_times.items()
                if now - timestamp > 20.0
            ]
            for item_path in old_entries:
                self._recent_enqueue_times.pop(item_path, None)

            last_seen = self._recent_enqueue_times.get(resolved)
            if last_seen is not None and now - last_seen < 5.0:
                return False
            self._recent_enqueue_times[resolved] = now
            return True

    def _mark_ignored(self, path: Path) -> None:
        with self._enqueue_lock:
            self._ignored_paths[path.resolve()] = time.monotonic() + 30.0

    def _is_ignored(self, path: Path) -> bool:
        now = time.monotonic()
        resolved = path.resolve()
        with self._enqueue_lock:
            expired_paths = [
                item_path
                for item_path, expires_at in self._ignored_paths.items()
                if expires_at <= now
            ]
            for item_path in expired_paths:
                self._ignored_paths.pop(item_path, None)

            expires_at = self._ignored_paths.get(resolved)
            return expires_at is not None and expires_at > now

    def _set_status(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception:
            LOGGER.debug("Status callback failed", exc_info=True)
