import json
import os
from urllib.request import Request, urlopen

import pytest

from datapilot.tools.documentation_retriever import _trusted_url, retrieve_documentation
from datapilot.tools.search_orchestrator import search_documentation


@pytest.fixture
def tavily_key() -> str:
    key = os.getenv("TAVILY_API_KEY", "").strip()
    if not key:
        pytest.skip("Requires TAVILY_API_KEY for real search and extraction")
    return key


def _tavily_request(endpoint: str, key: str, payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        f"https://api.tavily.com/{endpoint}",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        assert response.status == 200
        body = response.read(2_000_001)
    assert len(body) <= 2_000_000
    data = json.loads(body)
    assert isinstance(data, dict)
    return data


def test_real_tavily_search(tavily_key: str) -> None:
    data = _tavily_request(
        "search",
        tavily_key,
        {
            "query": "SQLite SELECT GROUP BY HAVING aggregate official documentation",
            "search_depth": "basic",
            "max_results": 3,
            "include_domains": ["sqlite.org"],
        },
    )
    results = data.get("results", [])
    assert results
    assert all(_trusted_url(result["url"], "sqlite") for result in results)
    assert any("group" in result.get("content", "").lower() for result in results)
    print(json.dumps({"check": "tavily_search", "urls": [result["url"] for result in results]}))


def test_real_tavily_extract(tavily_key: str) -> None:
    data = _tavily_request(
        "extract",
        tavily_key,
        {
            "urls": ["https://sqlite.org/lang_select.html"],
            "extract_depth": "basic",
            "format": "text",
            "timeout": 30,
        },
    )
    results = data.get("results", [])
    assert results and not data.get("failed_results")
    content = results[0].get("raw_content", "")
    assert len(content) > 500
    assert "group by" in content.lower() and "having" in content.lower()
    print(
        json.dumps(
            {"check": "tavily_extract", "url": results[0]["url"], "characters": len(content)}
        )
    )


@pytest.mark.parametrize(
    "topic,query",
    [
        ("sqlite", "SQLite GROUP BY HAVING SELECT official documentation"),
        ("pandas", "pandas DataFrame groupby aggregation official reference"),
    ],
)
def test_real_datapilot_search_and_scraping(tavily_key: str, topic: str, query: str) -> None:
    sources = retrieve_documentation(query, topic, max_results=1, max_characters=12000, timeout=20)
    assert sources
    for source in sources:
        assert _trusted_url(source.url, topic)
        assert 100 < len(source.content) <= 12000
        assert "group" in source.content.lower()
    print(
        json.dumps(
            {
                "check": "datapilot_scraping",
                "topic": topic,
                "url": sources[0].url,
                "characters": len(sources[0].content),
            }
        )
    )


def test_real_model_documentation_workflow(tavily_key: str) -> None:
    model = os.getenv("DATAPILOT_TEST_OLLAMA_MODEL")
    if not model:
        pytest.skip("Requires DATAPILOT_TEST_OLLAMA_MODEL for real model-driven retrieval")
    result = search_documentation(
        user_query="Verify current SQLite aggregate function ORDER BY syntax in official documentation; do not rely on memory.",
        topic="sqlite",
        error_context="SQLite version compatibility is unknown; current documentation is required to resolve aggregate ORDER BY syntax.",
        model_configuration={
            "provider": "ollama",
            "model": model,
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            "think": False,
            "request_timeout": 180,
        },
        max_results=1,
        max_context_characters=2500,
        timeout=30,
    )
    assert result.status == "retrieved"
    assert result.search_confirmed and result.source_urls
    assert result.context and len(result.context) <= 2500
    assert all(_trusted_url(url, "sqlite") for url in result.source_urls)
    print(
        json.dumps(
            {
                "check": "model_documentation_workflow",
                "model": model,
                "status": result.status,
                "urls": result.source_urls,
                "context_characters": len(result.context),
            }
        )
    )
