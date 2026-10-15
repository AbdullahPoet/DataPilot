from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite import SqliteSaver


def checkpoint_config(session_id: str) -> dict[str, dict[str, str]]:
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id must be a nonempty string")
    return {"configurable": {"thread_id": session_id}}


@contextmanager
def open_checkpoint_saver(database_path: Path) -> Iterator[SqliteSaver]:
    if not isinstance(database_path, Path):
        raise TypeError("database_path must be a pathlib.Path")
    if database_path.suffix.lower() != ".db":
        raise ValueError("Checkpoint database path must end in .db")

    from langgraph.checkpoint.sqlite import SqliteSaver

    database_path.parent.mkdir(parents=True, exist_ok=True)
    with SqliteSaver.from_conn_string(str(database_path)) as saver:
        yield saver
