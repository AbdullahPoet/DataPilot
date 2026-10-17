import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from datapilot.connections.connection_manager import parse_connection_url
from datapilot.validation.approval_manager import (
    can_execute_query,
    request_execution_approval,
)
from datapilot.validation.sql_validator import validate_sql


class SQLExecutionError(RuntimeError):
    pass


class SQLApprovalRequired(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class SQLExecutionResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    row_count: int
    truncated: bool
    elapsed_seconds: float


def _create_readonly_engine(connection_url: str, timeout_seconds: float) -> Engine:
    url = parse_connection_url(connection_url)
    dialect = url.get_backend_name()
    if dialect == "sqlite":
        database = Path(url.database or "").expanduser().resolve(strict=True)
        uri = f"file:{quote(str(database), safe='/')}?mode=ro"

        def connect_sqlite() -> sqlite3.Connection:
            connection = sqlite3.connect(uri, uri=True, timeout=timeout_seconds)
            connection.execute("PRAGMA query_only=ON")
            deadline = time.monotonic() + timeout_seconds
            connection.set_progress_handler(
                lambda: 1 if time.monotonic() >= deadline else 0, 1000
            )
            return connection

        return create_engine("sqlite://", creator=connect_sqlite)
    if dialect == "postgresql":
        return create_engine(
            url,
            connect_args={"connect_timeout": max(1, int(timeout_seconds))},
        )
    return create_engine(
        url,
        connect_args={"connect_timeout": max(1, int(timeout_seconds))},
    )


def execute_sql(
    *,
    connection_url: str,
    approval_database_path: Path,
    session_id: str,
    source_id: str,
    sql: str,
    timeout_seconds: float = 30.0,
    max_rows: int = 1000,
) -> SQLExecutionResult:
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (int, float)) or not 0 < timeout_seconds <= 3600:
        raise ValueError("timeout_seconds must be between 0 and 3600")
    if not isinstance(max_rows, int) or isinstance(max_rows, bool) or not 1 <= max_rows <= 100000:
        raise ValueError("max_rows must be between 1 and 100000")

    url = parse_connection_url(connection_url)
    dialect = url.get_backend_name()
    validated = validate_sql(sql, dialect)
    status = request_execution_approval(
        approval_database_path, session_id, source_id, sql
    )
    if status == "rejected":
        raise PermissionError("Execution of this SQL query was rejected")
    if status != "approved" or not can_execute_query(
        approval_database_path, session_id, source_id, sql
    ):
        raise SQLApprovalRequired("User approval is required before SQL execution")

    engine = _create_readonly_engine(connection_url, float(timeout_seconds))
    start = time.monotonic()
    try:
        with engine.connect() as connection:
            if dialect == "postgresql":
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{int(timeout_seconds * 1000)}ms"},
                )
            elif dialect == "mysql":
                connection.exec_driver_sql(
                    f"SET SESSION MAX_EXECUTION_TIME = {int(timeout_seconds * 1000)}"
                )
                connection.commit()
                connection.exec_driver_sql("START TRANSACTION READ ONLY")
            result = connection.exec_driver_sql(validated.sql)
            columns = tuple(map(str, result.keys()))
            fetched = result.fetchmany(max_rows + 1)
            rows = tuple(tuple(row) for row in fetched[:max_rows])
            connection.rollback()
    except (SQLAlchemyError, sqlite3.Error, TimeoutError, OSError) as error:
        raise SQLExecutionError("Read-only SQL execution failed or timed out") from error
    finally:
        engine.dispose()
    return SQLExecutionResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=len(fetched) > max_rows,
        elapsed_seconds=time.monotonic() - start,
    )
