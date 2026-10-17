import sqlite3
from pathlib import Path

import pytest

from datapilot.persistence.session_repository import create_session, initialize_sessions
from datapilot.persistence.sqlite_manager import initialize_database
from datapilot.validation.approval_manager import initialize_approvals


@pytest.fixture
def session(tmp_path: Path) -> tuple[Path, str]:
    database = tmp_path / "app.db"
    initialize_database(database)
    initialize_sessions(database)
    initialize_approvals(database)
    return database, create_session(database, "Test analytics", {})


@pytest.fixture
def source(tmp_path: Path) -> str:
    database = tmp_path / "source.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE sales (region TEXT, amount INTEGER)")
        connection.executemany(
            "INSERT INTO sales VALUES (?, ?)", [("East", 10), ("West", 20), ("East", 30)]
        )
    return f"sqlite:///{database.as_posix()}"
