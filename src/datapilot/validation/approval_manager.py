import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from datapilot.persistence.sqlite_manager import open_database

ApprovalDecision = Literal["pending", "approved", "rejected"]


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _query_digest(query: str) -> str:
    return hashlib.sha256(_required_text(query, "query").encode("utf-8")).hexdigest()


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


def initialize_approvals(database_path: Path) -> None:
    with open_database(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_approvals (
                session_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                query_digest TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                decided_at TEXT,
                PRIMARY KEY (session_id, source_id, query_digest),
                FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_approvals_source "
            "ON execution_approvals(session_id, source_id, status)"
        )


def _ensure_session(connection: sqlite3.Connection, session_id: str) -> None:
    if (
        connection.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        is None
    ):
        raise LookupError(f"Session not found: {session_id}")


def request_execution_approval(
    database_path: Path,
    session_id: str,
    source_id: str,
    query: str,
    *,
    require_review: bool = False,
) -> ApprovalDecision:
    session_id = _required_text(session_id, "session_id")
    source_id = _required_text(source_id, "source_id")
    digest = _query_digest(query)
    with open_database(database_path) as connection:
        _ensure_session(connection, session_id)
        existing = connection.execute(
            "SELECT status FROM execution_approvals "
            "WHERE session_id = ? AND source_id = ? AND query_digest = ?",
            (session_id, source_id, digest),
        ).fetchone()
        if existing is not None:
            if require_review and existing["status"] == "approved":
                connection.execute(
                    "UPDATE execution_approvals SET status = 'pending', decided_at = NULL "
                    "WHERE session_id = ? AND source_id = ? AND query_digest = ?",
                    (session_id, source_id, digest),
                )
                return "pending"
            return existing["status"]
        authorized = connection.execute(
            "SELECT 1 FROM execution_approvals "
            "WHERE session_id = ? AND source_id = ? AND status = 'approved' LIMIT 1",
            (session_id, source_id),
        ).fetchone()
        if authorized is not None and not require_review:
            return "approved"
        connection.execute(
            "INSERT INTO execution_approvals "
            "(session_id, source_id, query_digest, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (session_id, source_id, digest, _timestamp()),
        )
    return "pending"


def decide_execution_approval(
    database_path: Path,
    session_id: str,
    source_id: str,
    query: str,
    approve: bool,
) -> ApprovalDecision:
    session_id = _required_text(session_id, "session_id")
    source_id = _required_text(source_id, "source_id")
    digest = _query_digest(query)
    if not isinstance(approve, bool):
        raise TypeError("approve must be a boolean")
    decision: ApprovalDecision = "approved" if approve else "rejected"
    with open_database(database_path) as connection:
        _ensure_session(connection, session_id)
        cursor = connection.execute(
            "UPDATE execution_approvals SET status = ?, decided_at = ? "
            "WHERE session_id = ? AND source_id = ? AND query_digest = ? "
            "AND status = 'pending'",
            (decision, _timestamp(), session_id, source_id, digest),
        )
        if cursor.rowcount != 1:
            raise ValueError("No pending approval exists for this session, source, and query")
    return decision


def can_execute_query(database_path: Path, session_id: str, source_id: str, query: str) -> bool:
    session_id = _required_text(session_id, "session_id")
    source_id = _required_text(source_id, "source_id")
    digest = _query_digest(query)
    with open_database(database_path) as connection:
        _ensure_session(connection, session_id)
        row = connection.execute(
            "SELECT status FROM execution_approvals "
            "WHERE session_id = ? AND source_id = ? AND query_digest = ?",
            (session_id, source_id, digest),
        ).fetchone()
        if row is not None:
            return row["status"] == "approved"
        return (
            connection.execute(
                "SELECT 1 FROM execution_approvals "
                "WHERE session_id = ? AND source_id = ? AND status = 'approved' LIMIT 1",
                (session_id, source_id),
            ).fetchone()
            is not None
        )
