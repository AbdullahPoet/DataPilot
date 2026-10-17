import json
from pathlib import Path

import pandas as pd
import pytest
from langgraph.types import Command

from datapilot.graph.agent_workflow import build_sql_agent_workflow
from datapilot.graph.pandas_workflow import build_pandas_agent_workflow
from datapilot.graph.state import create_analytics_state
from datapilot.ingestion.file_loader import load_data_file
from datapilot.memory.checkpoint_manager import checkpoint_config, open_checkpoint_saver
from datapilot.models.model_manager import ModelResponse

MODEL = {"provider": "ollama", "model": "test"}


def test_sql_checkpoint_resume(
    tmp_path: Path,
    session: tuple[Path, str],
    source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, session_id = session
    from datapilot.skills_engine import basic_knowledge_fallback, complexity_classifier

    def respond(configuration: object, messages: object, **kwargs: object) -> ModelResponse:
        return ModelResponse(
            json.dumps(
                {
                    "status": "ready",
                    "reason": "Schema is sufficient",
                    "sql": "SELECT SUM(amount) AS total FROM sales",
                    "explanation": "Total",
                    "assumptions": [],
                }
            ),
            "test",
            "ollama",
        )

    monkeypatch.setattr(basic_knowledge_fallback, "invoke_model", respond)
    monkeypatch.setattr(
        complexity_classifier,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps({"level": "easy", "reasoning": "Simple aggregation"}),
            "test",
            "ollama",
        ),
    )
    results = []

    def store(session_id: str, result: object) -> str:
        results.append(result)
        return "saved-result"

    graph = build_sql_agent_workflow(
        connection_url=source,
        approval_database_path=database,
        schema_markdown="sales(region TEXT, amount INTEGER)",
        dialect="sqlite",
        model_configuration=MODEL,
        skills_directory=Path("skills"),
        model_family="test",
        result_store=store,
    )
    config = checkpoint_config(session_id)
    path = tmp_path / "checkpoints.db"
    with open_checkpoint_saver(path) as saver:
        compiled = graph.compile(checkpointer=saver)
        initial = compiled.invoke(
            create_analytics_state(
                session_id,
                "sales",
                "sql",
                "ollama",
                "test",
                "Total sales",
            ),
            config,
        )
        assert initial["__interrupt__"]
        assert not results
    with open_checkpoint_saver(path) as saver:
        compiled = graph.compile(checkpointer=saver)
        final = compiled.invoke(Command(resume=True), config)
        assert final["execution_status"] == "succeeded"
        assert final["result_reference"] == "saved-result"
        assert results[0].rows == ((60,),)


@pytest.mark.parametrize("file_type", ["csv", "xlsx"])
def test_file_workflow_resume(
    tmp_path: Path,
    session: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
    file_type: str,
) -> None:
    from datapilot.agents import pandas_agent, pandas_operation_compiler

    database, session_id = session
    frame = pd.DataFrame({"region": ["East", "West", "East"], "amount": [10, 20, 30]})
    path = tmp_path / f"sales.{file_type}"
    if file_type == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_excel(path, index=False)
    monkeypatch.setattr(
        pandas_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "operations": ["Group by region and sum amount"],
                    "required_columns": ["region", "amount"],
                    "explanation": "Totals by region",
                    "assumptions": [],
                }
            ),
            "test",
            "ollama",
        ),
    )
    monkeypatch.setattr(
        pandas_operation_compiler,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "operations": [
                        {
                            "kind": "groupby",
                            "parameters": {
                                "by": ["region"],
                                "aggregations": {"amount": "sum"},
                            },
                        }
                    ]
                }
            ),
            "test",
            "ollama",
        ),
    )
    results = []

    def store(session_id: str, result: object) -> str:
        results.append(result)
        return "saved-result"

    graph = build_pandas_agent_workflow(
        file_profile="region TEXT, amount INTEGER",
        model_configuration=MODEL,
        dataframe_loader=lambda *args: load_data_file(
            path, sheet_name="Sheet1" if file_type == "xlsx" else None
        ),
        result_store=store,
        approval_database_path=database,
    )
    config = checkpoint_config(session_id)
    checkpoint = tmp_path / "checkpoints.db"
    with open_checkpoint_saver(checkpoint) as saver:
        compiled = graph.compile(checkpointer=saver)
        result = compiled.invoke(
            create_analytics_state(
                session_id,
                "sales",
                file_type,
                "ollama",
                "test",
                "Totals by region",
            ),
            config,
        )
        assert result["__interrupt__"]
        assert not results
    with open_checkpoint_saver(checkpoint) as saver:
        result = graph.compile(checkpointer=saver).invoke(Command(resume=True), config)
        assert result["execution_status"] == "succeeded"
        assert results[0].dataframe.to_dict("records") == [
            {"region": "East", "amount": 40},
            {"region": "West", "amount": 20},
        ]
