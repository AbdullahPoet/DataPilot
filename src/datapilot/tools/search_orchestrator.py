from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from datapilot.agents.documentation_agent import DocumentationDecision, assess_documentation_need
from datapilot.tools.cloud_search import (
    NativeSearchError,
    NativeSearchUnavailable,
    native_search_supported,
    search_with_cloud_model,
)
from datapilot.tools.documentation_retriever import (
    OFFICIAL_DOMAINS,
    DocumentationRetrievalError,
    DocumentationSource,
    _trusted_url,
    retrieve_documentation,
)

SearchStatus = Literal["not_needed", "retrieved", "unavailable"]


@dataclass(frozen=True)
class SearchOrchestrationResult:
    status: SearchStatus
    decision: DocumentationDecision
    provider: str
    context: str
    source_urls: tuple[str, ...]
    search_confirmed: bool
    reason: str


def _format_local_sources(sources: tuple[DocumentationSource, ...], budget: int) -> str:
    chunks: list[str] = []
    remaining = budget
    for source in sources:
        heading = f"Source: {source.title}\nURL: {source.url}\nUntrusted documentation excerpt:\n"
        if len(heading) >= remaining:
            break
        content = source.content[: remaining - len(heading) - 2]
        chunk = f"{heading}{content}\n\n"
        chunks.append(chunk)
        remaining -= len(chunk)
    return "".join(chunks)


def search_documentation(
    *,
    user_query: str,
    topic: str,
    model_configuration: Mapping[str, str | int],
    error_context: str = "",
    max_results: int = 3,
    max_context_characters: int = 12000,
    timeout: float = 30.0,
) -> SearchOrchestrationResult:
    if topic not in OFFICIAL_DOMAINS:
        raise ValueError("Unsupported documentation topic")
    if not isinstance(user_query, str) or not user_query.strip() or len(user_query) > 2000:
        raise ValueError("User query must contain 1 to 2000 characters")
    if not isinstance(error_context, str) or len(error_context) > 2000:
        raise ValueError("Error context exceeds 2000 characters")
    if not 1 <= max_results <= 5 or not 1 <= max_context_characters <= 50000:
        raise ValueError("Invalid documentation retrieval limits")
    if not 0 < timeout <= 300:
        raise ValueError("Timeout must be between 0 and 300 seconds")
    provider = model_configuration.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError("Selected provider is required")

    decision = assess_documentation_need(
        user_query=user_query,
        topic=topic,
        model_configuration=model_configuration,
        error_context=error_context,
    )
    if not decision.needed:
        return SearchOrchestrationResult("not_needed", decision, provider, "", (), False, decision.reason)

    if provider == "ollama":
        try:
            sources = retrieve_documentation(
                query=decision.search_query,
                topic=topic,
                max_results=max_results,
                max_characters=max_context_characters,
                timeout=min(timeout, 30.0),
            )
        except DocumentationRetrievalError as error:
            return SearchOrchestrationResult("unavailable", decision, provider, "", (), False, str(error))
        context = _format_local_sources(sources, max_context_characters)
        if not sources or not context:
            return SearchOrchestrationResult("unavailable", decision, provider, "", (), False, "No official documentation could be retrieved")
        return SearchOrchestrationResult(
            "retrieved", decision, provider, context,
            tuple(source.url for source in sources), True, decision.reason,
        )

    if not native_search_supported(model_configuration):
        return SearchOrchestrationResult(
            "unavailable", decision, provider, "", (), False,
            "Native web search is not verified for the selected provider; no fallback provider was used",
        )

    try:
        response = search_with_cloud_model(
            query=f"Find official {topic} documentation for: {decision.search_query}",
            configuration=model_configuration,
            timeout=timeout,
        )
    except (NativeSearchUnavailable, NativeSearchError) as error:
        return SearchOrchestrationResult("unavailable", decision, provider, "", (), False, str(error))

    if not response.search_confirmed:
        return SearchOrchestrationResult(
            "unavailable", decision, provider, "", response.source_urls, False,
            "Provider did not confirm that native web search was performed",
        )

    if not response.source_urls or any(not _trusted_url(url, topic) for url in response.source_urls):
        return SearchOrchestrationResult(
            "unavailable", decision, provider, "", (), False,
            "Native search did not supply exclusively official documentation sources",
        )
    context = (
        "Native web search answer (untrusted; verify against official documentation):\n"
        + response.answer[:max_context_characters]
    )
    return SearchOrchestrationResult(
        "retrieved", decision, provider, context[:max_context_characters],
        response.source_urls, True, decision.reason,
    )
