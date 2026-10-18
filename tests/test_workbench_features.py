import json
import shutil
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from datapilot.agents.visualization_agent import VisualizationPlan
from datapilot.application import AnalyticsApplication, initialize_application
from datapilot.ingestion.joined_source import join_frames, load_joined_source
from datapilot.models.model_manager import ModelResponse
from datapilot.persistence.analysis_evidence import load_evidence
from datapilot.persistence.dashboard_repository import (
    advance_refresh,
    filter_frame,
    kpi_value,
    list_cards,
    load_filters,
    move_card,
    pin_card,
    remove_card,
    result_frame,
    save_filters,
    start_refresh,
)
from datapilot.persistence.result_repository import list_results
from datapilot.persistence.session_repository import create_session
from datapilot.skills_engine.query_learning import (
    forget_examples,
    learned_context,
    learning_scope,
    set_feedback,
    set_learning,
)


@pytest.fixture
def file_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AnalyticsApplication:
    from datapilot.agents import pandas_agent, pandas_operation_compiler

    initialize_application(tmp_path / "storage" / "app.db")
    shutil.copytree("skills", tmp_path / "skills")
    path = tmp_path / "sales.csv"
    path.write_text("region,amount\nEast,10\nWest,20\nEast,30\n")
    session_id = create_session(
        tmp_path / "storage" / "app.db",
        "Sales",
        {
            "source_type": "csv",
            "file_path": str(path),
            "source_configured": True,
            "model_configuration": {"provider": "ollama", "model": "test"},
        },
    )
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
                    ]
                }
            ),
            "test",
            "ollama",
        ),
    )
    return AnalyticsApplication(tmp_path, session_id, {"provider": "ollama", "model": "test"})


def complete(app: AnalyticsApplication, question: str = "Totals by region") -> dict:
    result = app.run(question)
    return app.run(decision=True) if result.get("__interrupt__") else result


def test_join_diagnostics_nulls_and_cardinality() -> None:
    left = pd.DataFrame({"orders.id": [1, 1, 2, None], "orders.amount": [10, 20, 30, 40]})
    right = pd.DataFrame({"customers.id": [1, 3, None], "customers.name": ["A", "B", "C"]})
    frame, details = join_frames(left, right, left_on="orders.id", right_on="customers.id")
    assert frame["customers.name"].tolist()[:2] == ["A", "A"]
    assert frame["customers.name"].isna().sum() == 2
    assert details["unmatched_left_rows"] == 2
    assert details["unmatched_right_rows"] == 2
    assert details["left_duplicate_keys"] == 1
    assert details["output_rows"] == 4
    with pytest.raises(ValueError, match="Left key is not unique"):
        join_frames(
            left, right, left_on="orders.id", right_on="customers.id", relationship="one_to_one"
        )
    inner, _ = join_frames(left, right, left_on="orders.id", right_on="customers.id", how="inner")
    assert len(inner) == 2


def test_join_explosion_is_rejected_before_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    left = pd.DataFrame({"left.id": [1] * 10})
    right = pd.DataFrame({"right.id": [1] * 10})
    monkeypatch.setattr(pd.DataFrame, "merge", lambda *a, **k: pytest.fail("Unbounded merge"))
    with pytest.raises(ValueError, match="output would exceed"):
        join_frames(
            left,
            right,
            left_on="left.id",
            right_on="right.id",
            relationship="many_to_many",
            max_rows=50,
        )
    with pytest.raises(ValueError, match="Right key is not unique"):
        join_frames(left, right, left_on="left.id", right_on="right.id")


def joined_configuration(root: Path) -> dict:
    left = root / "orders.csv"
    left.write_text("customer_id,amount\n1,10\n1,20\n2,30\n")
    right = root / "customers.xlsx"
    pd.DataFrame({"id": [1, 2], "region": ["East", "West"]}).to_excel(right, index=False)
    return {
        "source_type": "csv",
        "files": [
            {"alias": "orders", "path": str(left)},
            {"alias": "customers", "path": str(right), "sheet_name": "Sheet1"},
        ],
        "joins": [
            {
                "right_alias": "customers",
                "left_on": "orders.customer_id",
                "right_on": "customers.id",
                "how": "left",
                "relationship": "many_to_one",
            }
        ],
    }


def test_mixed_files_restore_and_join_identity(tmp_path: Path) -> None:
    configuration = joined_configuration(tmp_path)
    first = load_joined_source(configuration)
    assert first.dataframe["customers.region"].tolist() == ["East", "East", "West"]
    assert load_joined_source(configuration).source_id == first.source_id
    configuration["joins"][0]["how"] = "inner"
    assert load_joined_source(configuration).source_id != first.source_id
    configuration["files"][1]["alias"] = "orders"
    with pytest.raises(ValueError, match="unique"):
        load_joined_source(configuration)


