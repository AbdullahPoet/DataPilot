from typing import Literal, NotRequired, TypedDict

SourceType = Literal["sql", "csv", "xlsx"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
ExecutionStatus = Literal["not_started", "running", "succeeded", "failed"]


class ArtifactReference(TypedDict):
    kind: Literal["result", "chart", "report", "log"]
    path: str


class WorkflowError(TypedDict):
    category: str
    message: str
    retryable: bool


class AnalyticsState(TypedDict):
    session_id: str
    source_id: str
    source_type: SourceType
    model_provider: str
    model_name: str
    user_query: str
    approval_status: ApprovalStatus
    execution_status: ExecutionStatus
    attempt_count: int
    skill_paths: NotRequired[list[str]]
    sql_skill_instructions: NotRequired[str]
    schema_path: NotRequired[str]
    generated_query: NotRequired[str]
    query_language: NotRequired[Literal["sql", "pandas"]]
    query_version: NotRequired[int]
    result_reference: NotRequired[str]
    visualization_spec: NotRequired[dict[str, str | int | float | bool | None]]
    artifacts: NotRequired[list[ArtifactReference]]
    error: NotRequired[WorkflowError | None]
    analysis_context: NotRequired[str]
    documentation_status: NotRequired[str]


def create_analytics_state(
    session_id: str,
    source_id: str,
    source_type: SourceType,
    model_provider: str,
    model_name: str,
    user_query: str,
) -> AnalyticsState:
    required_values = {
        "session_id": session_id,
        "source_id": source_id,
        "model_provider": model_provider,
        "model_name": model_name,
        "user_query": user_query,
    }
    for field, value in required_values.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a nonempty string")
    if source_type not in ("sql", "csv", "xlsx"):
        raise ValueError("source_type must be sql, csv, or xlsx")

    return {
        **required_values,
        "source_type": source_type,
        "approval_status": "pending",
        "execution_status": "not_started",
        "attempt_count": 0,
    }
