from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NotRequired

import pandas as pd

from datapilot.graph.nodes import prepare_analysis
from datapilot.graph.state import AnalyticsState


class PandasWorkflowState(AnalyticsState):
    pandas_plan: NotRequired[dict[str, object]]
    pandas_operations: NotRequired[list[dict[str, object]]]


DataframeLoader = Callable[[str, str], pd.DataFrame]
ResultStore = Callable[[str, object], str]


def build_pandas_agent_workflow(
    *,
    file_profile: str,
    model_configuration: Mapping[str, str | int],
    dataframe_loader: DataframeLoader,
    result_store: ResultStore,
    approval_database_path: Path,
    skill_instructions: str = "",
    max_input_rows: int = 1_000_000,
    max_result_rows: int = 10_000,
) -> Any:
    from langgraph.graph import END, START, StateGraph

    from datapilot.agents.pandas_agent import PandasAnalysisPlan, plan_pandas_analysis
    from datapilot.agents.pandas_operation_compiler import compile_pandas_operations
    from datapilot.execution.pandas_executor import PandasOperation, execute_pandas_plan
    from datapilot.validation.approval_manager import request_execution_approval
    from datapilot.validation.pandas_validator import validate_pandas_plan

    if not isinstance(file_profile, str) or not file_profile.strip():
        raise ValueError("A verified file profile is required")
    if not callable(dataframe_loader) or not callable(result_store):
        raise TypeError("DataFrame loader and result store must be callable")
    if not isinstance(approval_database_path, Path):
        raise TypeError("An approval database path is required")
    if type(max_input_rows) is not int or max_input_rows < 1:
        raise ValueError("max_input_rows must be a positive integer")
    if type(max_result_rows) is not int or max_result_rows < 1:
        raise ValueError("max_result_rows must be a positive integer")

    def load_frame(state: PandasWorkflowState) -> pd.DataFrame:
        frame = dataframe_loader(state["session_id"], state["source_id"])
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("DataFrame loader must return a Pandas DataFrame")
        if len(frame) > max_input_rows:
            raise ValueError("Input exceeds the configured row limit")
        if any(not isinstance(name, str) or not name for name in frame.columns):
            raise ValueError("DataFrame columns must be non-empty strings")
        if not frame.columns.is_unique:
            raise ValueError("DataFrame columns must be unique")
        return frame

    def prepare(state: PandasWorkflowState) -> dict[str, object]:
        if state["source_type"] not in ("csv", "xlsx"):
            raise ValueError("This workflow supports CSV and XLSX sources only")
        return dict(prepare_analysis(state))

    def plan(state: PandasWorkflowState) -> dict[str, object]:
        frame = load_frame(state)
        generated = plan_pandas_analysis(
            user_query=state["user_query"],
            file_profile=file_profile,
            file_type=state["source_type"],
            model_configuration=model_configuration,
            skill_instructions="\n\n".join(filter(None, [skill_instructions, state.get("analysis_context", "")])),
        )
        validated = validate_pandas_plan(generated, frame.columns)
        return {
            "pandas_plan": {
                "operations": list(validated.operations),
                "required_columns": list(validated.required_columns),
                "explanation": validated.explanation,
                "assumptions": list(validated.assumptions),
                "file_type": validated.file_type,
                "model": validated.model,
                "provider": validated.provider,
            },
            "execution_status": "not_started",
        }

    def compile_operations(state: PandasWorkflowState) -> dict[str, object]:
        from datapilot.validation.pandas_validator import ValidatedPandasPlan

        frame = load_frame(state)
        stored = state["pandas_plan"]
        validated = ValidatedPandasPlan(
            operations=tuple(stored["operations"]),
            required_columns=tuple(stored["required_columns"]),
            explanation=str(stored["explanation"]),
            assumptions=tuple(stored["assumptions"]),
            file_type=str(stored["file_type"]),
            model=str(stored["model"]),
            provider=str(stored["provider"]),
        )
        validated = validate_pandas_plan(
            PandasAnalysisPlan(
                operations=validated.operations,
                required_columns=validated.required_columns,
                explanation=validated.explanation,
                assumptions=validated.assumptions,
                file_type=state["source_type"],
                model=validated.model,
                provider=validated.provider,
            ),
            frame.columns,
        )
        compiled = compile_pandas_operations(
            validated_plan=validated,
            available_columns=list(frame.columns),
            model_configuration=model_configuration,
        )
        return {
            "pandas_operations": [
                {"kind": operation.kind, "parameters": dict(operation.parameters)}
                for operation in compiled.operations
            ]
        }

    def check_approval(state: PandasWorkflowState) -> dict[str, object]:
        status = request_execution_approval(
            approval_database_path,
            state["session_id"],
            state["source_id"],
            state["user_query"],
        )
        if status == "pending":
            from langgraph.types import interrupt

            from datapilot.validation.approval_manager import decide_execution_approval

            decision = interrupt({"query": state["user_query"], "operations": state["pandas_operations"]})
            if not isinstance(decision, bool):
                raise ValueError("Approval decision must be a boolean")
            status = decide_execution_approval(
                approval_database_path, state["session_id"], state["source_id"],
                state["user_query"], decision,
            )
        return {"approval_status": status}

    def route_approval(state: PandasWorkflowState) -> str:
        return "execute" if state["approval_status"] == "approved" else "stop"

    def execute(state: PandasWorkflowState) -> dict[str, object]:
        from datapilot.validation.approval_manager import can_execute_query

        if not can_execute_query(
            approval_database_path,
            state["session_id"],
            state["source_id"],
            state["user_query"],
        ):
            raise PermissionError("Execution requires recorded user approval")
        frame = load_frame(state)
        stored = state["pandas_plan"]
        validated = validate_pandas_plan(
            PandasAnalysisPlan(
                operations=tuple(stored["operations"]),
                required_columns=tuple(stored["required_columns"]),
                explanation=str(stored["explanation"]),
                assumptions=tuple(stored["assumptions"]),
                file_type=state["source_type"],
                model=str(stored["model"]),
                provider=str(stored["provider"]),
            ),
            frame.columns,
        )
        operations = tuple(
            PandasOperation(kind=step["kind"], parameters=step["parameters"])
            for step in state["pandas_operations"]
        )
        result = execute_pandas_plan(
            dataframe=frame,
            validated_plan=validated,
            operations=operations,
            max_input_rows=max_input_rows,
            max_result_rows=max_result_rows,
        )
        reference = result_store(state["session_id"], result)
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("Result storage must return a non-empty artifact reference")
        return {
            "result_reference": reference,
            "execution_status": "succeeded",
            "attempt_count": 1,
            "error": None,
        }

    graph = StateGraph(PandasWorkflowState)
    graph.add_node("prepare", prepare)
    graph.add_node("plan", plan)
    graph.add_node("compile", compile_operations)
    graph.add_node("approval", check_approval)
    graph.add_node("execute", execute)
    graph.add_edge(START, "prepare")
    graph.add_edge("prepare", "plan")
    graph.add_edge("plan", "compile")
    graph.add_edge("compile", "approval")
    graph.add_conditional_edges("approval", route_approval, {"execute": "execute", "stop": END})
    graph.add_edge("execute", END)
    return graph