def test_joined_analysis_approval_and_restoration(
    file_app: AnalyticsApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datapilot.agents import pandas_agent, pandas_operation_compiler
    from datapilot.persistence.sqlite_manager import open_database

    configuration = joined_configuration(file_app.root)
    with open_database(file_app.database) as connection:
        connection.execute(
            "UPDATE sessions SET configuration_json = ? WHERE session_id = ?",
            (json.dumps(configuration), file_app.session_id),
        )
    monkeypatch.setattr(
        pandas_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "operations": ["Group by region and sum amount"],
                    "required_columns": ["customers.region", "orders.amount"],
                    "explanation": "Totals by customer region",
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
                                "by": ["customers.region"],
                                "aggregations": {"orders.amount": "sum"},
                            },
                        }
                    ]
                }
            ),
            "test",
            "ollama",
        ),
    )
    app = AnalyticsApplication(file_app.root, file_app.session_id, file_app.model)
    assert app.run("Totals by customer region")["__interrupt__"]
    restored = AnalyticsApplication(app.root, app.session_id, app.model)
    result = restored.run(decision=True)
    frame = result_frame(app.root, app.session_id, result["result_reference"])
    assert frame["orders.amount"].tolist() == [30, 30]
    evidence = load_evidence(app.database, app.session_id, result["result_reference"])
    assert len(evidence["source"]["files"]) == 2
    assert evidence["source"]["joins"][0]["output_rows"] == 3
    app.run("Different totals")
    Path(configuration["files"][0]["path"]).write_text("customer_id,amount\n1,999\n")
    with pytest.raises(ValueError, match="Source changed"):
        app.run("Totals")


def test_evidence_and_learning_are_idempotent_and_isolated(file_app: AnalyticsApplication) -> None:
    app = file_app
    first = complete(app)
    evidence = load_evidence(app.database, app.session_id, first["result_reference"])
    assert evidence["row_count"] == 2
    assert evidence["source"]["input_rows"] == 3
    assert evidence["explanation"] == "Totals by region"
    assert evidence["executed_analysis"][0]["kind"] == "groupby"
    assert not evidence["truncated"]
    app.snapshot()
    assert not learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")
    second = complete(app)
    context = learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")
    assert "groupby" in context and "not proof of correctness" in context
    assert not learned_context(app.database, "other", app.learning_scope, "Totals by region")
    assert not learned_context(app.database, app.session_id, "other", "Totals by region")
    assert not learned_context(app.database, app.session_id, app.learning_scope, "Other question")
    assert load_evidence(app.database, "other", first["result_reference"]) is None
    third = complete(app)
    assert load_evidence(app.database, app.session_id, third["result_reference"])[
        "learning_example_used"
    ]
    set_feedback(app.database, app.session_id, second["result_reference"], False)
    assert not learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")
    set_feedback(app.database, app.session_id, second["result_reference"], True)
    assert learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")
    assert (
        learning_scope(app.source_id, app.knowledge, {**app.model, "model": "other"})
        != app.learning_scope
    )
    forget_examples(app.database, app.session_id)
    app.snapshot()
    assert not learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")
    set_learning(app.database, app.session_id, False)
    complete(app)
    complete(app)
    set_learning(app.database, app.session_id, True)
    app.snapshot()
    assert not learned_context(app.database, app.session_id, app.learning_scope, "Totals by region")


def test_dashboard_persistence_filters_kpis_and_refresh(file_app: AnalyticsApplication) -> None:
    app = file_app
    result = complete(app)
    definition = {"kind": "kpi", "title": "Sales", "column": "amount", "aggregation": "sum"}
    first = pin_card(app.root, app.session_id, result["result_reference"], definition)
    plan = VisualizationPlan(
        "bar",
        "matplotlib",
        "region",
        "amount",
        "Sales",
        "Region",
        "Amount",
        "User selected",
        "manual",
        "manual",
    )
    second = pin_card(
        app.root,
        app.session_id,
        result["result_reference"],
        {
            "kind": "chart",
            "title": "Sales by region",
            "plan": asdict(plan),
        },
    )
    cards = list_cards(app.database, app.session_id)
    assert [card["card_id"] for card in cards] == [first, second]
    move_card(app.database, app.session_id, second, -1)
    assert list_cards(app.database, app.session_id)[0]["card_id"] == second
    filters = [{"column": "region", "values": ["East"], "include_missing": False}]
    save_filters(app.database, app.session_id, filters)
    frame = result_frame(app.root, app.session_id, result["result_reference"])
    assert (
        kpi_value(filter_frame(frame, load_filters(app.database, app.session_id)), definition) == 40
    )
    with pytest.raises(LookupError):
        pin_card(app.root, "other", result["result_reference"], definition)
    start_refresh(app.database, app.session_id)
    assert not advance_refresh(app)
    refreshed = list_cards(app.database, app.session_id)
    assert all(card["result_id"] != result["result_reference"] for card in refreshed)
    assert len(list_results(app.database, app.session_id, app.artifacts)) == 2
    remove_card(app.database, "other", first)
    assert len(list_cards(app.database, app.session_id)) == 2
    remove_card(app.database, app.session_id, first)
    assert len(list_cards(app.database, app.session_id)) == 1


