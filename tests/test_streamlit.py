import json
import shutil
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from datapilot.application import AnalyticsApplication, initialize_application
from datapilot.models.model_manager import ModelResponse
from datapilot.persistence.session_repository import create_session


def test_streamlit_file_analysis_and_reporting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datapilot.agents import pandas_agent, pandas_operation_compiler

    root = tmp_path / "app"
    initialize_application(root / "storage" / "app.db")
    shutil.copytree("skills", root / "skills")
    path = root / "sales.csv"
    path.write_text("region,amount\nEast,10\nWest,20\nEast,30\n")
    session_id = create_session(
        root / "storage" / "app.db",
        "Sales",
        {
            "source_type": "csv",
            "source_configured": True,
            "file_path": str(path),
            "model_configuration": {"provider": "ollama", "model": "test"},
        },
    )
    monkeypatch.setenv("DATAPILOT_HOME", str(root))
    monkeypatch.setattr(AnalyticsApplication, "_context", lambda *args: ("", "not_needed"))
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
                            "parameters": {"by": ["region"], "aggregations": {"amount": "sum"}},
                        }
                    ],
                }
            ),
            "test",
            "ollama",
        ),
    )
    at = AppTest.from_file(Path("streamlit_app.py").resolve(), default_timeout=30).run()
    assert not at.exception
    at.button(key=f"open_{session_id}").click().run()
    assert not at.exception
    at.chat_input[0].set_value("Totals by region").run()
    assert not at.exception
    assert at.button(key=f"approve_{session_id}")
    at.button(key=f"approve_{session_id}").click().run()
    assert not at.exception
    assert at.dataframe[-1].value["amount"].tolist() == [40, 20]
    at.button(key=f"chart_{session_id}").click().run()
    assert not at.exception
    assert list((root / "sessions" / session_id / "charts").glob("*.png"))
    pdf_button = next(button for button in at.button if button.label == "Generate PDF report")
    pdf_button.click().run()
    assert not at.exception
    assert list((root / "storage" / "reports" / session_id).glob("*.pdf"))
    assert not at.error


def test_streamlit_new_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATAPILOT_HOME", str(tmp_path))
    at = AppTest.from_file(Path("streamlit_app.py").resolve(), default_timeout=30).run()
    next(button for button in at.button if button.label == "New Analytics").click().run()
    at.radio[0].set_value("CSV")
    at.radio[1].set_value("Cloud API")
    next(button for button in at.button if button.label == "Create Analytics Session").click().run()
    assert not at.exception
    assert at.session_state["session_config"]["source_type"] == "csv"
