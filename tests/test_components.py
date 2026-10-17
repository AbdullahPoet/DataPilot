import json
from pathlib import Path

import pandas as pd
import pytest
from jsonschema import ValidationError, validate
from pypdf import PdfReader

from datapilot.agents.pandas_agent import PandasAnalysisPlan
from datapilot.agents.pandas_operation_compiler import PandasCompilationError, _parse_operations
from datapilot.agents.visualization_agent import VisualizationPlan
from datapilot.execution.pandas_executor import PandasOperation, execute_pandas_plan
from datapilot.execution.sql_executor import execute_sql
from datapilot.graph.memory_orchestrator import prepare_memory_context
from datapilot.graph.retry_orchestrator import SQLRetryExhausted, execute_with_sql_repair
from datapilot.memory.context_reconstructor import reconstruct_context
from datapilot.memory.memory_compactor import MemoryTurn
from datapilot.models.model_manager import ModelResponse
from datapilot.models.response_schemas import pandas_operations_schema
from datapilot.persistence.result_repository import ResultRepositoryError, load_result, save_result
from datapilot.reports.pdf_report import ReportData, generate_pdf_report
from datapilot.skills_engine.skill_learning_manager import (
    LearnedSkill,
    SkillVerification,
    save_verified_skill,
)
from datapilot.skills_engine.skill_registry import discover_skills
from datapilot.validation.approval_manager import (
    decide_execution_approval,
    request_execution_approval,
)
from datapilot.validation.pandas_validator import PandasPlanValidationError, validate_pandas_plan
from datapilot.validation.sql_validator import SQLValidationError
from datapilot.visualization.chart_artifacts import save_chart_artifact
from datapilot.visualization.chart_renderer import render_chart


def test_repair_revalidates_and_uses_real_database(
    session: tuple[Path, str],
    source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datapilot.agents import sql_repair_agent

    database, session_id = session
    query = "SELECT SUM(missing) AS total FROM sales"
    request_execution_approval(database, session_id, "sales", query)
    decide_execution_approval(database, session_id, "sales", query, True)
    options = {
        "connection_url": source,
        "approval_database_path": database,
        "session_id": session_id,
        "source_id": "sales",
        "sql": query,
        "user_query": "Total",
        "schema_markdown": "sales(amount INTEGER)",
        "dialect": "sqlite",
        "model_configuration": {"provider": "ollama", "model": "test"},
    }
    monkeypatch.setattr(
        sql_repair_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "sql": "SELECT SUM(amount) AS total FROM sales",
                    "explanation": "Use verified column",
                    "changes": ["Use amount"],
                }
            ),
            "test",
            "ollama",
        ),
    )
    result = execute_with_sql_repair(**options)
    assert result.repairs_used == 1
    assert result.result.rows == ((60,),)
    monkeypatch.setattr(
        sql_repair_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "sql": "DELETE FROM sales",
                    "explanation": "Unsafe",
                    "changes": ["Delete data"],
                }
            ),
            "test",
            "ollama",
        ),
    )
    with pytest.raises(SQLValidationError):
        execute_with_sql_repair(**options)
    with pytest.raises(SQLRetryExhausted) as error:
        execute_with_sql_repair(**options, max_repairs=0)
    assert len(error.value.attempts) == 1


@pytest.mark.parametrize(
    "operation", ["exec('x')", "__import__('os')", "df['amount']", "import os"]
)
def test_pandas_rejects_executable_plans(operation: str) -> None:
    with pytest.raises(PandasPlanValidationError):
        validate_pandas_plan(
            PandasAnalysisPlan((operation,), ("amount",), "Bad", (), "csv", "test", "ollama"),
            ["amount"],
        )


@pytest.mark.parametrize(
    "operation",
    [
        {"kind": "eval", "parameters": {"code": "anything"}},
        {"kind": "select", "parameters": {"columns": ["missing"]}},
        {"kind": "groupby", "parameters": {"by": ["region"], "aggregations": {"amount": "exec"}}},
    ],
)
def test_compiler_rejects_unsafe_operations(operation: dict[str, object]) -> None:
    with pytest.raises(PandasCompilationError):
        _parse_operations(json.dumps({"operations": [operation]}), ["region", "amount"], 1)


def test_compiler_schema_requires_column_to_function_aggregation_mapping() -> None:
    schema = pandas_operations_schema(["category", "value"], 1)
    valid = {
        "operations": [
            {
                "kind": "groupby",
                "parameters": {"by": ["category"], "aggregations": {"value": "sum"}},
            }
        ]
    }
    validate(valid, schema)
    for aggregations in ({"sum": "value"}, {"value": "exec"}, {"unknown": "sum"}):
        invalid = {
            "operations": [
                {
                    "kind": "groupby",
                    "parameters": {"by": ["category"], "aggregations": aggregations},
                }
            ]
        }
        with pytest.raises(ValidationError):
            validate(invalid, schema)


def test_compaction_and_reconstruction(tmp_path: Path) -> None:
    messages = [MemoryTurn(str(index), "user", "A" * 6000) for index in range(6)]
    prepared = prepare_memory_context(
        session_id="session",
        messages=messages,
        tokenizer=lambda text: list(text.encode()),
        summarizer=lambda previous, turns: "Sales analysis summary",
        system_instructions="Analyze",
        schema_knowledge="sales(amount)",
        preserve_recent=1,
        artifact_references=["result123"],
        summary_path=tmp_path / "summary.md",
    )
    assert prepared.compaction is not None
    assert len(prepared.compaction.compacted_message_ids) == 5
    reconstructed = reconstruct_context(
        prepared.compaction,
        lambda text: list(text.encode()),
        schema_knowledge="sales(amount)",
    )
    assert not reconstructed.usage.should_compact
    assert "result123" in reconstructed.messages[0].content
    assert reconstructed.messages[-1].message_id == "5"
    assert (tmp_path / "summary.md").read_text().strip() == "Sales analysis summary"