def test_dashboard_refresh_pauses_on_changed_source(file_app: AnalyticsApplication) -> None:
    app = file_app
    result = complete(app)
    pin_card(
        app.root,
        app.session_id,
        result["result_reference"],
        {
            "kind": "kpi",
            "title": "Sales",
            "column": "amount",
            "aggregation": "sum",
        },
    )
    (app.root / "sales.csv").write_text("region,amount\nEast,999\n")
    restored = AnalyticsApplication(app.root, app.session_id, app.model)
    start_refresh(app.database, app.session_id)
    assert advance_refresh(restored)
    assert restored.snapshot()["interrupts"]
    assert list_cards(app.database, app.session_id)[0]["result_id"] == result["result_reference"]
    restored.run(decision=True)
    assert not advance_refresh(AnalyticsApplication(app.root, app.session_id, app.model))
    card = list_cards(app.database, app.session_id)[0]
    assert (
        kpi_value(result_frame(app.root, app.session_id, card["result_id"]), card["definition"])
        == 999
    )


def test_dashboard_filter_missing_and_no_data() -> None:
    frame = pd.DataFrame({"region": ["East", None], "amount": [10.0, None]})
    filtered = filter_frame(frame, [{"column": "region", "values": [], "include_missing": True}])
    assert len(filtered) == 1
    assert kpi_value(filtered, {"column": "amount", "aggregation": "sum"}) is None
    with pytest.raises(ValueError, match="missing"):
        filter_frame(frame, [{"column": "missing", "values": [], "include_missing": False}])
    with pytest.raises(ValueError, match="numeric"):
        kpi_value(frame, {"column": "region", "aggregation": "sum"})


def test_assumptions_require_review_after_source_approval(
    file_app: AnalyticsApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datapilot.agents import pandas_agent

    app = file_app
    complete(app)
    monkeypatch.setattr(
        pandas_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "operations": ["Group by region and sum amount"],
                    "required_columns": ["region", "amount"],
                    "explanation": "Totals by region",
                    "assumptions": ["Amount means revenue"],
                }
            ),
            "test",
            "ollama",
        ),
    )
    pending = app.run("Revenue by region")
    assert pending["__interrupt__"]
    assert len(list_results(app.database, app.session_id, app.artifacts)) == 1
    rejected = app.run(decision=False)
    assert rejected["approval_status"] == "rejected"
    pending = app.run("Revenue with clarification")
    assert pending["__interrupt__"]
    result = app.run(decision=True)
    assert load_evidence(app.database, app.session_id, result["result_reference"])[
        "assumptions"
    ] == ["Amount means revenue"]


def test_dashboard_refresh_rejection_keeps_previous_cards(file_app: AnalyticsApplication) -> None:
    app = file_app
    result = complete(app)
    pin_card(
        app.root,
        app.session_id,
        result["result_reference"],
        {
            "kind": "kpi",
            "title": "Sales",
            "column": "amount",
            "aggregation": "sum",
        },
    )
    (app.root / "sales.csv").write_text("region,amount\nEast,999\n")
    restored = AnalyticsApplication(app.root, app.session_id, app.model)
    start_refresh(app.database, app.session_id)
    assert advance_refresh(restored)
    restored.run(decision=False)
    with pytest.raises(ValueError, match="without a new approved result"):
        advance_refresh(restored)
    assert list_cards(app.database, app.session_id)[0]["result_id"] == result["result_reference"]
    assert not advance_refresh(restored)


