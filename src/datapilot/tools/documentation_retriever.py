import json
import os
import re
from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from bs4 import BeautifulSoup
from dotenv import load_dotenv

OFFICIAL_DOMAINS = {
    "sqlite": ("sqlite.org",),
    "postgresql": ("postgresql.org",),
    "mysql": ("dev.mysql.com",),
    "pandas": ("pandas.pydata.org",),
    "matplotlib": ("matplotlib.org",),
    "seaborn": ("seaborn.pydata.org",),
    "plotly": ("plotly.com",),
    "bokeh": ("docs.bokeh.org",),
}
TAVILY_ENDPOINT = "https://api.tavily.com/search"


class DocumentationRetrievalError(RuntimeError):
    pass


@dataclass(frozen=True)
class DocumentationSource:
    title: str
    url: str
    content: str


def _trusted_url(url: str, topic: str) -> bool:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError:
        return False
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    if parsed.username or parsed.password or port not in (None, 443):
        return False
    if parsed.query and len(parsed.query) > 2048:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    return any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in OFFICIAL_DOMAINS[topic]
    )


def _fetch_page(url: str, topic: str, timeout: float, max_bytes: int) -> str:
    if not _trusted_url(url, topic):
        raise DocumentationRetrievalError("Documentation URL is not trusted")
    request = Request(url, headers={"User-Agent": "DataPilotDocs/1.0", "Accept": "text/html"})
    class TrustedRedirect(HTTPRedirectHandler):
        def redirect_request(self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str) -> Request | None:
            if not _trusted_url(newurl, topic):
                raise DocumentationRetrievalError("Documentation redirect is outside trusted domains")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    with build_opener(TrustedRedirect()).open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not _trusted_url(final_url, topic):
            raise DocumentationRetrievalError("Documentation redirected outside the trusted domains")
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            raise DocumentationRetrievalError("Documentation response is not HTML")
        body = response.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise DocumentationRetrievalError("Documentation page exceeds size limit")
    soup = BeautifulSoup(body, "html.parser")
    for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
        element.decompose()
    primary = soup.find("main") or soup.find("article") or soup.body or soup
    return re.sub(r"\s+", " ", unescape(primary.get_text(" ", strip=True))).strip()


def retrieve_documentation(
    query: str,
    topic: str,
    *,
    max_results: int = 3,
    max_characters: int = 12000,
    timeout: float = 10.0,
    max_page_bytes: int = 1_000_000,
) -> tuple[DocumentationSource, ...]:
    if topic not in OFFICIAL_DOMAINS:
        raise ValueError("Unsupported documentation topic")
    if not query.strip() or len(query) > 500:
        raise ValueError("Query must contain 1 to 500 characters")
    if not 1 <= max_results <= 5 or max_characters <= 0 or timeout <= 0 or max_page_bytes <= 0:
        raise ValueError("Invalid documentation retrieval limits")
    load_dotenv()
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        raise DocumentationRetrievalError("TAVILY_API_KEY is not configured")
    payload = {
        "api_key": api_key,
        "query": query.strip(),
        "search_depth": "basic",
        "max_results": max_results * 3,
        "include_domains": list(OFFICIAL_DOMAINS[topic]),
        "include_answer": False,
    }
    request = Request(
        TAVILY_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_data = response.read(1_000_001)
        if len(response_data) > 1_000_000:
            raise DocumentationRetrievalError("Search response exceeds size limit")
        search_data = json.loads(response_data)
        if not isinstance(search_data, dict) or not isinstance(search_data.get("results"), list):
            raise DocumentationRetrievalError("Unexpected Tavily response format")
        sources = []
        for result in search_data["results"]:
            if not isinstance(result, dict):
                continue
            url = result.get("url")
            title = result.get("title")
            if not isinstance(url, str) or not _trusted_url(url, topic):
                continue
            try:
                content = _fetch_page(url, topic, timeout, max_page_bytes)
            except (HTTPError, URLError, TimeoutError, OSError, DocumentationRetrievalError):
                continue
            if not content:
                continue
            sources.append(DocumentationSource(
                title=title.strip()[:200] if isinstance(title, str) and title.strip() else url,
                url=url,
                content=content[:max_characters],
            ))
            if len(sources) >= max_results:
                break
        return tuple(sources)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise DocumentationRetrievalError("Documentation search failed") from exc
