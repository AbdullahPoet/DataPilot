import json
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from datapilot.agents.visualization_agent import VisualizationPlan
from datapilot.persistence.analysis_evidence import load_evidence
from datapilot.persistence.result_repository import load_result
from datapilot.persistence.sqlite_manager import open_database


def initialize_dashboards(database: Path) -> None:
    with open_database(database) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS dashboard_cards ("
            "card_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id), "
            "result_id TEXT NOT NULL REFERENCES analysis_results(result_id), "
            "position INTEGER NOT NULL, definition TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS dashboard_settings ("
            "session_id TEXT PRIMARY KEY REFERENCES sessions(session_id), filters TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS dashboard_refresh ("
            "session_id TEXT PRIMARY KEY REFERENCES sessions(session_id), jobs TEXT NOT NULL)"
        )


def result_frame(root: Path, session_id: str, result_id: str) -> pd.DataFrame:
    data = load_result(
        database_path=root / "storage" / "app.db",
        artifacts_directory=root / "sessions",
        session_id=session_id,
        result_id=result_id,
    )
    return (
        data.dataframe
        if hasattr(data, "dataframe")
        else pd.DataFrame(data.rows, columns=data.columns)
    )


def list_cards(database: Path, session_id: str) -> list[dict[str, Any]]:
    initialize_dashboards(database)
    with open_database(database) as connection:
        rows = connection.execute(
            "SELECT * FROM dashboard_cards WHERE session_id = ? ORDER BY position, card_id",
            (session_id,),
        ).fetchall()
    return [{**dict(row), "definition": json.loads(row["definition"])} for row in rows]


