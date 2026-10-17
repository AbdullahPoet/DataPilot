import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv

from datapilot.application import AnalyticsApplication, initialize_application
from datapilot.execution.sql_executor import execute_sql
from datapilot.models.model_manager import ChatMessage, invoke_model
from datapilot.persistence.result_repository import load_result
from datapilot.persistence.session_repository import create_session
from datapilot.ui.model_selector import discover_ollama_models, inspect_ollama_model
from datapilot.validation.approval_manager import (
    decide_execution_approval,
    request_execution_approval,
)

load_dotenv()


def test_real_ollama() -> None:
    endpoint = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    try:
        available = discover_ollama_models(endpoint, timeout=2)
    except (ConnectionError, OSError):
        pytest.skip("No reachable Ollama endpoint")
    model = os.getenv("DATAPILOT_TEST_OLLAMA_MODEL")
    if not model:
        pytest.skip("Set DATAPILOT_TEST_OLLAMA_MODEL to select a real installed model")
    assert model in available
    configuration = {"provider": "ollama", "model": model, "base_url": endpoint}
    configuration["request_timeout"] = int(os.getenv("DATAPILOT_TEST_REQUEST_TIMEOUT", "60"))
    capabilities = inspect_ollama_model(endpoint, model)
    if isinstance(capabilities.get("thinking"), dict) and False in capabilities["thinking"].get(
        "values", []
    ):
        configuration["think"] = False
    result = invoke_model(
        configuration,
        [ChatMessage("user", "Reply with the word ready")],
        max_output_tokens=64,
    )
    assert result.content


@pytest.mark.parametrize(
    "provider,credential,model_variable",
    [
        ("OpenAI", "OPENAI_API_KEY", "DATAPILOT_TEST_OPENAI_MODEL"),
        ("Anthropic (Claude)", "ANTHROPIC_API_KEY", "DATAPILOT_TEST_ANTHROPIC_MODEL"),
        ("DeepSeek", "DEEPSEEK_API_KEY", "DATAPILOT_TEST_DEEPSEEK_MODEL"),
        ("Qwen", "DASHSCOPE_API_KEY", "DATAPILOT_TEST_QWEN_MODEL"),
    ],
)
def test_real_cloud_model(provider: str, credential: str, model_variable: str) -> None:
    model = os.getenv(model_variable)
    if not model or not os.getenv(credential):
        pytest.skip(f"Requires {credential} and {model_variable}")
    response = invoke_model(
        {"provider": provider, "model": model, "credential_env_var": credential},
        [ChatMessage("user", "Reply with the word ready")],
        max_output_tokens=64,
    )
    assert response.content


@pytest.mark.parametrize("variable", ["DATAPILOT_TEST_POSTGRES_URL", "DATAPILOT_TEST_MYSQL_URL"])
def test_real_external_database(variable: str, session: tuple[Path, str]) -> None:
    url = os.getenv(variable)
    if not url:
        pytest.skip(f"Requires {variable} pointing to a test database with read-only credentials")
    database, session_id = session
    query = "SELECT 1 AS ready"
    request_execution_approval(database, session_id, "external", query)
    decide_execution_approval(database, session_id, "external", query, True)
    result = execute_sql(
        connection_url=url,
        approval_database_path=database,
        session_id=session_id,
        source_id="external",
        sql=query,
    )
    assert result.rows == ((1,),)


@pytest.mark.parametrize("source_type", ["sql", "csv", "xlsx"])
def test_real_model_analytics(tmp_path: Path, source: str, source_type: str) -> None:
    model = os.getenv("DATAPILOT_TEST_OLLAMA_MODEL")
    if not model:
        pytest.skip(
            "Set DATAPILOT_TEST_OLLAMA_MODEL for actual model-generated analytical workflows"
        )
    configuration = {
        "provider": "ollama",
        "model": model,
        "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        "request_timeout": int(os.getenv("DATAPILOT_TEST_REQUEST_TIMEOUT", "60")),
    }
    capabilities = inspect_ollama_model(configuration["base_url"], model)
    if isinstance(capabilities.get("thinking"), dict) and False in capabilities["thinking"].get(
        "values", []
    ):
        configuration["think"] = False
    initialize_application(tmp_path / "storage" / "app.db")
    shutil.copytree("skills", tmp_path / "skills")
    source_configuration = {"source_type": source_type}
    if source_type != "sql":
        frame = pd.DataFrame({"region": ["East", "West", "East"], "amount": [10, 20, 30]})
        path = tmp_path / f"sales.{source_type}"
        if source_type == "csv":
            frame.to_csv(path, index=False)
        else:
            frame.to_excel(path, index=False)
        source_configuration.update(
            file_path=str(path), sheet_name="Sheet1" if source_type == "xlsx" else None
        )
    session_id = create_session(
        tmp_path / "storage" / "app.db", "Live model integration", source_configuration
    )
    app = AnalyticsApplication(
        tmp_path, session_id, configuration, connection_url=source if source_type == "sql" else None
    )
    result = app.run(
        "Return the sum of amount grouped by region, ordered by region ascending. Include only the region and aggregated amount columns."
    )
    assert result["__interrupt__"]
    result = app.run(decision=True)
    assert result["execution_status"] == "succeeded"
    restored = load_result(
        database_path=app.database,
        artifacts_directory=app.artifacts,
        session_id=session_id,
        result_id=result["result_reference"],
    )
    values = (
        restored.dataframe
        if hasattr(restored, "dataframe")
        else pd.DataFrame(restored.rows, columns=restored.columns)
    )
    assert values.iloc[:, 0].tolist() == ["East", "West"]
    assert values.iloc[:, 1].tolist() == [40, 20]
