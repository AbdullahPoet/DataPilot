from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import SQLAlchemyError

SUPPORTED_DIALECTS = frozenset({"sqlite", "postgresql", "mysql"})


@dataclass(frozen=True)
class ConnectionInfo:
    dialect: str
    database: str
    driver: str


def parse_connection_url(connection_url: str) -> URL:
    if not connection_url.strip():
        raise ValueError("A database connection URL is required")
    try:
        url = make_url(connection_url)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid SQLAlchemy connection URL") from error
    dialect = url.get_backend_name()
    if dialect not in SUPPORTED_DIALECTS:
        raise ValueError(f"Unsupported database dialect: {dialect}")
    if not url.database:
        raise ValueError("A database name or file path is required")
    if dialect == "sqlite":
        if url.database == ":memory:":
            raise ValueError("Select an existing SQLite database file")
        file_path = Path(url.database).expanduser()
        if not file_path.is_file():
            raise FileNotFoundError("SQLite database file does not exist")
    elif not url.host:
        raise ValueError("A database host is required")
    return url


def test_connection(connection_url: str, timeout_seconds: int = 10) -> ConnectionInfo:
    if timeout_seconds <= 0:
        raise ValueError("Connection timeout must be positive")
    url = parse_connection_url(connection_url)
    dialect = url.get_backend_name()
    connect_args = (
        {"timeout": float(timeout_seconds)}
        if dialect == "sqlite"
        else {"connect_timeout": timeout_seconds}
    )
    try:
        engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
    except (SQLAlchemyError, ImportError, TypeError, ValueError) as error:
        raise ConnectionError("Could not initialize the database driver") from error
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError as error:
        raise ConnectionError("Database connection test failed") from error
    finally:
        engine.dispose()
    return ConnectionInfo(
        dialect=dialect,
        database=url.database or "",
        driver=url.drivername,
    )
