import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import pandas as pd

from datapilot.execution.pandas_executor import PandasExecutionResult
from datapilot.execution.sql_executor import SQLExecutionResult
from datapilot.persistence.sqlite_manager import open_database


ResultKind = Literal["sql", "pandas"]


class ResultRepositoryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredResult:
    result_id: str
    session_id: str
    source_id: str
    kind: ResultKind
    created_at: str
    path: Path
    row_count: int
    truncated: bool


def _identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ResultRepositoryError(f"Invalid {name}")
    return value


def _encode_value(value: Any) -> Any:
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return {"type": "datetime", "value": value.isoformat()}
    if isinstance(value, Decimal):
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, bytes):
        return {"type": "bytes", "value": value.hex()}
    if isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not pd.notna(value):
            return None
        return value
    if hasattr(value, "item"):
        return _encode_value(value.item())
    raise ResultRepositoryError(f"Unsupported result value type: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    if set(value) != {"type", "value"} or not isinstance(value["value"], str):
        raise ResultRepositoryError("Invalid encoded result value")
    if value["type"] == "datetime":
        return datetime.fromisoformat(value["value"])
    if value["type"] == "decimal":
        return Decimal(value["value"])
    if value["type"] == "bytes":
        return bytes.fromhex(value["value"])
    raise ResultRepositoryError("Unsupported encoded result value")


def _payload(result: SQLExecutionResult | PandasExecutionResult) -> dict[str, Any]:
    if isinstance(result, SQLExecutionResult):
        columns = result.columns
        rows = result.rows
        kind: ResultKind = "sql"
    elif isinstance(result, PandasExecutionResult):
        columns = result.columns
        rows = result.dataframe.itertuples(index=False, name=None)
        kind = "pandas"
    else:
        raise TypeError("Expected SQLExecutionResult or PandasExecutionResult")
    if len(set(columns)) != len(columns) or any(not isinstance(name, str) for name in columns):
        raise ResultRepositoryError("Result columns must be unique strings")
    encoded_rows = [[_encode_value(cell) for cell in row] for row in rows]
    if any(len(row) != len(columns) for row in encoded_rows):
        raise ResultRepositoryError("Result row does not match column count")
    if result.row_count != len(encoded_rows):
        raise ResultRepositoryError("Result row count mismatch")
    return {
        "version": 1,
        "kind": kind,
        "columns": list(columns),
        "rows": encoded_rows,
        "row_count": result.row_count,
        "truncated": result.truncated,
    }


def _atomic_write(path: Path, content: bytes) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".result_", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def initialize_results(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with open_database(database_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS analysis_results ("
            "result_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
            "source_id TEXT NOT NULL, kind TEXT NOT NULL, "
            "created_at TEXT NOT NULL, relative_path TEXT NOT NULL, "
            "sha256 TEXT NOT NULL, row_count INTEGER NOT NULL, "
            "truncated INTEGER NOT NULL)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_analysis_results_session "
            "ON analysis_results (session_id, created_at DESC)"
        )


def _directory(root: Path, session_id: str) -> Path:
    base = root.resolve()
    target = base / session_id / "results"
    for path in (base, base / session_id, target):
        if path.is_symlink():
            raise ResultRepositoryError("Artifact directory cannot be a symbolic link")
    target.mkdir(parents=True, exist_ok=True)
    return target


def save_result(
    result: SQLExecutionResult | PandasExecutionResult,
    *,
    database_path: Path,
    artifacts_directory: Path,
    session_id: str,
    source_id: str,
) -> StoredResult:
    session_id = _identifier(session_id, "session_id")
    source_id = _identifier(source_id, "source_id")
    data = _payload(result)
    content = json.dumps(data, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    identifier = uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    relative_path = Path(session_id) / "results" / f"{identifier}.json"
    destination = _directory(Path(artifacts_directory), session_id) / f"{identifier}.json"
    initialize_results(Path(database_path))
    _atomic_write(destination, content)
    try:
        with open_database(Path(database_path)) as connection:
            connection.execute(
                "INSERT INTO analysis_results "
                "(result_id, session_id, source_id, kind, created_at, relative_path, sha256, row_count, truncated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    identifier, session_id, source_id, data["kind"], created_at,
                    relative_path.as_posix(), hashlib.sha256(content).hexdigest(),
                    data["row_count"], int(data["truncated"]),
                ),
            )
    except sqlite3.Error:
        destination.unlink(missing_ok=True)
        raise
    return StoredResult(
        identifier, session_id, source_id, data["kind"], created_at,
        destination, data["row_count"], data["truncated"],
    )


def list_results(database_path: Path, session_id: str, artifacts_directory: Path) -> list[StoredResult]:
    session_id = _identifier(session_id, "session_id")
    initialize_results(Path(database_path))
    with open_database(Path(database_path)) as connection:
        rows = connection.execute(
            "SELECT * FROM analysis_results WHERE session_id = ? "
            "ORDER BY created_at DESC, result_id DESC", (session_id,)
        ).fetchall()
    root = Path(artifacts_directory).resolve()
    return [
        StoredResult(
            row["result_id"], row["session_id"], row["source_id"], row["kind"],
            row["created_at"], root / row["relative_path"],
            row["row_count"], bool(row["truncated"]),
        )
        for row in rows
    ]


def load_result(
    *, database_path: Path, artifacts_directory: Path, session_id: str, result_id: str
) -> SQLExecutionResult | PandasExecutionResult:
    session_id = _identifier(session_id, "session_id")
    result_id = _identifier(result_id, "result_id")
    initialize_results(Path(database_path))
    with open_database(Path(database_path)) as connection:
        record = connection.execute(
            "SELECT * FROM analysis_results WHERE session_id = ? AND result_id = ?",
            (session_id, result_id),
        ).fetchone()
    if record is None:
        raise LookupError("Result not found for this session")
    base = Path(artifacts_directory).resolve()
    expected = base / session_id / "results" / f"{result_id}.json"
    if record["relative_path"] != (Path(session_id) / "results" / f"{result_id}.json").as_posix():
        raise ResultRepositoryError("Invalid result artifact reference")
    if expected.is_symlink() or expected.parent.is_symlink():
        raise ResultRepositoryError("Symlink result artifact is not allowed")
    content = expected.read_bytes()
    if hashlib.sha256(content).hexdigest() != record["sha256"]:
        raise ResultRepositoryError("Result artifact checksum mismatch")
    data = json.loads(content)
    if data["version"] != 1 or data["kind"] != record["kind"]:
        raise ResultRepositoryError("Result format mismatch")
    columns = tuple(data["columns"])
    rows = tuple(tuple(_decode_value(cell) for cell in row) for row in data["rows"])
    if len(set(columns)) != len(columns) or any(len(row) != len(columns) for row in rows):
        raise ResultRepositoryError("Invalid stored result shape")
    if data["row_count"] != len(rows) or data["row_count"] != record["row_count"]:
        raise ResultRepositoryError("Stored result count mismatch")
    if bool(data["truncated"]) != bool(record["truncated"]):
        raise ResultRepositoryError("Stored truncation mismatch")
    if data["kind"] == "sql":
        return SQLExecutionResult(columns, rows, len(rows), bool(data["truncated"]), 0.0)
    if data["kind"] == "pandas":
        return PandasExecutionResult(
            pd.DataFrame(rows, columns=columns), len(rows), columns, 0,
            bool(data["truncated"]),
        )
    raise ResultRepositoryError("Unknown result kind")
