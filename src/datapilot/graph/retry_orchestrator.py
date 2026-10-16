from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from datapilot.agents.sql_agent import SQLDialect
from datapilot.agents.sql_repair_agent import repair_sql
from datapilot.execution.sql_executor import (
    SQLApprovalRequired,
    SQLExecutionError,
    SQLExecutionResult,
    execute_sql,
)
from datapilot.validation.sql_validator import validate_sql


@dataclass(frozen=True, slots=True)
class SQLRetryAttempt:
    sql: str
    error_category: str | None


@dataclass(frozen=True, slots=True)
class SQLRetryResult:
    result: SQLExecutionResult
    executed_sql: str
    repairs_used: int
    attempts: tuple[SQLRetryAttempt, ...]


class SQLRetryExhausted(RuntimeError):
    def __init__(self, attempts: tuple[SQLRetryAttempt, ...]) -> None:
        super().__init__("SQL execution failed after the permitted repair attempts")
        self.attempts = attempts


_RECOVERABLE_ERRORS = {
    "no such table": "missing table",
    "no such column": "missing column",
    "does not exist": "missing database object",
    "unknown column": "missing column",
    "undefined table": "missing table",
    "undefined column": "missing column",
    "ambiguous column": "ambiguous column",
    "syntax error": "SQL syntax error",
    "near \"": "SQL syntax error",
    "not a group by expression": "grouping error",
    "must appear in the group by": "grouping error",
    "misuse of aggregate": "aggregation error",
}

_NONRECOVERABLE_ERRORS = (
    "permission denied",
    "access denied",
    "not authorized",
    "authentication",
    "password",
    "connection refused",
    "connection timed out",
    "statement timeout",
    "query timeout",
    "interrupted",
    "database is locked",
    "read-only",
    "readonly",
    "canceling statement",
    "disk full",
    "out of memory",
)


def _classify_failure(error: SQLExecutionError) -> str | None:
    cause = error.__cause__
    if cause is None:
        return None
    message = str(cause).lower()
    if any(pattern in message for pattern in _NONRECOVERABLE_ERRORS):
        return None
    return next(
        (category for pattern, category in _RECOVERABLE_ERRORS.items() if pattern in message),
        None,
    )


def execute_with_sql_repair(
    *,
    connection_url: str,
    approval_database_path: Path,
    session_id: str,
    source_id: str,
    sql: str,
    user_query: str,
    schema_markdown: str,
    dialect: SQLDialect,
    model_configuration: Mapping[str, str | int],
    skill_instructions: str = "",
    max_repairs: int = 3,
    timeout_seconds: float = 30.0,
    max_rows: int = 1000,
) -> SQLRetryResult:
    if not isinstance(max_repairs, int) or isinstance(max_repairs, bool) or not 0 <= max_repairs <= 3:
        raise ValueError("max_repairs must be an integer between 0 and 3")
    for label, value in (("sql", sql), ("user_query", user_query), ("schema_markdown", schema_markdown)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{label} must be non-empty text")
    if not isinstance(skill_instructions, str):
        raise TypeError("skill_instructions must be text")

    current_sql = sql.strip()
    attempts: list[SQLRetryAttempt] = []
    seen = {current_sql}

    for repair_count in range(max_repairs + 1):
        validate_sql(current_sql, dialect)
        try:
            result = execute_sql(
                connection_url=connection_url,
                approval_database_path=approval_database_path,
                session_id=session_id,
                source_id=source_id,
                sql=current_sql,
                timeout_seconds=timeout_seconds,
                max_rows=max_rows,
            )
        except SQLApprovalRequired:
            raise
        except SQLExecutionError as error:
            category = _classify_failure(error)
            attempts.append(SQLRetryAttempt(sql=current_sql, error_category=category))
            if category is None:
                raise
            if repair_count == max_repairs:
                raise SQLRetryExhausted(tuple(attempts)) from error
            repaired = repair_sql(
                user_query=user_query,
                original_sql=current_sql,
                error_details=category,
                schema_markdown=schema_markdown,
                dialect=dialect,
                model_configuration=model_configuration,
                skill_instructions=skill_instructions,
            )
            candidate = repaired.sql.strip()
            if candidate in seen:
                raise SQLRetryExhausted(tuple(attempts)) from error
            validate_sql(candidate, dialect)
            current_sql = candidate
            seen.add(current_sql)
        else:
            attempts.append(SQLRetryAttempt(sql=current_sql, error_category=None))
            return SQLRetryResult(
                result=result,
                executed_sql=current_sql,
                repairs_used=repair_count,
                attempts=tuple(attempts),
            )

    raise RuntimeError("Unexpected SQL retry state")