def pin_card(root: Path, session_id: str, result_id: str, definition: dict[str, Any]) -> str:
    database = root / "storage" / "app.db"
    initialize_dashboards(database)
    frame = result_frame(root, session_id, result_id)
    if (
        not isinstance(definition.get("title"), str)
        or not 1 <= len(definition["title"].strip()) <= 100
    ):
        raise ValueError("Card title must contain 1 to 100 characters")
    if definition.get("kind") == "kpi":
        kpi_value(frame, definition)
    elif definition.get("kind") == "chart":
        from datapilot.visualization.chart_renderer import render_chart

        chart = render_chart(frame, VisualizationPlan(**definition["plan"]))
        if chart.library in {"matplotlib", "seaborn"}:
            chart.figure.clear()
    else:
        raise ValueError("Unsupported dashboard card")
    identifier = uuid4().hex
    with open_database(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM dashboard_cards WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        if count >= 24:
            raise ValueError("Dashboard supports at most 24 cards")
        connection.execute(
            "INSERT INTO dashboard_cards VALUES (?, ?, ?, "
            "(SELECT COALESCE(MAX(position), 0) + 1 FROM dashboard_cards WHERE session_id = ?), ?)",
            (
                identifier,
                session_id,
                result_id,
                session_id,
                json.dumps(definition, allow_nan=False),
            ),
        )
    return identifier


def remove_card(database: Path, session_id: str, card_id: str) -> None:
    with open_database(database) as connection:
        connection.execute(
            "DELETE FROM dashboard_cards WHERE session_id = ? AND card_id = ?",
            (session_id, card_id),
        )


def move_card(database: Path, session_id: str, card_id: str, offset: int) -> None:
    if offset not in {-1, 1}:
        raise ValueError("Move a card one position at a time")
    cards = list_cards(database, session_id)
    index = next((i for i, card in enumerate(cards) if card["card_id"] == card_id), None)
    if index is None:
        raise LookupError("Card not found in this session")
    target = index + offset
    if 0 <= target < len(cards):
        cards[index], cards[target] = cards[target], cards[index]
        with open_database(database) as connection:
            connection.executemany(
                "UPDATE dashboard_cards SET position = ? WHERE card_id = ? AND session_id = ?",
                [(i, card["card_id"], session_id) for i, card in enumerate(cards)],
            )


def kpi_value(frame: pd.DataFrame, definition: dict[str, Any]) -> int | float | None:
    aggregation = definition.get("aggregation")
    if aggregation == "count":
        return len(frame)
    column = definition.get("column")
    if aggregation not in {"sum", "mean", "min", "max"} or column not in frame:
        raise ValueError("Choose a supported KPI aggregation and column")
    if not pd.api.types.is_numeric_dtype(frame[column]):
        raise ValueError("KPI column must be numeric")
    if frame[column].dropna().empty:
        return None
    value = float(getattr(frame[column], aggregation)())
    if not math.isfinite(value):
        raise ValueError("KPI is not finite")
    return value


def validate_filters(filters: object) -> list[dict[str, Any]]:
    if not isinstance(filters, list) or len(filters) > 20:
        raise ValueError("Invalid dashboard filters")
    names = []
    for item in filters:
        if not isinstance(item, dict) or set(item) != {"column", "values", "include_missing"}:
            raise ValueError("Invalid dashboard filter")
        if not isinstance(item["column"], str) or not isinstance(item["values"], list):
            raise TypeError("Filter needs a column and values")
        if len(item["values"]) > 1000 or any(not isinstance(v, str) for v in item["values"]):
            raise ValueError("Invalid filter values")
        if type(item["include_missing"]) is not bool:
            raise ValueError("Missing-value selection must be boolean")
        names.append(item["column"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate dashboard filters")
    return filters


def save_filters(database: Path, session_id: str, filters: list[dict[str, Any]]) -> None:
    validate_filters(filters)
    with open_database(database) as connection:
        connection.execute(
            "INSERT INTO dashboard_settings VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET filters = excluded.filters",
            (session_id, json.dumps(filters)),
        )


def load_filters(database: Path, session_id: str) -> list[dict[str, Any]]:
    with open_database(database) as connection:
        row = connection.execute(
            "SELECT filters FROM dashboard_settings WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return validate_filters(json.loads(row[0])) if row else []


def filter_frame(frame: pd.DataFrame, filters: list[dict[str, Any]]) -> pd.DataFrame:
    result = frame
    for item in validate_filters(filters):
        if item["column"] not in result:
            raise ValueError("A shared filter column is missing; clear or update dashboard filters")
        series = result[item["column"]]
        keep = series.notna() & series.astype(str).isin(item["values"])
        if item["include_missing"]:
            keep |= series.isna()
        result = result.loc[keep]
    return result.copy()


def start_refresh(database: Path, session_id: str) -> None:
    jobs = []
    for card in list_cards(database, session_id):
        evidence = load_evidence(database, session_id, card["result_id"])
        if not evidence:
            raise ValueError("This card has no saved question to refresh")
        job = next((job for job in jobs if job["question"] == evidence["question"]), None)
        if job is None:
            job = {"question": evidence["question"], "cards": [], "started": False}
            jobs.append(job)
        job["cards"].append(card["card_id"])
    with open_database(database) as connection:
        connection.execute(
            "INSERT INTO dashboard_refresh VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET jobs = excluded.jobs",
            (session_id, json.dumps(jobs)),
        )


def cancel_refresh(database: Path, session_id: str) -> None:
    with open_database(database) as connection:
        connection.execute("DELETE FROM dashboard_refresh WHERE session_id = ?", (session_id,))


def advance_refresh(application: Any) -> bool:
    database, session_id = application.database, application.session_id
    with open_database(database) as connection:
        row = connection.execute(
            "SELECT jobs FROM dashboard_refresh WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    if not row:
        return False
    jobs = json.loads(row["jobs"])
    while jobs:
        job = jobs[0]
        snapshot = application.snapshot()
        if snapshot["interrupts"]:
            return True
        if not job["started"]:
            job["started"] = True
            job["previous_result"] = snapshot["values"].get("result_reference")
            with open_database(database) as connection:
                connection.execute(
                    "UPDATE dashboard_refresh SET jobs = ? WHERE session_id = ?",
                    (json.dumps(jobs), session_id),
                )
            try:
                values = application.run(job["question"])
            except Exception:
                cancel_refresh(database, session_id)
                raise
            if values.get("__interrupt__"):
                return True
        else:
            values = snapshot["values"]
        if (
            values.get("execution_status") != "succeeded"
            or values.get("user_query") != job["question"]
            or values.get("result_reference") == job.get("previous_result")
            or values.get("source_id") != application.source_id
        ):
            cancel_refresh(database, session_id)
            raise ValueError("Dashboard refresh stopped without a new approved result")
        new_id = values["result_reference"]
        try:
            frame = result_frame(application.root, session_id, new_id)
            for card in list_cards(database, session_id):
                if card["card_id"] in job["cards"]:
                    if card["definition"]["kind"] == "kpi":
                        kpi_value(frame, card["definition"])
                    elif not frame.empty:
                        from datapilot.visualization.chart_renderer import render_chart

                        chart = render_chart(frame, VisualizationPlan(**card["definition"]["plan"]))
                        if chart.library in {"matplotlib", "seaborn"}:
                            chart.figure.clear()
        except (ValueError, TypeError, KeyError, LookupError, OSError):
            cancel_refresh(database, session_id)
            raise
        jobs.pop(0)
        with open_database(database) as connection:
            connection.executemany(
                "UPDATE dashboard_cards SET result_id = ? WHERE card_id = ? AND session_id = ?",
                [(new_id, card_id, session_id) for card_id in job["cards"]],
            )
            connection.execute(
                "UPDATE dashboard_refresh SET jobs = ? WHERE session_id = ?",
                (json.dumps(jobs), session_id),
            )
    cancel_refresh(database, session_id)
    return False
