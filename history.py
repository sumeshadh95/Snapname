from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from settings import get_app_dir


LOGGER = logging.getLogger(__name__)


CREATE_RENAME_LOG_SQL = """
CREATE TABLE IF NOT EXISTS rename_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    original_name   TEXT NOT NULL,
    new_name        TEXT NOT NULL,
    folder_path     TEXT NOT NULL,
    renamed_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    engine_used     TEXT NOT NULL,
    confidence      REAL,
    was_undone      INTEGER DEFAULT 0,
    keywords_found  TEXT
);
"""

CREATE_APP_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS app_config (
    key     TEXT PRIMARY KEY,
    value   TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class RenameRecord:
    id: int
    original_name: str
    new_name: str
    folder_path: str
    renamed_at: str
    engine_used: str
    confidence: float | None
    was_undone: bool
    keywords_found: list[str]


@dataclass(frozen=True)
class UndoResult:
    success: bool
    message: str
    restored_path: Path | None = None


class HistoryDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or get_app_dir() / "data" / "snapname.db"
        self._lock = threading.RLock()
        self._ensure_schema()

    def log_rename(
        self,
        original_name: str,
        new_name: str,
        folder_path: str,
        engine_used: str,
        confidence: float | None,
        keywords_found: Iterable[str],
    ) -> int:
        keywords_json = json.dumps(list(keywords_found), ensure_ascii=False)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO rename_log (
                    original_name,
                    new_name,
                    folder_path,
                    engine_used,
                    confidence,
                    keywords_found
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    original_name,
                    new_name,
                    folder_path,
                    engine_used,
                    confidence,
                    keywords_json,
                ),
            )
            connection.commit()
            return int(cursor.lastrowid)

    def get_history(self, limit: int = 250) -> list[RenameRecord]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM rename_log
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_last_active(self) -> RenameRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM rename_log
                WHERE was_undone = 0
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return _row_to_record(row) if row is not None else None

    def undo_last_rename(self) -> UndoResult:
        record = self.get_last_active()
        if record is None:
            return UndoResult(False, "No active rename to undo.")
        return self.undo_rename(record.id)

    def undo_rename(self, record_id: int) -> UndoResult:
        with self._lock:
            record = self._get_record(record_id)
            if record is None:
                return UndoResult(False, "Rename record was not found.")
            if record.was_undone:
                return UndoResult(
                    False,
                    "That rename has already been undone.",
                )

            folder = Path(record.folder_path)
            renamed_path = folder / record.new_name
            if not renamed_path.exists():
                return UndoResult(
                    False,
                    f"Cannot undo because {record.new_name} no longer exists.",
                )

            restore_path = _unique_path(folder / record.original_name)
            try:
                renamed_path.rename(restore_path)
            except OSError as exc:
                LOGGER.exception("Failed to undo rename for %s", renamed_path)
                return UndoResult(False, f"Undo failed: {exc}")

            with self._connect() as connection:
                connection.execute(
                    """
                    UPDATE rename_log
                    SET was_undone = 1
                    WHERE id = ?
                    """,
                    (record.id,),
                )
                connection.commit()

            if restore_path.name == record.original_name:
                return UndoResult(
                    True,
                    f"Restored {record.original_name}.",
                    restore_path,
                )
            return UndoResult(
                True,
                (
                    f"Restored as {restore_path.name} because the old name "
                    "existed."
                ),
                restore_path,
            )

    def set_config_value(self, key: str, value: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO app_config (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )
            connection.commit()

    def get_config_value(self, key: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT value
                FROM app_config
                WHERE key = ?
                """,
                (key,),
            ).fetchone()
        return str(row["value"]) if row is not None else None

    def _ensure_schema(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(CREATE_RENAME_LOG_SQL)
            connection.execute(CREATE_APP_CONFIG_SQL)
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _get_record(self, record_id: int) -> RenameRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM rename_log
                WHERE id = ?
                """,
                (record_id,),
            ).fetchone()
        return _row_to_record(row) if row is not None else None


def _row_to_record(row: sqlite3.Row) -> RenameRecord:
    keywords_raw = row["keywords_found"] or "[]"
    try:
        parsed_keywords = json.loads(keywords_raw)
    except json.JSONDecodeError:
        parsed_keywords = []
    keywords = [
        str(keyword)
        for keyword in parsed_keywords
        if isinstance(keyword, (str, int, float))
    ]
    confidence = row["confidence"]
    return RenameRecord(
        id=int(row["id"]),
        original_name=str(row["original_name"]),
        new_name=str(row["new_name"]),
        folder_path=str(row["folder_path"]),
        renamed_at=str(row["renamed_at"]),
        engine_used=str(row["engine_used"]),
        confidence=float(confidence) if confidence is not None else None,
        was_undone=bool(row["was_undone"]),
        keywords_found=keywords,
    )


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(2, 10000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not find a unique restore name for {path}")
