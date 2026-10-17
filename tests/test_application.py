import json
import shutil
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pandas as pd
import pytest

from datapilot.application import AnalyticsApplication, initialize_application
from datapilot.models.model_manager import ModelResponse
from datapilot.persistence.result_repository import list_results, load_result
from datapilot.persistence.session_repository import create_session


@pytest.fixture
def model_endpoint() -> Iterator[dict[str, str | int]]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            system = request["messages"][0]["content"]
            if not isinstance(request.get("format"), dict):
                self.send_error(400, "Structured agents must request JSON output")
                return
            if "search_query" in system:
                payload = {"needed": False, "search_query": "", "reason": "Routine aggregation"}
            elif "reasoning" in system and "level" in system:
                payload = {"level": "easy", "reasoning": "Simple aggregation"}
            elif "needs_basic_knowledge" in system:
                payload = {
                    "status": "ready",
                    "reason": "Sufficient schema",
                    "sql": "SELECT SUM(amount) AS total FROM sales",
                    "explanation": "Total sales",
                    "assumptions": [],
                }
            elif "analysis planner" in system:
                payload = {
                    "operations": ["Group by region and sum amount"],
                    "required_columns": ["region", "amount"],
                    "explanation": "Totals by region",
                    "assumptions": [],
                }
            elif "operations array" in system:
                payload = {
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
            else:
                self.send_error(400, "Unexpected model prompt")
                return
            data = json.dumps({"message": {"content": json.dumps(payload)}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "provider": "ollama",
            "model": "test",
            "base_url": f"http://127.0.0.1:{server.server_port}",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("source_type", ["sql", "csv", "xlsx"])
def test_application_end_to_end(
    tmp_path: Path,
    source: str,
    model_endpoint: dict[str, str | int],
    source_type: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "application"
    database = root / "storage" / "app.db"
    initialize_application(database)
    shutil.copytree("skills", root / "skills")
    configuration = {"source_type": source_type}
    if source_type != "sql":
        path = root / f"sales.{source_type}"
        frame = pd.DataFrame({"region": ["East", "West", "East"], "amount": [10, 20, 30]})
        if source_type == "csv":
            frame.to_csv(path, index=False)
        else:
            frame.to_excel(path, index=False)
        configuration.update(
            file_path=str(path), sheet_name="Sheet1" if source_type == "xlsx" else None
        )
    session_id = create_session(database, "Sales", configuration)
    options = {"connection_url": source} if source_type == "sql" else {}
    app = AnalyticsApplication(root, session_id, model_endpoint, **options)
    pending = app.run("Total sales")
    assert pending["__interrupt__"]
    assert not list_results(database, session_id, app.artifacts)
    restored = AnalyticsApplication(root, session_id, model_endpoint, **options)
    assert restored.snapshot()["interrupts"]
    completed = restored.run(decision=True)
    assert completed["execution_status"] == "succeeded"
    result = load_result(
        database_path=database,
        artifacts_directory=app.artifacts,
        session_id=session_id,
        result_id=completed["result_reference"],
    )
    if source_type == "sql":
        assert result.rows == ((60,),)
        assert list((root / "storage" / "logs" / session_id).glob("*.txt"))
    else:
        assert result.dataframe["amount"].tolist() == [40, 20]
    assert len(restored._memory()["turns"]) == 2
    subsequent = restored.run("Total sales again")
    assert subsequent["execution_status"] == "succeeded"
    assert len(list_results(database, session_id, app.artifacts)) == 2
    assert len(restored._memory()["turns"]) == 4
    restored._save_memory({"summary": "", "turns": [], "references": []})
    restored.snapshot()
    assert len(restored._memory()["turns"]) == 2
    batches = []

    def summarize(configuration: object, messages: object, **kwargs: object) -> ModelResponse:
        batches.append(sum(len(message.content.encode()) for message in messages))
        return ModelResponse("Earlier sales analysis", "test", "ollama")

    monkeypatch.setattr("datapilot.application.invoke_model", summarize)
    restored._save_memory(
        {
            "summary": "",
            "references": [],
            "turns": [
                {"message_id": str(index), "role": "user", "content": "A" * 6000}
                for index in range(6)
            ],
        }
    )
    context, status = restored._context("Continue analysis")
    assert "Earlier sales analysis" in context
    assert status == "not_needed"
    assert len(batches) > 1 and max(batches) < 35000 * 0.85
    assert restored._memory()["summary"] == "Earlier sales analysis"
    assert len(restored._memory()["turns"]) == 2


def test_application_rejects_changed_source(
    tmp_path: Path,
    model_endpoint: dict[str, str | int],
) -> None:
    initialize_application(tmp_path / "storage" / "app.db")
    shutil.copytree("skills", tmp_path / "skills")
    path = tmp_path / "data.csv"
    path.write_text("region,amount\nEast,10\n")
    session_id = create_session(
        tmp_path / "storage" / "app.db",
        "CSV",
        {
            "source_type": "csv",
            "file_path": str(path),
        },
    )
    app = AnalyticsApplication(tmp_path, session_id, model_endpoint)
    app.run("Total sales")
    path.write_text("region,amount\nEast,999\n")
    restored = AnalyticsApplication(tmp_path, session_id, model_endpoint)
    with pytest.raises(ValueError, match="original source"):
        restored.run(decision=True)
    rejected = restored.run(decision=False)
    assert rejected["approval_status"] == "rejected"
    assert not list_results(restored.database, session_id, restored.artifacts)
