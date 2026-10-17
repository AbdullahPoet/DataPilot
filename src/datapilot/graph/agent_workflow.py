from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from datapilot.graph.nodes import prepare_analysis
from datapilot.graph.state import AnalyticsState

ResultStore = Callable[[str, object], str]


def build_sql_agent_workflow(
    *,
    connection_url: str,
    approval_database_path: Path,
    schema_markdown: str,
    dialect: str,
    model_configuration: Mapping[str, str | int],
    skills_directory: Path,
    model_family: str,
    result_store: ResultStore,
    max_repairs: int = 3,
) -> Any:
    from langgraph.graph import END, START, StateGraph

    from datapilot.graph.retry_orchestrator import execute_with_sql_repair
    from datapilot.skills_engine.basic_knowledge_fallback import generate_sql_with_basic_fallback
    from datapilot.skills_engine.skill_orchestrator import orchestrate_skills
    from datapilot.validation.approval_manager import request_execution_approval
    from datapilot.validation.sql_validator import validate_sql

    if not connection_url or not schema_markdown.strip():
        raise ValueError("Connection and verified schema are required")
    if dialect not in ("sqlite", "postgresql", "mysql"):
        raise ValueError("Unsupported SQL dialect")
    if not callable(result_store):
        raise TypeError("A result storage callback is required")
    if isinstance(max_repairs, bool) or not isinstance(max_repairs, int) or not 0 <= max_repairs <= 3:
        raise ValueError("max_repairs must be between 0 and 3")

    def prepare(state: AnalyticsState) -> dict[str, object]:
        if state["source_type"] != "sql":
            raise ValueError("This workflow supports SQL sources only")
        return dict(prepare_analysis(state))

    def select_and_generate(state: AnalyticsState) -> dict[str, object]:
        selection = orchestrate_skills(
            user_query=state["user_query"],
            model_configuration=model_configuration,
            skills_directory=skills_directory,
            model_family=model_family,
            source_context=schema_markdown,
        )
        generated = generate_sql_with_basic_fallback(
            user_query=state["user_query"],
            schema_markdown=schema_markdown,
            dialect=dialect,
            model_configuration=model_configuration,
            skill_instructions=selection.instructions,
            basic_skill_path=skills_directory / "basic" / "basic.md",
        ).generation
        validate_sql(generated.sql, dialect)
        return {
            "generated_query": generated.sql,
            "skill_paths": [str(match.skill.path) for match in selection.selected],
            "query_version": 1,
            "execution_status": "not_started",
        }

    def check_approval(state: AnalyticsState) -> dict[str, object]:
        status = request_execution_approval(
            approval_database_path,
            state["session_id"],
            state["source_id"],
            state["generated_query"],
        )
        if status == "pending":
            from langgraph.types import interrupt

            from datapilot.validation.approval_manager import decide_execution_approval

            decision = interrupt({"query": state["generated_query"], "source_id": state["source_id"]})
            if not isinstance(decision, bool):
                raise ValueError("Approval decision must be a boolean")
            status = decide_execution_approval(
                approval_database_path, state["session_id"], state["source_id"],
                state["generated_query"], decision,
            )
        return {"approval_status": status}

    def approval_route(state: AnalyticsState) -> str:
        return "execute" if state["approval_status"] == "approved" else "stop"

    def execute(state: AnalyticsState) -> dict[str, object]:
        retry_result = execute_with_sql_repair(
            connection_url=connection_url,
            approval_database_path=approval_database_path,
            session_id=state["session_id"],
            source_id=state["source_id"],
            sql=state["generated_query"],
            user_query=state["user_query"],
            schema_markdown=schema_markdown,
            dialect=dialect,
            model_configuration=model_configuration,
            max_repairs=max_repairs,
        )
        reference = result_store(state["session_id"], retry_result.result)
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Result storage must return a non-empty reference")
        return {
            "generated_query": retry_result.executed_sql,
            "attempt_count": len(retry_result.attempts),
            "query_version": state.get("query_version", 1) + retry_result.repairs_used,
            "result_reference": reference,
            "execution_status": "succeeded",
            "error": None,
        }

    graph = StateGraph(AnalyticsState)
    graph.add_node("prepare", prepare)
    graph.add_node("generate", select_and_generate)
    graph.add_node("approval", check_approval)
    graph.add_node("execute", execute)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "generate")
    graph.add_edge("generate", "approval")
    graph.add_conditional_edges("approval", approval_route, {"execute": "execute", "stop": END})
    graph.add_edge("execute", END)
    return graph