def test_skill_isolation(tmp_path: Path) -> None:
    for category in ("easy", "alpha_skills", "beta_skills", "basic"):
        directory = tmp_path / category / "aggregate"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: {category}\ndescription: sum totals\n---\nAggregate data."
        )
    assert {skill.name for skill in discover_skills(tmp_path, "alpha")} == {"easy", "alpha_skills"}
    assert {skill.name for skill in discover_skills(tmp_path, "beta")} == {"easy", "beta_skills"}


def test_symlink_cannot_cross_model_skill_boundaries(tmp_path: Path) -> None:
    beta = tmp_path / "beta_skills"
    beta.mkdir()
    directory = beta / "aggregate"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: beta-only\ndescription: Beta aggregation\n---\nSum data."
    )
    try:
        (tmp_path / "alpha_skills").symlink_to(beta, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symbolic-link creation is unavailable")
    assert discover_skills(tmp_path, "alpha") == []
    skill = LearnedSkill(
        "sum-sales",
        "Sum sales",
        "Use SUM",
        "Totals",
        "SELECT SUM(amount) FROM sales",
        "Read only",
        "sqlite",
    )
    with pytest.raises(ValueError, match="symbolic link"):
        save_verified_skill(
            tmp_path, "alpha", skill, [SkillVerification("total", "passed", "fixture")]
        )


@pytest.mark.parametrize("library", ["matplotlib", "seaborn", "plotly", "bokeh"])
def test_charts_and_reports(tmp_path: Path, library: str) -> None:
    frame = pd.DataFrame({"region": ["East", "West"], "amount": [40, 20]})
    plan = VisualizationPlan(
        "bar", library, "region", "amount", "Sales", "Region", "Amount", "Compare", "test", "ollama"
    )
    rendered = render_chart(frame, plan)
    artifact = save_chart_artifact(
        rendered, artifacts_directory=tmp_path, session_id="test", title="Sales"
    )
    assert artifact.file_path.stat().st_size > 1000
    chart_paths = (artifact.file_path,) if artifact.media_type == "image/png" else ()
    report = generate_pdf_report(
        ReportData(
            "Sales",
            "test",
            "Sales by region",
            "East 40; West 20",
            tuple(frame.columns),
            tuple(frame.itertuples(index=False, name=None)),
            "sales",
            chart_paths=chart_paths,
        ),
        reports_directory=tmp_path / "reports",
    )
    text = "\n".join(page.extract_text() for page in PdfReader(report.path).pages)
    assert "East" in text and "40" in text and "Sales by region" in text
    if library in {"matplotlib", "seaborn"}:
        import matplotlib.pyplot as plt

        plt.close(rendered.figure)


def test_result_roundtrip_and_tampering(
    tmp_path: Path, session: tuple[Path, str], source: str
) -> None:
    database, session_id = session
    query = "SELECT * FROM sales"
    request_execution_approval(database, session_id, "sales", query)
    decide_execution_approval(database, session_id, "sales", query, True)
    result = execute_sql(
        connection_url=source,
        approval_database_path=database,
        session_id=session_id,
        source_id="sales",
        sql=query,
    )
    stored = save_result(
        result,
        database_path=database,
        artifacts_directory=tmp_path,
        session_id=session_id,
        source_id="sales",
    )
    options = {
        "database_path": database,
        "artifacts_directory": tmp_path,
        "session_id": session_id,
        "result_id": stored.result_id,
    }
    assert load_result(**options).rows == result.rows
    with pytest.raises(LookupError):
        load_result(**{**options, "session_id": "other"})
    stored.path.write_text("corrupted")
    with pytest.raises(ResultRepositoryError, match="checksum"):
        load_result(**options)


def test_pandas_limits_preserve_input() -> None:
    frame = pd.DataFrame({"amount": [3, 1, 2]})
    plan = validate_pandas_plan(
        PandasAnalysisPlan(("Sort amount",), ("amount",), "Sort", (), "csv", "test", "ollama"),
        frame.columns,
    )
    result = execute_pandas_plan(
        frame,
        plan,
        [PandasOperation("sort", {"by": ["amount"], "ascending": True})],
        max_result_rows=2,
    )
    assert result.truncated
    assert result.dataframe["amount"].tolist() == [1, 2]
    assert frame["amount"].tolist() == [3, 1, 2]


def test_sql_retries_stop_after_three_repairs(
    session: tuple[Path, str], source: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datapilot.agents import sql_repair_agent

    database, session_id = session
    query = "SELECT missing0 FROM sales"
    request_execution_approval(database, session_id, "sales", query)
    decide_execution_approval(database, session_id, "sales", query, True)
    repairs = []

    def repair(*args: object, **kwargs: object) -> ModelResponse:
        repairs.append(len(repairs) + 1)
        return ModelResponse(
            json.dumps(
                {
                    "sql": f"SELECT missing{len(repairs)} FROM sales",
                    "explanation": "Still missing",
                    "changes": ["Change column"],
                }
            ),
            "test",
            "ollama",
        )

    monkeypatch.setattr(sql_repair_agent, "invoke_model", repair)
    with pytest.raises(SQLRetryExhausted) as error:
        execute_with_sql_repair(
            connection_url=source,
            approval_database_path=database,
            session_id=session_id,
            source_id="sales",
            sql=query,
            user_query="Sales",
            schema_markdown="sales(amount)",
            dialect="sqlite",
            model_configuration={"provider": "ollama", "model": "test"},
        )
    assert len(repairs) == 3
    assert len(error.value.attempts) == 4
