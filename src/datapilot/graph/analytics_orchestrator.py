from collections.abc import Mapping
from typing import Any

from datapilot.graph.state import AnalyticsState
from datapilot.memory.checkpoint_manager import checkpoint_config


class AnalyticsOrchestrationError(ValueError):
    pass


def build_analytics_workflow(
    source_type: str,
    *,
    sql_options: Mapping[str, Any] | None = None,
    pandas_options: Mapping[str, Any] | None = None,
) -> Any:
    if source_type == "sql":
        if not sql_options:
            raise AnalyticsOrchestrationError("SQL workflow configuration is required")
        from datapilot.graph.agent_workflow import build_sql_agent_workflow

        return build_sql_agent_workflow(**dict(sql_options))

    if source_type in ("csv", "xlsx"):
        if not pandas_options:
            raise AnalyticsOrchestrationError("Pandas workflow configuration is required")
        from datapilot.graph.pandas_workflow import build_pandas_agent_workflow

        return build_pandas_agent_workflow(**dict(pandas_options))

    raise AnalyticsOrchestrationError("Unsupported analytics source type")


def run_analytics_workflow(
    state: AnalyticsState,
    *,
    sql_options: Mapping[str, Any] | None = None,
    pandas_options: Mapping[str, Any] | None = None,
    checkpointer: Any = None,
) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise TypeError("Analytics state must be a dictionary")
    session_id = state.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise AnalyticsOrchestrationError("A valid session ID is required")
    source_type = state.get("source_type")
    if source_type not in ("sql", "csv", "xlsx"):
        raise AnalyticsOrchestrationError("Unsupported analytics source type")
    if not isinstance(state.get("source_id"), str) or not state["source_id"].strip():
        raise AnalyticsOrchestrationError("A valid source ID is required")

    workflow = build_analytics_workflow(
        source_type,
        sql_options=sql_options,
        pandas_options=pandas_options,
    )
    compiled = workflow.compile(checkpointer=checkpointer) if checkpointer is not None else workflow.compile()
    result = compiled.invoke(state, config=checkpoint_config(session_id))
    if not isinstance(result, dict):
        raise TypeError("Analytics workflow must return a state dictionary")
    return result
