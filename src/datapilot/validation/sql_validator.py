from dataclasses import dataclass
from typing import Literal

from sqlglot import exp, parse
from sqlglot.errors import ErrorLevel, ParseError

SQLDialect = Literal["sqlite", "postgresql", "mysql"]
SUPPORTED_DIALECTS = frozenset({"sqlite", "postgresql", "mysql"})


class SQLValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SQLValidationResult:
    sql: str
    dialect: SQLDialect
    referenced_tables: tuple[str, ...]


def validate_sql(sql: str, dialect: SQLDialect) -> SQLValidationResult:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL must be a non-empty string")
    if dialect not in SUPPORTED_DIALECTS:
        raise SQLValidationError("Unsupported SQL dialect")

    try:
        statements = parse(sql, read=dialect, error_level=ErrorLevel.RAISE)
    except (ParseError, ValueError) as error:
        raise SQLValidationError("SQL could not be parsed for the selected dialect") from error

    if len(statements) != 1 or statements[0] is None:
        raise SQLValidationError("Exactly one SQL statement is required")

    statement = statements[0]
    if not isinstance(statement, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
        raise SQLValidationError("Only read-only SELECT queries and set operations are allowed")

    prohibited = (
        "Insert", "Update", "Delete", "Drop", "Create", "Alter", "Merge",
        "TruncateTable", "Grant", "Revoke", "Command", "Execute", "Copy",
        "Set", "Use", "Transaction", "Commit", "Rollback", "Pragma",
        "Attach", "Detach", "Into", "Lock", "ForUpdate", "TableSample",
    )
    prohibited_types = tuple(
        node_type for name in prohibited
        if (node_type := getattr(exp, name, None)) is not None
    )

    unsafe_functions = {
        "pg_sleep", "sleep", "benchmark", "load_file", "sys_eval", "sys_exec",
        "dblink_exec", "lo_import", "lo_export", "pg_read_file", "pg_write_file",
        "pg_read_binary_file", "pg_ls_dir", "set_config", "nextval", "setval",
        "load_extension", "readfile", "writefile", "pg_stat_file",
    }
    anonymous_functions = {
        "strftime", "julianday", "date", "time", "datetime", "unixepoch",
        "timediff", "printf", "format", "typeof", "instr", "ifnull",
        "iif", "string_agg", "group_concat", "date_trunc", "date_part",
        "to_char", "to_date", "to_timestamp", "round", "ceil", "floor",
        "substring", "length", "lower", "upper", "trim", "replace",
    }

    for node in statement.walk():
        if isinstance(node, prohibited_types):
            raise SQLValidationError(f"Prohibited SQL operation: {type(node).__name__}")
        if isinstance(node, exp.Anonymous) and node.name.lower() in unsafe_functions:
            raise SQLValidationError(f"Prohibited SQL function: {node.name}")
        if isinstance(node, exp.Anonymous) and node.name.lower() not in anonymous_functions:
            raise SQLValidationError(f"Unverified SQL function: {node.name}")
        if isinstance(node, exp.Dot) and isinstance(node.expression, exp.Func):
            raise SQLValidationError("Schema-qualified SQL functions are not allowed")
        if isinstance(node, exp.Func) and node.sql_name().lower() in unsafe_functions:
            raise SQLValidationError(f"Prohibited SQL function: {node.sql_name()}")

    tables = tuple(sorted({table.name for table in statement.find_all(exp.Table) if table.name}))
    normalized_sql = statement.sql(dialect=dialect)
    return SQLValidationResult(sql=normalized_sql, dialect=dialect, referenced_tables=tables)
