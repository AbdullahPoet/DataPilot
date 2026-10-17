from pathlib import Path

import pytest

from datapilot.agents.documentation_agent import DocumentationDecision
from datapilot.models.model_manager import ModelResponse
from datapilot.skills_engine.basic_knowledge_fallback import generate_sql_with_basic_fallback
from datapilot.tools import documentation_retriever, search_orchestrator
from datapilot.tools.cloud_search import NativeSearchResult
from datapilot.tools.documentation_retriever import DocumentationRetrievalError, _trusted_url


@pytest.mark.parametrize(
    "url",
    [
        "http://sqlite.org/docs",
        "https://sqlite.org.evil.test/",
        "https://user:pass@sqlite.org/",
        "https://sqlite.org:444/",
        "https://sqlite.org:invalid/",
        "file:///tmp/doc",
    ],
)
def test_untrusted_documentation_urls(url: str) -> None:
    assert not _trusted_url(url, "sqlite")


def test_missing_search_credential_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        search_orchestrator,
        "assess_documentation_need",
        lambda **kwargs: DocumentationDecision(True, "sqlite docs", "Need syntax"),
    )

    def unavailable(**kwargs: object) -> tuple:
        raise DocumentationRetrievalError("TAVILY_API_KEY is not configured")

    monkeypatch.setattr(search_orchestrator, "retrieve_documentation", unavailable)
    result = search_orchestrator.search_documentation(
        user_query="Syntax",
        topic="sqlite",
        model_configuration={"provider": "ollama", "model": "test"},
    )
    assert result.status == "unavailable"
    assert not result.search_confirmed
    assert "TAVILY" in result.reason


def test_unsupported_cloud_search_never_switches_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        search_orchestrator,
        "assess_documentation_need",
        lambda **kwargs: DocumentationDecision(True, "sqlite docs", "Need syntax"),
    )

    def unexpected(**kwargs: object) -> None:
        raise AssertionError("An unsupported provider must not trigger another provider's search")

    monkeypatch.setattr(search_orchestrator, "search_with_cloud_model", unexpected)
    result = search_orchestrator.search_documentation(
        user_query="Syntax",
        topic="sqlite",
        model_configuration={"provider": "DeepSeek", "model": "test"},
    )
    assert result.status == "unavailable" and result.provider == "DeepSeek"


def test_native_search_requires_official_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        search_orchestrator,
        "assess_documentation_need",
        lambda **kwargs: DocumentationDecision(True, "sqlite docs", "Need syntax"),
    )
    monkeypatch.setattr(
        search_orchestrator,
        "search_with_cloud_model",
        lambda **kwargs: NativeSearchResult(
            "OpenAI", "test", "Untrusted answer", True, ("https://untrusted.example/docs",)
        ),
    )
    result = search_orchestrator.search_documentation(
        user_query="Syntax",
        topic="sqlite",
        model_configuration={"provider": "OpenAI", "model": "test"},
    )
    assert result.status == "unavailable" and not result.search_confirmed
    assert not result.context


def test_redirect_is_rejected_before_request(monkeypatch: pytest.MonkeyPatch) -> None:
    from urllib.request import Request

    def opener(handler: object) -> object:
        class Opener:
            def open(self, request: Request, **kwargs: object) -> object:
                return handler.redirect_request(
                    request, None, 302, "redirect", {}, "http://127.0.0.1/private"
                )

        return Opener()

    monkeypatch.setattr(documentation_retriever, "build_opener", opener)
    with pytest.raises(DocumentationRetrievalError, match="redirect"):
        documentation_retriever._fetch_page("https://sqlite.org/docs", "sqlite", 1, 1000)


def test_basic_reference_loads_only_when_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    from datapilot.agents import sql_agent
    from datapilot.skills_engine import basic_knowledge_fallback

    model = {"provider": "ollama", "model": "test"}
    monkeypatch.setattr(
        basic_knowledge_fallback,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            '{"status":"ready","reason":"Known","sql":"SELECT 1","explanation":"One","assumptions":[]}',
            "test",
            "ollama",
        ),
    )
    result = generate_sql_with_basic_fallback(
        "One", "sales(amount)", "sqlite", model, basic_skill_path=Path("missing/basic/basic.md")
    )
    assert not result.basic_knowledge_used
    monkeypatch.setattr(
        basic_knowledge_fallback,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            '{"status":"needs_basic_knowledge","reason":"Need aggregate syntax"}',
            "test",
            "ollama",
        ),
    )
    monkeypatch.setattr(
        sql_agent,
        "invoke_model",
        lambda *a, **k: ModelResponse(
            '{"sql":"SELECT SUM(amount) FROM sales","explanation":"Total","assumptions":[]}',
            "test",
            "ollama",
        ),
    )
    result = generate_sql_with_basic_fallback("Total", "sales(amount)", "sqlite", model)
    assert result.basic_knowledge_used
