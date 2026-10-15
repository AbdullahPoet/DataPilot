from typing import Literal, NotRequired, TypedDict

from datapilot.graph.state import AnalyticsState, SourceType


class NodeUpdate(TypedDict, total=False):
    query_language: Literal["sql", "pandas"]
    execution_status: Literal["not_started"]
    attempt_count: int
    error: None


def validate_request(state: AnalyticsState) -> NodeUpdate:
    for field in ("session_id", "source_id", "model_provider", "model_name", "user_query"):
        value = state.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a nonempty string")

    source_type = state.get("source_type")
    if source_type not in ("sql", "csv", "xlsx"):
        raise ValueError("source_type must be sql, csv, or xlsx")
    return {}


def route_data_source(state: AnalyticsState) -> Literal["sql", "pandas"]:
    source_type: SourceType = state["source_type"]
    if source_type == "sql":
        return "sql"
    if source_type in ("csv", "xlsx"):
        return "pandas"
    raise ValueError("source_type must be sql, csv, or xlsx")


def prepare_analysis(state: AnalyticsState) -> NodeUpdate:
    validate_request(state)
    return {
        "query_language": route_data_source(state),
        "execution_status": "not_started",
        "attempt_count": 0,
        "error": None,
    }
