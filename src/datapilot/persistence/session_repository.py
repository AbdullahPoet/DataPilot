import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from datapilot.persistence.sqlite_manager import open_database


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def initialize_sessions(database_path: Path) -> None:
    with open_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                configuration_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_activity_at TEXT NOT NULL,
                is_pinned INTEGER NOT NULL DEFAULT 0 CHECK (is_pinned IN (0, 1))
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_sessions_recent "
            "ON sessions (is_pinned, last_activity_at DESC)"
        )


def create_session(database_path: Path, title: str, configuration: dict[str, object]) -> str:
    if not title.strip():
        raise ValueError("Session title must not be empty")
    serialized_config = json.dumps(configuration, allow_nan=False)
    session_id = uuid4().hex
    timestamp = _utc_now()
    with open_database(database_path) as connection:
        connection.execute(
            "INSERT INTO sessions "
            "(session_id, title, configuration_json, created_at, last_activity_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, title.strip(), serialized_config, timestamp, timestamp),
        )
    return session_id


def get_session(database_path: Path, session_id: str) -> dict[str, object] | None:
    with open_database(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
    return _decode_session(row) if row is not None else None


def list_sessions(database_path: Path) -> list[dict[str, object]]:
    with open_database(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM sessions "
            "ORDER BY is_pinned DESC, last_activity_at DESC, session_id DESC"
        ).fetchall()
    return [_decode_session(row) for row in rows]


def touch_session(database_path: Path, session_id: str) -> None:
    with open_database(database_path) as connection:
        cursor = connection.execute(
            "UPDATE sessions SET last_activity_at = ? WHERE session_id = ?",
            (_utc_now(), session_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Session not found: {session_id}")


def set_pinned(database_path: Path, session_id: str, pinned: bool) -> None:
    with open_database(database_path) as connection:
        cursor = connection.execute(
            "UPDATE sessions SET is_pinned = ? WHERE session_id = ?",
            (int(pinned), session_id),
        )
        if cursor.rowcount == 0:
            raise LookupError(f"Session not found: {session_id}")


def _decode_session(row: sqlite3.Row) -> dict[str, object]:
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "configuration": json.loads(row["configuration_json"]),
        "created_at": row["created_at"],
        "last_activity_at": row["last_activity_at"],
        "is_pinned": bool(row["is_pinned"]),
    }
