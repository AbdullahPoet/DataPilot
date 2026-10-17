from pathlib import Path

import pytest

from datapilot.execution.sql_executor import SQLApprovalRequired, execute_sql
from datapilot.validation.approval_manager import (
    decide_execution_approval,
    request_execution_approval,
)
from datapilot.validation.sql_validator import SQLValidationError, validate_sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM sales", "SELECT * FROM sales; DROP TABLE sales",
    "SELECT * INTO stolen FROM sales", "SELECT load_extension('evil')",
    "SELECT writefile('file', 'data')", "SELECT unknown_udf()",
    "WITH changed AS (DELETE FROM sales RETURNING *) SELECT * FROM changed",
    "SELECT FROM", "SELECT pg_catalog.pg_read_file('/etc/passwd')",
])
def test_reject_unsafe_sql(sql: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_sql(sql, "sqlite")


def test_sql_approval_and_readonly_execution(session: tuple[Path, str], source: str) -> None:
    database, session_id = session
    options = {
        "connection_url": source, "approval_database_path": database,
        "session_id": session_id, "source_id": "sales", "sql": "SELECT SUM(amount) AS total FROM sales",
    }
    with pytest.raises(SQLApprovalRequired):
        execute_sql(**options)
    decide_execution_approval(database, session_id, "sales", options["sql"], True)
    result = execute_sql(**options)
    assert result.rows == ((60,),)
    assert result.columns == ("total",)
    assert execute_sql(**{**options, "sql": "SELECT ':literal' AS text"}).rows == ((":literal",),)
    with pytest.raises(SQLValidationError):
        execute_sql(**{**options, "sql": "DELETE FROM sales"})
    with pytest.raises(SQLApprovalRequired):
        execute_sql(**{**options, "source_id": "other"})


def test_rejection_survives_source_approval(session: tuple[Path, str]) -> None:
    database, session_id = session
    for query, decision in [("SELECT 1", False), ("SELECT 2", True)]:
        request_execution_approval(database, session_id, "sales", query)
        decide_execution_approval(database, session_id, "sales", query, decision)
    assert request_execution_approval(database, session_id, "sales", "SELECT 1") == "rejected"

