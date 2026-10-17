import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from datapilot.execution.sql_executor import SQLExecutionResult


@dataclass(frozen=True, slots=True)
class ExecutionLog:
    path: Path
    timestamp: datetime


def _identifier(value: str, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", value):
        raise ValueError(f"{field} must contain 1-128 letters, digits, underscores or hyphens")
    return value


def _description(value: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", value.lower())[:8]
    return "_".join(words)[:60] or "sql_query"


def log_successful_sql_execution(
    *,
    logs_directory: Path,
    session_id: str,
    source_id: str,
    sql: str,
    result: SQLExecutionResult,
    description: str = "sql query",
    artifact_references: Iterable[str] = (),
    timestamp: datetime | None = None,
) -> ExecutionLog:
    session = _identifier(session_id, "session_id")
    source = _identifier(source_id, "source_id")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("sql must not be empty")
    if not isinstance(result, SQLExecutionResult):
        raise TypeError("result must be a successful SQLExecutionResult")
    if not isinstance(description, str):
        raise TypeError("description must be text")
    if not isinstance(logs_directory, Path):
        raise TypeError("logs_directory must be a Path")
    instant = timestamp or datetime.now(UTC)
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    instant = instant.astimezone(UTC)
    references = tuple(artifact_references)
    if any(not isinstance(reference, str) or not reference.strip() for reference in references):
        raise ValueError("artifact references must be nonempty strings")
    if any("\n" in reference or "\r" in reference for reference in references):
        raise ValueError("artifact references must not contain line breaks")
    if result.row_count != len(result.rows):
        raise ValueError("result row count does not match returned rows")
    target_directory = logs_directory / session
    target_directory.mkdir(parents=True, exist_ok=True)
    name = f"{instant:%Y%m%dT%H%M%S_%fZ}_{_description(description)}_{uuid4().hex[:12]}.txt"
    path = target_directory / name
    content = "\n".join(
        [
            "DataPilot SQL Execution Log",
            f"Timestamp (UTC): {instant.isoformat()}",
            f"Session ID: {session}",
            f"Source ID: {source}",
            "Status: succeeded",
            f"Description: {description.strip()}",
            f"Execution Time (seconds): {result.elapsed_seconds:.6f}",
            f"Returned Rows: {result.row_count}",
            f"Result Truncated: {str(result.truncated).lower()}",
            f"Columns: {', '.join(result.columns)}",
            "Artifact References:",
            *(f"- {reference}" for reference in references),
            "SQL:",
            sql.strip(),
            "",
        ]
    )
    with path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)
    return ExecutionLog(path=path, timestamp=instant)
