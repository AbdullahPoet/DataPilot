import json
from pathlib import Path
from typing import Any

from datapilot.persistence.sqlite_manager import open_database


def initialize_evidence(database: Path) -> None:
    with open_database(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS analysis_evidence ("
            "result_id TEXT PRIMARY KEY REFERENCES analysis_results(result_id), "
            "session_id TEXT NOT NULL REFERENCES sessions(session_id), payload TEXT NOT NULL)"
        )


def save_evidence(database: Path, session_id: str, result_id: str, payload: dict[str, Any]) -> None:
    with open_database(database) as connection:
        record = connection.execute(
            "SELECT source_id, row_count, truncated, created_at FROM analysis_results "
            "WHERE result_id = ? AND session_id = ?",
            (result_id, session_id),
        ).fetchone()
        if record is None:
            raise LookupError("Result does not belong to this session")
        content = {**payload, **dict(record), "result_id": result_id}
        connection.execute(
            "INSERT OR IGNORE INTO analysis_evidence VALUES (?, ?, ?)",
            (result_id, session_id, json.dumps(content, allow_nan=False)),
        )


def load_evidence(database: Path, session_id: str, result_id: str) -> dict[str, Any] | None:
    with open_database(database) as connection:
        row = connection.execute(
            "SELECT payload FROM analysis_evidence WHERE session_id = ? AND result_id = ?",
            (session_id, result_id),
        ).fetchone()
    return json.loads(row["payload"]) if row else None
