from langgraph.graph import END, START, StateGraph

from datapilot.graph.nodes import prepare_analysis, route_data_source
from datapilot.graph.state import AnalyticsState


def sql_entry(state: AnalyticsState) -> dict[str, str]:
    if state.get("query_language") != "sql":
        raise ValueError("SQL branch requires query_language='sql'")
    return {}


def pandas_entry(state: AnalyticsState) -> dict[str, str]:
    if state.get("query_language") != "pandas":
        raise ValueError("Pandas branch requires query_language='pandas'")
    return {}


def build_workflow() -> StateGraph:
    workflow = StateGraph(AnalyticsState)
    workflow.add_node("prepare", prepare_analysis)
    workflow.add_node("sql_entry", sql_entry)
    workflow.add_node("pandas_entry", pandas_entry)
    workflow.add_edge(START, "prepare")
    workflow.add_conditional_edges(
        "prepare",
        route_data_source,
        {"sql": "sql_entry", "pandas": "pandas_entry"},
    )
    workflow.add_edge("sql_entry", END)
    workflow.add_edge("pandas_entry", END)
    return workflow
