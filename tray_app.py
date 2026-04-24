from __future__ import annotations

import logging
import threading
from typing import Any

import pystray
from PIL import Image, ImageDraw
from pystray import Menu, MenuItem

import tkinter as tk
from tkinter import filedialog

from gui.dashboard_window import (
    DashboardCallbacks,
    close_dashboard_window,
    open_dashboard_window_threaded,
)
from gui.history_window import open_history_window_threaded
from gui.settings_window import open_settings_window_threaded
from history import HistoryDatabase
from pipeline import ScreenshotPipeline
from settings import SettingsManager, get_resource_path
from watcher import ScreenshotWatcher


LOGGER = logging.getLogger(__name__)


class TrayApp:
    def __init__(self) -> None:
        self.settings_manager = SettingsManager()
        self.history_database = HistoryDatabase()
        self._status_lock = threading.RLock()
        self._status = "Starting"
        self.pipeline = ScreenshotPipeline(
            settings_manager=self.settings_manager,
            history_database=self.history_database,
            status_callback=self.set_status,
        )
        self.watcher = ScreenshotWatcher(
            settings_manager=self.settings_manager,
            pipeline=self.pipeline,
            status_callback=self.set_status,
        )
        self.icon = pystray.Icon(
            "SnapName",
            self._load_icon(),
            "SnapName",
            self._build_menu(),
        )

    def run(self) -> None:
        LOGGER.info("Starting SnapName")
        self.watcher.start()
        self.icon.run()

    def set_status(self, message: str) -> None:
        with self._status_lock:
            self._status = message
        try:
            self.icon.update_menu()
        except Exception:
            LOGGER.debug("Could not update tray menu", exc_info=True)

    def _build_menu(self) -> Menu:
        return Menu(
            MenuItem(lambda item: self._status_text(), None, enabled=False),
            MenuItem(
                lambda item: self._destination_text(),
                None,
                enabled=False,
            ),
            Menu.SEPARATOR,
            MenuItem("Open Dashboard", self._open_dashboard, default=True),
            MenuItem("Set Destination Folder…", self._set_destination),
            MenuItem("Change Watch Folder…", self._set_watch_folder),
            MenuItem("Open Settings", self._open_settings),
            MenuItem("View Rename History", self._open_history),
            MenuItem(
                lambda item: self._pause_resume_text(),
                self._toggle_pause,
            ),
            Menu.SEPARATOR,
            MenuItem("Undo Last Rename", self._undo_last),
            Menu.SEPARATOR,
            MenuItem("Quit", self._quit),
        )

    def _status_text(self) -> str:
        with self._status_lock:
            status = self._status
        settings = self.settings_manager.load()
        if not settings.enabled:
            return "SnapName - Paused"
        return f"SnapName - {status}"

    def _pause_resume_text(self) -> str:
        settings = self.settings_manager.load()
        return "Resume Watching" if not settings.enabled else "Pause Watching"

    def _dashboard_status_text(self) -> str:
        return self._status_text()

    def _destination_text(self) -> str:
        settings = self.settings_manager.load()
        dest = settings.destination_folder.strip()
        if dest:
            # Show just the last folder name for brevity
            from pathlib import Path
            short = Path(dest).name or dest
            return f"Dest → {short}"
        return "Dest → Same folder"

    def _open_settings(self, icon: Any = None, item: Any = None) -> None:
        open_settings_window_threaded(
            self.settings_manager,
            on_save=self.watcher.restart,
        )

    def _open_dashboard(self, icon: Any = None, item: Any = None) -> None:
        open_dashboard_window_threaded(
            self.settings_manager,
            self.history_database,
            DashboardCallbacks(
                get_status=self._dashboard_status_text,
                on_settings_saved=self._on_dashboard_settings_saved,
                on_pause=self._pause_from_dashboard,
                on_resume=self._resume_from_dashboard,
                on_undo_last=self._undo_last_from_dashboard,
                on_quit=self._quit,
            ),
        )

    def _open_history(self, icon: Any = None, item: Any = None) -> None:
        open_history_window_threaded(self.history_database)

    def _toggle_pause(self, icon: Any = None, item: Any = None) -> None:
        settings = self.settings_manager.load()
        if settings.enabled:
            self.watcher.pause()
        else:
            self.watcher.resume()
        self.icon.update_menu()

    def _pause_from_dashboard(self) -> None:
        self.watcher.pause()
        self.icon.update_menu()

    def _resume_from_dashboard(self) -> None:
        self.watcher.resume()
        self.icon.update_menu()

    def _on_dashboard_settings_saved(self) -> None:
        self.watcher.restart()
        self.icon.update_menu()

    def _undo_last(self, icon: Any = None, item: Any = None) -> None:
        self._undo_last_from_dashboard()

    def _undo_last_from_dashboard(self) -> str:
        result = self.history_database.undo_last_rename()
        self.set_status(result.message)
        self._notify(result.message)
        return result.message

    def _quit(self, icon: Any = None, item: Any = None) -> None:
        LOGGER.info("Quitting SnapName")
        close_dashboard_window()
        self.watcher.shutdown()
        self.icon.stop()

    def _set_destination(self, icon: Any = None, item: Any = None) -> None:
        """Open a folder picker to set the destination folder."""
        def _pick():
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            settings = self.settings_manager.load()
            initial = settings.destination_folder.strip() or settings.watch_folder
            folder = filedialog.askdirectory(
                title="Choose destination folder for renamed screenshots",
                initialdir=initial or None,
            )
            root.destroy()
            if folder:
                self.settings_manager.update(destination_folder=folder)
                self._notify(f"Destination set to {folder}")
                LOGGER.info("Destination folder changed to: %s", folder)
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

        thread = threading.Thread(
            target=_pick, name="SnapNameDestPicker", daemon=True
        )
        thread.start()

    def _set_watch_folder(self, icon: Any = None, item: Any = None) -> None:
        """Open a folder picker to change the watch folder."""
        def _pick():
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            settings = self.settings_manager.load()
            folder = filedialog.askdirectory(
                title="Choose screenshot watch folder",
                initialdir=settings.watch_folder or None,
            )
            root.destroy()
            if folder:
                self.settings_manager.update(watch_folder=folder)
                self.watcher.restart()
                self._notify(f"Now watching {folder}")
                LOGGER.info("Watch folder changed to: %s", folder)
                try:
                    self.icon.update_menu()
                except Exception:
                    pass

        thread = threading.Thread(
            target=_pick, name="SnapNameWatchPicker", daemon=True
        )
        thread.start()

    def _notify(self, message: str) -> None:
        try:
            from plyer import notification

            notification.notify(
                title="SnapName",
                message=message,
                timeout=3,
                app_name="SnapName",
            )
        except Exception:
            LOGGER.debug("Desktop notification failed", exc_info=True)

    def _load_icon(self) -> Image.Image:
        icon_path = get_resource_path("assets/icon.ico")
        if icon_path.exists():
            try:
                return Image.open(icon_path)
            except OSError:
                LOGGER.exception("Could not load tray icon: %s", icon_path)
        return _fallback_icon()


def _fallback_icon() -> Image.Image:
    image = Image.new("RGB", (64, 64), "#2563eb")
    draw = ImageDraw.Draw(image)
    draw.rectangle((8, 8, 56, 56), outline="#ffffff", width=3)
    draw.text((23, 20), "S", fill="#ffffff")
    return image
