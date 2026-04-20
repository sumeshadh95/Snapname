from __future__ import annotations

import logging
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from settings import SettingsManager


LOGGER = logging.getLogger(__name__)
SaveCallback = Callable[[], None]


class SettingsWindow:
    def __init__(
        self,
        settings_manager: SettingsManager,
        on_save: SaveCallback | None = None,
    ) -> None:
        self.settings_manager = settings_manager
        self.on_save = on_save
        self.root = tk.Tk()
        self.root.title("SnapName Settings")
        self.root.resizable(False, False)
        self.folder_var = tk.StringVar()
        self.dest_folder_var = tk.StringVar()
        self.prefix_var = tk.StringVar()
        self.append_timestamp_var = tk.BooleanVar()
        self.use_active_window_var = tk.BooleanVar()
        self.engine_var = tk.StringVar()
        self.confidence_var = tk.DoubleVar()
        self.status_var = tk.StringVar(value="")
        self._load_values()
        self._build_ui()

    def run(self) -> None:
        self.root.mainloop()

    def _load_values(self) -> None:
        settings = self.settings_manager.load()
        self.folder_var.set(settings.watch_folder)
        self.dest_folder_var.set(settings.destination_folder)
        self.prefix_var.set(settings.prefix)
        self.append_timestamp_var.set(settings.append_timestamp)
        self.use_active_window_var.set(settings.use_active_window)
        engine_name = "LLaVA" if settings.engine == "llava" else "Tesseract"
        self.engine_var.set(engine_name)
        self.confidence_var.set(settings.confidence_threshold)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")

        ttk.Label(frame, text="Watch folder").grid(row=0, column=0, sticky="w")
        folder_entry = ttk.Entry(frame, textvariable=self.folder_var, width=56)
        folder_entry.grid(row=1, column=0, sticky="ew", pady=(4, 12))
        ttk.Button(frame, text="Browse", command=self._browse_watch).grid(
            row=1,
            column=1,
            padx=(8, 0),
            pady=(4, 12),
        )

        ttk.Label(frame, text="Destination folder (leave empty = same folder)").grid(
            row=2, column=0, sticky="w"
        )
        dest_entry = ttk.Entry(frame, textvariable=self.dest_folder_var, width=56)
        dest_entry.grid(row=3, column=0, sticky="ew", pady=(4, 4))
        dest_btn_frame = ttk.Frame(frame)
        dest_btn_frame.grid(row=3, column=1, padx=(8, 0), pady=(4, 4))
        ttk.Button(dest_btn_frame, text="Browse", command=self._browse_dest).grid(
            row=0, column=0,
        )
        ttk.Button(dest_btn_frame, text="Clear", command=self._clear_dest, width=5).grid(
            row=0, column=1, padx=(4, 0),
        )

        ttk.Label(frame, text="Filename prefix").grid(
            row=4,
            column=0,
            sticky="w",
        )
        ttk.Entry(frame, textvariable=self.prefix_var, width=28).grid(
            row=5,
            column=0,
            sticky="w",
            pady=(4, 12),
        )

        ttk.Checkbutton(
            frame,
            text="Append timestamp",
            variable=self.append_timestamp_var,
        ).grid(row=6, column=0, sticky="w", pady=(0, 4))

        ttk.Checkbutton(
            frame,
            text="Use active window title for smarter names",
            variable=self.use_active_window_var,
        ).grid(row=7, column=0, sticky="w", pady=(0, 12))

        ttk.Label(frame, text="Engine").grid(row=8, column=0, sticky="w")
        engine_dropdown = ttk.Combobox(
            frame,
            textvariable=self.engine_var,
            values=("Tesseract", "LLaVA"),
            state="readonly",
            width=20,
        )
        engine_dropdown.grid(row=9, column=0, sticky="w", pady=(4, 12))

        ttk.Label(frame, text="Confidence threshold").grid(
            row=10,
            column=0,
            sticky="w",
        )
        threshold_frame = ttk.Frame(frame)
        threshold_frame.grid(
            row=11,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(4, 12),
        )
        scale = ttk.Scale(
            threshold_frame,
            from_=0.1,
            to=0.9,
            variable=self.confidence_var,
            orient="horizontal",
            length=280,
            command=self._update_threshold_label,
        )
        scale.grid(row=0, column=0, sticky="ew")
        self.threshold_label = ttk.Label(threshold_frame, width=5)
        self.threshold_label.grid(row=0, column=1, padx=(8, 0))
        self._update_threshold_label(str(self.confidence_var.get()))

        ttk.Label(
            frame,
            textvariable=self.status_var,
            foreground="#555555",
        ).grid(
            row=12,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(0, 12),
        )

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=13, column=0, columnspan=2, sticky="e")
        ttk.Button(
            button_frame,
            text="Cancel",
            command=self.root.destroy,
        ).grid(
            row=0,
            column=0,
            padx=(0, 8),
        )
        ttk.Button(button_frame, text="Save", command=self._save).grid(
            row=0,
            column=1,
        )

    def _browse_watch(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose screenshot folder",
            initialdir=self.folder_var.get() or None,
        )
        if folder:
            self.folder_var.set(folder)

    def _browse_dest(self) -> None:
        folder = filedialog.askdirectory(
            title="Choose destination folder",
            initialdir=self.dest_folder_var.get() or self.folder_var.get() or None,
        )
        if folder:
            self.dest_folder_var.set(folder)

    def _clear_dest(self) -> None:
        self.dest_folder_var.set("")

    def _save(self) -> None:
        engine = (
            "llava"
            if self.engine_var.get().lower() == "llava"
            else "tesseract"
        )
        try:
            self.settings_manager.update(
                watch_folder=self.folder_var.get(),
                destination_folder=self.dest_folder_var.get(),
                prefix=self.prefix_var.get(),
                append_timestamp=self.append_timestamp_var.get(),
                use_active_window=self.use_active_window_var.get(),
                engine=engine,
                confidence_threshold=round(
                    float(self.confidence_var.get()),
                    2,
                ),
            )
            if self.on_save is not None:
                self.on_save()
        except Exception as exc:
            LOGGER.exception("Failed to save settings")
            messagebox.showerror(
                "SnapName",
                f"Settings could not be saved: {exc}",
            )
            return

        self.status_var.set("Settings saved.")
        messagebox.showinfo("SnapName", "Settings saved.")
        self.root.destroy()

    def _update_threshold_label(self, value: str) -> None:
        try:
            threshold = float(value)
        except ValueError:
            threshold = self.confidence_var.get()
        self.threshold_label.configure(text=f"{threshold:.2f}")


def open_settings_window(
    settings_manager: SettingsManager,
    on_save: SaveCallback | None = None,
) -> None:
    window = SettingsWindow(settings_manager, on_save)
    window.run()


def open_settings_window_threaded(
    settings_manager: SettingsManager,
    on_save: SaveCallback | None = None,
) -> None:
    thread = threading.Thread(
        target=open_settings_window,
        args=(settings_manager, on_save),
        name="SnapNameSettingsWindow",
        daemon=True,
    )
    thread.start()
