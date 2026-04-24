from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from active_window import get_active_window_info, list_visible_windows
from history import HistoryDatabase, RenameRecord
from settings import SettingsManager, get_resource_path


LOGGER = logging.getLogger(__name__)
StatusGetter = Callable[[], str]
SimpleCallback = Callable[[], None]
UndoCallback = Callable[[], str]


@dataclass(frozen=True)
class DashboardCallbacks:
    get_status: StatusGetter
    on_settings_saved: SimpleCallback
    on_pause: SimpleCallback
    on_resume: SimpleCallback
    on_undo_last: UndoCallback
    on_quit: SimpleCallback


class DashboardWindow:
    def __init__(
        self,
        settings_manager: SettingsManager,
        history_database: HistoryDatabase,
        callbacks: DashboardCallbacks,
    ) -> None:
        self.settings_manager = settings_manager
        self.history_database = history_database
        self.callbacks = callbacks
        self._closed = False
        self._refresh_after_id: str | None = None
        self._history_records: dict[str, RenameRecord] = {}

        self.root = tk.Tk()
        self.root.title("SnapName Dashboard")
        self.root.geometry("980x680")
        self.root.minsize(860, 580)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self._set_window_icon()

        self.status_var = tk.StringVar(value="Starting")
        self.message_var = tk.StringVar(value="Close this window to keep SnapName running in the tray.")
        self.watch_folder_var = tk.StringVar()
        self.dest_folder_var = tk.StringVar()
        self.prefix_var = tk.StringVar()
        self.extensions_var = tk.StringVar()
        self.delay_var = tk.DoubleVar()
        self.confidence_var = tk.DoubleVar()
        self.append_timestamp_var = tk.BooleanVar()
        self.use_active_window_var = tk.BooleanVar()
        self.active_title_var = tk.StringVar(value="-")
        self.active_process_var = tk.StringVar(value="-")
        self.active_app_var = tk.StringVar(value="-")
        self.active_keywords_var = tk.StringVar(value="-")

        self._build_ui()
        self._load_values()
        self._refresh_dashboard()

    def run(self) -> None:
        self.root.mainloop()

    def show_threadsafe(self) -> None:
        try:
            self.root.after(0, self.show)
        except tk.TclError:
            LOGGER.debug("Dashboard is not available", exc_info=True)

    def destroy_threadsafe(self) -> None:
        try:
            self.root.after(0, self.destroy)
        except tk.TclError:
            LOGGER.debug("Dashboard is already closed", exc_info=True)

    def is_alive(self) -> bool:
        return not self._closed

    def show(self) -> None:
        if self._closed:
            return
        self._load_values()
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()
        self._refresh_dashboard(force=True)

    def hide(self) -> None:
        if self._closed:
            return
        self.message_var.set("Dashboard hidden. SnapName is still running in the tray.")
        self.root.withdraw()

    def destroy(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._refresh_after_id is not None:
            try:
                self.root.after_cancel(self._refresh_after_id)
            except tk.TclError:
                pass
        self.root.destroy()

    def _set_window_icon(self) -> None:
        icon_path = get_resource_path("assets/icon.ico")
        if not icon_path.exists():
            return
        try:
            self.root.iconbitmap(str(icon_path))
        except tk.TclError:
            LOGGER.debug("Could not set dashboard icon", exc_info=True)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        header = ttk.Frame(outer)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        header.columnconfigure(1, weight=1)
        ttk.Label(
            header,
            text="SnapName Dashboard",
            font=("Segoe UI", 18, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            textvariable=self.status_var,
            font=("Segoe UI", 10, "bold"),
        ).grid(row=0, column=1, sticky="e", padx=(12, 8))
        self.pause_button = ttk.Button(
            header,
            width=16,
            command=self._toggle_pause,
        )
        self.pause_button.grid(row=0, column=2, sticky="e", padx=(0, 8))
        ttk.Button(header, text="Undo Last", command=self._undo_last).grid(
            row=0,
            column=3,
            sticky="e",
            padx=(0, 8),
        )
        ttk.Button(header, text="Quit", command=self._quit).grid(
            row=0,
            column=4,
            sticky="e",
        )

        notebook = ttk.Notebook(outer)
        notebook.grid(row=1, column=0, sticky="nsew")
        self.setup_tab = ttk.Frame(notebook, padding=12)
        self.history_tab = ttk.Frame(notebook, padding=12)
        self.windows_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.setup_tab, text="Setup")
        notebook.add(self.history_tab, text="History")
        notebook.add(self.windows_tab, text="Windows")

        self._build_setup_tab()
        self._build_history_tab()
        self._build_windows_tab()

        ttk.Label(
            outer,
            textvariable=self.message_var,
            foreground="#555555",
        ).grid(row=2, column=0, sticky="ew", pady=(10, 0))

    def _build_setup_tab(self) -> None:
        frame = self.setup_tab
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Watch folder", font=("Segoe UI", 10, "bold")).grid(
            row=0,
            column=0,
            columnspan=3,
            sticky="w",
        )
        ttk.Entry(frame, textvariable=self.watch_folder_var).grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 12),
        )
        ttk.Button(frame, text="Browse", command=self._browse_watch).grid(
            row=1,
            column=2,
            sticky="ew",
            padx=(8, 0),
            pady=(4, 12),
        )

        ttk.Label(
            frame,
            text="Destination folder",
            font=("Segoe UI", 10, "bold"),
        ).grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Entry(frame, textvariable=self.dest_folder_var).grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 12),
        )
        dest_buttons = ttk.Frame(frame)
        dest_buttons.grid(row=3, column=2, sticky="ew", padx=(8, 0), pady=(4, 12))
        ttk.Button(dest_buttons, text="Browse", command=self._browse_dest).pack(
            side="left",
            fill="x",
            expand=True,
        )
        ttk.Button(dest_buttons, text="Clear", command=self._clear_dest).pack(
            side="left",
            padx=(6, 0),
        )

        ttk.Label(frame, text="Filename prefix").grid(row=4, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.prefix_var, width=28).grid(
            row=5,
            column=0,
            sticky="w",
            pady=(4, 12),
        )

        ttk.Label(frame, text="File extensions").grid(row=4, column=1, sticky="w")
        ttk.Entry(frame, textvariable=self.extensions_var).grid(
            row=5,
            column=1,
            sticky="ew",
            pady=(4, 12),
        )

        ttk.Checkbutton(
            frame,
            text="Append timestamp to smart names",
            variable=self.append_timestamp_var,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 6))
        ttk.Checkbutton(
            frame,
            text="Use active Windows app context for better names",
            variable=self.use_active_window_var,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(frame, text="OCR confidence threshold").grid(
            row=8,
            column=0,
            sticky="w",
        )
        threshold_frame = ttk.Frame(frame)
        threshold_frame.grid(row=9, column=0, sticky="ew", pady=(4, 12))
        threshold_frame.columnconfigure(0, weight=1)
        ttk.Scale(
            threshold_frame,
            from_=0.1,
            to=0.9,
            variable=self.confidence_var,
            orient="horizontal",
            command=self._update_threshold_label,
        ).grid(row=0, column=0, sticky="ew")
        self.threshold_label = ttk.Label(threshold_frame, width=5)
        self.threshold_label.grid(row=0, column=1, padx=(8, 0))

        ttk.Label(frame, text="Processing delay seconds").grid(
            row=8,
            column=1,
            sticky="w",
        )
        delay_frame = ttk.Frame(frame)
        delay_frame.grid(row=9, column=1, sticky="ew", pady=(4, 12))
        delay_frame.columnconfigure(0, weight=1)
        ttk.Scale(
            delay_frame,
            from_=0.2,
            to=5.0,
            variable=self.delay_var,
            orient="horizontal",
            command=self._update_delay_label,
        ).grid(row=0, column=0, sticky="ew")
        self.delay_label = ttk.Label(delay_frame, width=5)
        self.delay_label.grid(row=0, column=1, padx=(8, 0))

        action_frame = ttk.Frame(frame)
        action_frame.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        ttk.Button(action_frame, text="Open Watch Folder", command=self._open_watch_folder).pack(
            side="left",
        )
        ttk.Button(action_frame, text="Open Destination", command=self._open_destination_folder).pack(
            side="left",
            padx=(8, 0),
        )
        ttk.Button(action_frame, text="Reload", command=self._load_values).pack(
            side="right",
            padx=(8, 0),
        )
        ttk.Button(action_frame, text="Save and Restart Watcher", command=self._save_settings).pack(
            side="right",
        )

        help_text = (
            "Tip: keep active window context on. It uses direct Win32 calls "
            "instead of heavier packages, so it stays fast and low-memory."
        )
        ttk.Label(frame, text=help_text, foreground="#555555", wraplength=760).grid(
            row=11,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(18, 0),
        )

    def _build_history_tab(self) -> None:
        frame = self.history_tab
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        columns = ("time", "old", "new", "engine", "confidence", "keywords")
        self.history_tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            height=16,
        )
        headings = {
            "time": "Time",
            "old": "Old Name",
            "new": "New Name",
            "engine": "Engine",
            "confidence": "Conf.",
            "keywords": "Keywords",
        }
        widths = {
            "time": 140,
            "old": 170,
            "new": 220,
            "engine": 80,
            "confidence": 70,
            "keywords": 220,
        }
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], anchor="w")
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.history_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(frame)
        actions.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(actions, text="Refresh", command=self._refresh_history).pack(side="left")
        ttk.Button(actions, text="Open Selected Folder", command=self._open_selected_history).pack(
            side="left",
            padx=(8, 0),
        )
        ttk.Button(actions, text="Undo Selected", command=self._undo_selected_history).pack(
            side="left",
            padx=(8, 0),
        )

    def _build_windows_tab(self) -> None:
        frame = self.windows_tab
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)

        active_frame = ttk.LabelFrame(frame, text="Current foreground window", padding=10)
        active_frame.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        active_frame.columnconfigure(1, weight=1)
        self._add_info_row(active_frame, 0, "Title", self.active_title_var)
        self._add_info_row(active_frame, 1, "App", self.active_app_var)
        self._add_info_row(active_frame, 2, "Process", self.active_process_var)
        self._add_info_row(active_frame, 3, "Keywords", self.active_keywords_var)

        ttk.Button(
            frame,
            text="Refresh Window Context",
            command=self._refresh_window_context,
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        columns = ("app", "process", "class", "title")
        self.windows_tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            height=13,
        )
        for column, heading, width in (
            ("app", "App", 90),
            ("process", "Process", 110),
            ("class", "Class", 120),
            ("title", "Window Title", 520),
        ):
            self.windows_tree.heading(column, text=heading)
            self.windows_tree.column(column, width=width, anchor="w")
        self.windows_tree.grid(row=2, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.windows_tree.yview)
        scrollbar.grid(row=2, column=1, sticky="ns")
        self.windows_tree.configure(yscrollcommand=scrollbar.set)

        ttk.Label(
            frame,
            text=(
                "This view uses direct Win32 foreground-window and top-level "
                "window enumeration. No pywin32 or PyWinCtl dependency is loaded."
            ),
            foreground="#555555",
            wraplength=780,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _add_info_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
    ) -> None:
        ttk.Label(parent, text=label, width=10, font=("Segoe UI", 9, "bold")).grid(
            row=row,
            column=0,
            sticky="nw",
            pady=2,
        )
        ttk.Label(parent, textvariable=variable, wraplength=760).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=2,
        )

    def _load_values(self) -> None:
        settings = self.settings_manager.load()
        self.watch_folder_var.set(settings.watch_folder)
        self.dest_folder_var.set(settings.destination_folder)
        self.prefix_var.set(settings.prefix)
        self.extensions_var.set(", ".join(settings.file_extensions))
        self.delay_var.set(settings.delay_seconds)
        self.confidence_var.set(settings.confidence_threshold)
        self.append_timestamp_var.set(settings.append_timestamp)
        self.use_active_window_var.set(settings.use_active_window)
        self._update_delay_label(str(settings.delay_seconds))
        self._update_threshold_label(str(settings.confidence_threshold))
        self._update_status_controls()

    def _refresh_dashboard(self, force: bool = False) -> None:
        if self._closed:
            return
        self._update_status_controls()
        if force or self._is_visible():
            self._refresh_window_context()
            self._refresh_history()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        if self._refresh_after_id is not None:
            return
        self._refresh_after_id = self.root.after(2500, self._on_refresh_timer)

    def _on_refresh_timer(self) -> None:
        self._refresh_after_id = None
        self._refresh_dashboard()

    def _is_visible(self) -> bool:
        try:
            return self.root.state() != "withdrawn"
        except tk.TclError:
            return False

    def _update_status_controls(self) -> None:
        settings = self.settings_manager.load()
        status = self.callbacks.get_status()
        self.status_var.set(status)
        self.pause_button.configure(
            text="Resume Watching" if not settings.enabled else "Pause Watching"
        )

    def _refresh_window_context(self) -> None:
        try:
            active = get_active_window_info()
            self.active_title_var.set(active.raw_title or "-")
            self.active_app_var.set(active.app_name or "-")
            process_label = active.process_name or "-"
            if active.window_class:
                process_label = f"{process_label} / {active.window_class}"
            self.active_process_var.set(process_label)
            self.active_keywords_var.set(", ".join(active.keywords) or "-")

            self.windows_tree.delete(*self.windows_tree.get_children())
            for index, window in enumerate(list_visible_windows(limit=18)):
                self.windows_tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        window.app_name or "-",
                        window.process_name or "-",
                        window.window_class or "-",
                        _shorten(window.raw_title, 120),
                    ),
                )
        except Exception:
            LOGGER.debug("Could not refresh dashboard window context", exc_info=True)

    def _refresh_history(self) -> None:
        try:
            records = self.history_database.get_history(limit=80)
        except Exception:
            LOGGER.debug("Could not refresh dashboard history", exc_info=True)
            return

        self.history_records = {str(record.id): record for record in records}
        self.history_tree.delete(*self.history_tree.get_children())
        for record in records:
            confidence = "-" if record.confidence is None else f"{record.confidence:.2f}"
            keywords = ", ".join(record.keywords_found)
            if record.was_undone:
                keywords = f"undone; {keywords}" if keywords else "undone"
            self.history_tree.insert(
                "",
                "end",
                iid=str(record.id),
                values=(
                    record.renamed_at,
                    _shorten(record.original_name, 34),
                    _shorten(record.new_name, 42),
                    record.engine_used,
                    confidence,
                    _shorten(keywords, 54),
                ),
            )

    @property
    def history_records(self) -> dict[str, RenameRecord]:
        return self._history_records

    @history_records.setter
    def history_records(self, value: dict[str, RenameRecord]) -> None:
        self._history_records = value

    def _browse_watch(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose screenshot folder",
            initialdir=self.watch_folder_var.get() or None,
            parent=self.root,
        )
        if folder:
            self.watch_folder_var.set(folder)

    def _browse_dest(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose destination folder",
            initialdir=self.dest_folder_var.get() or self.watch_folder_var.get() or None,
            parent=self.root,
        )
        if folder:
            self.dest_folder_var.set(folder)

    def _clear_dest(self) -> None:
        self.dest_folder_var.set("")

    def _save_settings(self) -> None:
        try:
            self.settings_manager.update(
                watch_folder=self.watch_folder_var.get(),
                destination_folder=self.dest_folder_var.get(),
                prefix=self.prefix_var.get(),
                append_timestamp=self.append_timestamp_var.get(),
                use_active_window=self.use_active_window_var.get(),
                confidence_threshold=round(float(self.confidence_var.get()), 2),
                delay_seconds=round(float(self.delay_var.get()), 2),
                file_extensions=_parse_extensions(self.extensions_var.get()),
            )
            self.callbacks.on_settings_saved()
        except Exception as exc:
            LOGGER.exception("Failed to save dashboard settings")
            messagebox.showerror(
                "SnapName",
                f"Settings could not be saved: {exc}",
                parent=self.root,
            )
            return

        self.message_var.set("Settings saved. Watcher restarted with the new setup.")
        self._load_values()
        self._refresh_dashboard(force=True)

    def _toggle_pause(self) -> None:
        settings = self.settings_manager.load()
        if settings.enabled:
            self.callbacks.on_pause()
            self.message_var.set("Watching paused. Use Resume Watching to continue.")
        else:
            self.callbacks.on_resume()
            self.message_var.set("Watching resumed.")
        self._update_status_controls()

    def _undo_last(self) -> None:
        message = self.callbacks.on_undo_last()
        self.message_var.set(message)
        self._refresh_history()

    def _undo_selected_history(self) -> None:
        record = self._selected_history_record()
        if record is None:
            self.message_var.set("Select a history row first.")
            return
        result = self.history_database.undo_rename(record.id)
        self.message_var.set(result.message)
        self._refresh_history()

    def _open_selected_history(self) -> None:
        record = self._selected_history_record()
        if record is None:
            self.message_var.set("Select a history row first.")
            return
        _open_folder(Path(record.folder_path), record.new_name)

    def _selected_history_record(self) -> RenameRecord | None:
        selected = self.history_tree.selection()
        if not selected:
            return None
        return self.history_records.get(selected[0])

    def _open_watch_folder(self) -> None:
        _open_folder(Path(self.watch_folder_var.get()))

    def _open_destination_folder(self) -> None:
        folder = self.dest_folder_var.get().strip() or self.watch_folder_var.get()
        _open_folder(Path(folder))

    def _quit(self) -> None:
        self.callbacks.on_quit()
        self.destroy()

    def _update_threshold_label(self, value: str) -> None:
        self.threshold_label.configure(text=f"{_safe_float(value, self.confidence_var.get()):.2f}")

    def _update_delay_label(self, value: str) -> None:
        self.delay_label.configure(text=f"{_safe_float(value, self.delay_var.get()):.1f}")