def test_streamlit_dashboard_evidence_and_learning(
    file_app: AnalyticsApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    app = file_app
    complete(app)
    monkeypatch.setenv("DATAPILOT_HOME", str(app.root))
    at = AppTest.from_file(Path("streamlit_app.py").resolve(), default_timeout=30).run()
    at.button(key=f"open_{app.session_id}").click().run()
    assert not at.exception
    assert any(expander.label == "Answer evidence" for expander in at.expander)
    result_id = list_results(app.database, app.session_id, app.artifacts)[0].result_id
    at.button(key=f"pin_kpi_{result_id}").click().run()
    assert not at.exception
    assert at.metric[0].value == "60.00"
    at.selectbox(key=f"dashboard_column_{app.session_id}").set_value("region").run()
    at.multiselect(key=f"dashboard_values_{app.session_id}_region").set_value(["East"]).run()
    at.button(key=f"apply_filter_{app.session_id}").click().run()
    assert at.metric[0].value == "40.00"
    at.button(key=f"chart_{app.session_id}").click().run()
    chart_button = next(button for button in at.button if button.label == "Pin chart to dashboard")
    chart_button.click().run()
    assert not at.exception
    assert len(list_cards(app.database, app.session_id)) == 2
    at.button(key=f"refresh_dashboard_{app.session_id}").click().run()
    assert not at.exception
    assert at.metric[0].value == "40.00"
    assert len(list_results(app.database, app.session_id, app.artifacts)) == 2
    at.checkbox(key=f"learning_{app.session_id}").uncheck().run()
    from datapilot.skills_engine.query_learning import learning_enabled

    assert not learning_enabled(app.database, app.session_id)
    at.button(key=f"forget_learning_{app.session_id}").click().run()
    assert not at.exception
    assert not at.error


def test_streamlit_join_configuration(
    file_app: AnalyticsApplication, monkeypatch: pytest.MonkeyPatch
) -> None:
    from streamlit.testing.v1 import AppTest

    app = file_app
    configuration = joined_configuration(app.root)
    monkeypatch.setenv("DATAPILOT_HOME", str(app.root))
    at = AppTest.from_file(Path("streamlit_app.py").resolve(), default_timeout=30).run()
    at.button(key=f"open_{app.session_id}").click().run()
    at.checkbox(key=f"combine_{app.session_id}").check().run()
    at.radio(key=f"join_method_{app.session_id}").set_value("Local paths").run()
    paths = "\n".join(source["path"] for source in configuration["files"])
    at.text_area(key=f"join_paths_{app.session_id}").set_value(paths).run()
    assert not at.exception
    at.button(key=f"save_join_{app.session_id}").click().run()
    assert not at.exception
    restored = AnalyticsApplication(app.root, app.session_id, app.model)
    assert restored.frame["file2.region"].tolist() == ["East", "East", "West"]
    assert not at.error


def test_assumption_review_revokes_execution_until_decided(session: tuple[Path, str]) -> None:
    from datapilot.validation.approval_manager import (
        can_execute_query,
        decide_execution_approval,
        request_execution_approval,
    )

    database, session_id = session
    query = "SELECT 1"
    request_execution_approval(database, session_id, "source", query)
    decide_execution_approval(database, session_id, "source", query, True)
    assert can_execute_query(database, session_id, "source", query)
    assert (
        request_execution_approval(database, session_id, "source", query, require_review=True)
        == "pending"
    )
    assert not can_execute_query(database, session_id, "source", query)
    decide_execution_approval(database, session_id, "source", query, False)
    assert (
        request_execution_approval(database, session_id, "source", query, require_review=True)
        == "rejected"
    )


def test_refresh_incompatible_result_preserves_card(
    file_app: AnalyticsApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datapilot.agents import pandas_agent, pandas_operation_compiler

    app = file_app
    result = complete(app)
    pin_card(
        app.root,
        app.session_id,
        result["result_reference"],
        {
            "kind": "kpi",
            "title": "Sales",
            "column": "amount",
            "aggregation": "sum",
        },
    )
    monkeypatch.setattr(
        pandas_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "operations": ["Select region"],
                    "required_columns": ["region"],
                    "explanation": "Region list",
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
            json.dumps({"operations": [{"kind": "select", "parameters": {"columns": ["region"]}}]}),
            "test",
            "ollama",
        ),
    )
    start_refresh(app.database, app.session_id)
    with pytest.raises(ValueError, match="KPI aggregation and column"):
        advance_refresh(app)
    assert list_cards(app.database, app.session_id)[0]["result_id"] == result["result_reference"]
    assert not advance_refresh(app)


def test_pending_approval_cannot_change_model_endpoint(file_app: AnalyticsApplication) -> None:
    app = file_app
    app.run("Totals by region")
    changed = AnalyticsApplication(
        app.root,
        app.session_id,
        {
            **app.model,
            "base_url": "http://localhost:9999",
        },
    )
    assert changed.learning_scope != app.learning_scope
    with pytest.raises(ValueError, match="original source and model endpoint"):
        changed.run(decision=True)
    assert not list_results(app.database, app.session_id, app.artifacts)
    assert app.run(decision=True)["execution_status"] == "succeeded"
