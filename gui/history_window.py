from __future__ import annotations

import logging
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from history import HistoryDatabase, RenameRecord


LOGGER = logging.getLogger(__name__)


class HistoryWindow:
    def __init__(self, history_database: HistoryDatabase) -> None:
        self.history_database = history_database
        self.root = tk.Tk()
        self.root.title("SnapName Rename History")
        self.root.geometry("920x520")
        self.container: ttk.Frame | None = None
        self._build_ui()
        self._populate_rows()

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(
            header,
            text="Old Name",
            width=25,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="New Name",
            width=28,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=1, sticky="w")
        ttk.Label(
            header,
            text="Time",
            width=19,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=2, sticky="w")
        ttk.Label(
            header,
            text="Engine",
            width=10,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=3, sticky="w")
        ttk.Label(
            header,
            text="Confidence",
            width=11,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=4, sticky="w")
        ttk.Label(
            header,
            text="Actions",
            width=18,
            anchor="w",
            font=("Segoe UI", 9, "bold"),
        ).grid(row=0, column=5, sticky="w")

        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(
            outer,
            orient="vertical",
            command=canvas.yview,
        )
        self.container = ttk.Frame(canvas)
        self.container.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self.container, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        footer = ttk.Frame(self.root, padding=(12, 0, 12, 12))
        footer.pack(fill="x")
        ttk.Button(
            footer,
            text="Refresh",
            command=self._populate_rows,
        ).pack(side="left")
        ttk.Button(
            footer,
            text="Close",
            command=self.root.destroy,
        ).pack(side="right")

    def _populate_rows(self) -> None:
        if self.container is None:
            return
        for child in self.container.winfo_children():
            child.destroy()

        records = self.history_database.get_history(limit=300)
        if not records:
            ttk.Label(
                self.container,
                text="No renamed screenshots yet.",
                padding=(4, 16),
            ).grid(row=0, column=0, sticky="w")
            return

        for row_index, record in enumerate(records):
            self._add_row(row_index, record)

    def _add_row(self, row_index: int, record: RenameRecord) -> None:
        if self.container is None:
            return
        row = ttk.Frame(self.container, padding=(0, 3))
        row.grid(row=row_index, column=0, sticky="ew")

        values = (
            _shorten(record.original_name, 30),
            _shorten(record.new_name, 34),
            record.renamed_at,
            record.engine_used,
            _format_confidence(record.confidence),
        )
        widths = (25, 28, 19, 10, 11)
        for column, value in enumerate(values):
            ttk.Label(row, text=value, width=widths[column], anchor="w").grid(
                row=0,
                column=column,
                sticky="w",
            )

        actions = ttk.Frame(row)
        actions.grid(row=0, column=5, sticky="w")
        undo_state = "disabled" if record.was_undone else "normal"
        ttk.Button(
            actions,
            text="Undo",
            command=lambda item=record: self._undo(item),
            state=undo_state,
            width=7,
        ).grid(row=0, column=0, padx=(0, 4))
        ttk.Button(
            actions,
            text="Open Folder",
            command=lambda item=record: self._open_folder(item),
            width=12,
        ).grid(row=0, column=1)

    def _undo(self, record: RenameRecord) -> None:
        result = self.history_database.undo_rename(record.id)
        if result.success:
            messagebox.showinfo("SnapName", result.message)
            self._populate_rows()
        else:
            messagebox.showwarning("SnapName", result.message)

    def _open_folder(self, record: RenameRecord) -> None:
        folder = Path(record.folder_path)
        target = folder / record.new_name
        try:
            if target.exists():
                subprocess.Popen(["explorer", "/select,", str(target)])
            else:
                os.startfile(folder)
        except OSError as exc:
            LOGGER.exception("Could not open Explorer for %s", folder)
            messagebox.showerror("SnapName", f"Could not open folder: {exc}")


def open_history_window(history_database: HistoryDatabase) -> None:
    window = HistoryWindow(history_database)
    window.run()


def open_history_window_threaded(history_database: HistoryDatabase) -> None:
    thread = threading.Thread(
        target=open_history_window,
        args=(history_database,),
        name="SnapNameHistoryWindow",
        daemon=True,
    )
    thread.start()


def _shorten(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 3)] + "..."


def _format_confidence(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