_dashboard_lock = threading.RLock()
_dashboard_window: DashboardWindow | None = None


def open_dashboard_window_threaded(
    settings_manager: SettingsManager,
    history_database: HistoryDatabase,
    callbacks: DashboardCallbacks,
) -> None:
    global _dashboard_window
    with _dashboard_lock:
        if _dashboard_window is not None and _dashboard_window.is_alive():
            _dashboard_window.show_threadsafe()
            return

    def _run() -> None:
        global _dashboard_window
        window = DashboardWindow(settings_manager, history_database, callbacks)
        with _dashboard_lock:
            _dashboard_window = window
        try:
            window.run()
        finally:
            with _dashboard_lock:
                if _dashboard_window is window:
                    _dashboard_window = None

    thread = threading.Thread(
        target=_run,
        name="SnapNameDashboardWindow",
        daemon=True,
    )
    thread.start()


def close_dashboard_window() -> None:
    with _dashboard_lock:
        window = _dashboard_window
    if window is not None and window.is_alive():
        window.destroy_threadsafe()


def _parse_extensions(value: str) -> list[str]:
    extensions: list[str] = []
    for item in re.split(r"[,;\s]+", value):
        extension = item.strip().lower()
        if not extension:
            continue
        if not extension.startswith("."):
            extension = "." + extension
        if extension not in extensions:
            extensions.append(extension)
    return extensions or [".png", ".jpg", ".jpeg"]


def _open_folder(folder: Path, selected_name: str = "") -> None:
    try:
        if selected_name:
            selected_path = folder / selected_name
            if selected_path.exists():
                subprocess.Popen(["explorer", "/select,", str(selected_path)])
                return
        if folder.exists():
            os.startfile(folder)  # type: ignore[attr-defined]
    except OSError as exc:
        LOGGER.exception("Could not open folder: %s", folder)
        messagebox.showerror("SnapName", f"Could not open folder: {exc}")


def _safe_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 3)] + "..."
