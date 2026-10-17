import json
import re
import shutil
import sqlite3
from pathlib import Path

import pytest
from langgraph.types import Command

from datapilot.graph.agent_workflow import build_sql_agent_workflow
from datapilot.graph.state import create_analytics_state
from datapilot.memory.checkpoint_manager import checkpoint_config, open_checkpoint_saver
from datapilot.models.model_manager import ModelResponse
from datapilot.skills_engine.skill_loader import load_sql_reference_skills
from datapilot.skills_engine.skill_registry import discover_skills
from datapilot.validation.sql_validator import validate_sql

REFERENCES = sorted(
    path for level in ("easy", "mid", "hard") for path in Path("skills", level).glob("*.md")
)
EXPECTED = {
    "aggregation.md": {("East", 2, 300)},
    "filtering.md": {(3, 2, 300), (2, 1, 200)},
    "nulls_and_ratios.md": {("East", 300, 50), ("West", 300, 100)},
    "joins.md": {(1, "Ada", 2), (2, "Lin", 1), (3, "Sam", 0)},
    "subqueries.md": {(3, "Sam")},
    "conditional_aggregation.md": {("East", 100, 1), ("West", 300, 0)},
    "window_functions.md": {(2, 1, 200), (3, 2, 300)},
    "ctes_and_grain.md": {(1, "Ada", 300), (2, "Lin", 300), (3, "Sam", 0)},
    "set_operations.md": {(1, 100), (2, 200), (3, 300)},
    "repair_checklist.md": {("East", 300), ("West", 300)},
}


@pytest.mark.parametrize("path", REFERENCES, ids=lambda path: path.as_posix())
def test_sql_reference_examples_execute(path: Path) -> None:
    content = path.read_text(encoding="utf-8")
    examples = re.findall(r"```sql\s*\n(.*?)```", content, re.DOTALL)
    assert examples
    assert len(content) < 2000
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(
            "CREATE TABLE customers (id INTEGER, name TEXT);"
            "CREATE TABLE orders (id INTEGER, customer_id INTEGER, region TEXT, amount REAL, status TEXT, order_date TEXT);"
            "INSERT INTO customers VALUES (1, 'Ada'), (2, 'Lin'), (3, 'Sam');"
            "INSERT INTO orders VALUES (1, 1, 'East', 100, 'paid', '2024-12-01'),"
            "(2, 1, 'East', 200, 'pending', '2025-01-02'), (3, 2, 'West', 300, 'paid', '2025-01-03');"
        )
        for example in examples:
            for dialect in ("sqlite", "postgresql", "mysql"):
                validate_sql(example, dialect)
            assert set(connection.execute(example).fetchall()) == EXPECTED[path.name]


def test_direct_references_are_discovered_and_mid_is_medium(tmp_path: Path) -> None:
    skills = discover_skills(Path("skills"), "example")
    assert set(REFERENCES).issubset({skill.path.relative_to(Path.cwd()) for skill in skills})
    assert {skill.category for skill in skills if skill.path.parent.name == "mid"} == {"medium"}
    legacy = tmp_path / "medium" / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "SKILL.md").write_text(
        "---\nname: legacy\ndescription: Existing skill\n---\nKeep compatibility."
    )
    assert discover_skills(tmp_path, "example")[0].name == "legacy"


def test_retry_references_cross_levels_but_not_model_families(tmp_path: Path) -> None:
    root = tmp_path / "skills"
    shutil.copytree("skills", root)
    for family in ("example", "other"):
        directory = root / f"{family}_skills" / "private"
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: sql-private-{family}\ndescription: aggregate totals region grouping error\n---\nPrivate model reference."
        )
    references = load_sql_reference_skills(
        root, "example", "aggregate totals by region", error_context="grouping error"
    )
    assert "sql-repair-checklist" in references
    assert "sql-aggregation" in references
    assert "sql-private" not in references


def test_knowledge_fallback_supplies_reference_files(monkeypatch: pytest.MonkeyPatch) -> None:
    from datapilot.agents import sql_agent
    from datapilot.skills_engine import basic_knowledge_fallback

    captured = []
    monkeypatch.setattr(
        basic_knowledge_fallback,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            '{"status":"needs_basic_knowledge","reason":"Need window ranking syntax"}',
            "test",
            "ollama",
        ),
    )

    def generate(configuration: object, messages: object, **kwargs: object) -> ModelResponse:
        captured.extend(message.content for message in messages)
        return ModelResponse(
            '{"sql":"SELECT amount FROM sales","explanation":"Read sales","assumptions":[]}',
            "test",
            "ollama",
        )

    monkeypatch.setattr(sql_agent, "invoke_model", generate)
    result = basic_knowledge_fallback.generate_sql_with_basic_fallback(
        "Get latest results per customer",
        "sales(amount INTEGER)",
        "sqlite",
        {"provider": "ollama", "model": "test"},
    )
    assert result.basic_knowledge_used
    assert "skills/mid/*.md" in captured[0]
    assert "sql-window-ranking" in captured[1]


def test_approved_checkpoint_repair_receives_selected_and_diagnostic_skills(
    tmp_path: Path,
    session: tuple[Path, str],
    source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datapilot.agents import sql_repair_agent
    from datapilot.skills_engine import basic_knowledge_fallback, complexity_classifier

    database, session_id = session
    monkeypatch.setattr(
        complexity_classifier,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            '{"level":"easy","reasoning":"Aggregation"}', "test", "ollama"
        ),
    )
    monkeypatch.setattr(
        basic_knowledge_fallback,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            json.dumps(
                {
                    "status": "ready",
                    "reason": "Schema sufficient",
                    "sql": "SELECT SUM(missing) AS total FROM sales",
                    "explanation": "Total",
                    "assumptions": [],
                }
            ),
            "test",
            "ollama",
        ),
    )
    prompts = []

    def repair(configuration: object, messages: object, **kwargs: object) -> ModelResponse:
        prompts.extend(message.content for message in messages)
        return ModelResponse(
            '{"sql":"SELECT SUM(amount) AS total FROM sales","explanation":"Use verified column","changes":["Use amount"]}',
            "test",
            "ollama",
        )

    monkeypatch.setattr(sql_repair_agent, "invoke_model", repair)
    results = []

    def store(session_id: str, result: object) -> str:
        results.append(result)
        return "stored-result"

    graph = build_sql_agent_workflow(
        connection_url=source,
        approval_database_path=database,
        schema_markdown="sales(region TEXT, amount INTEGER)",
        dialect="sqlite",
        model_configuration={"provider": "ollama", "model": "test"},
        skills_directory=Path("skills"),
        model_family="test",
        result_store=store,
    )
    config = checkpoint_config(session_id)
    path = tmp_path / "checkpoints.db"
    with open_checkpoint_saver(path) as saver:
        pending = graph.compile(checkpointer=saver).invoke(
            create_analytics_state(
                session_id, "sales", "sql", "ollama", "test", "Sum amount totals by region"
            ),
            config,
        )
        assert pending["__interrupt__"]
        assert "sql-aggregation" in pending["sql_skill_instructions"]
        assert not prompts
    with open_checkpoint_saver(path) as saver:
        final = graph.compile(checkpointer=saver).invoke(Command(resume=True), config)
    assert final["attempt_count"] == 2
    assert results[0].rows == ((60,),)
    assert "sql-aggregation" in prompts[1]
    assert "sql-repair-checklist" in prompts[1]
