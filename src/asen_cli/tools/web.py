from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator

from ..utils.safety import truncate_text
from .base import BaseTool, ToolResult

DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=20.0)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}
RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
DUCKDUCKGO_HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
TAVILY_SEARCH_ENDPOINT = "https://api.tavily.com/search"


class WebFetchArgs(BaseModel):
    url: str = Field(..., description="HTTP or HTTPS URL to fetch.")

    @field_validator("url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class WebSearchArgs(BaseModel):
    query: str = Field(..., description="Search query used to find web results.")
    max_results: int = Field(
        default=5,
        ge=1,
        le=8,
        description="Maximum number of search results to return.",
    )

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be empty")
        return stripped


class SearchHit(BaseModel):
    rank: int
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    source: str
    domain: str = ""

    def source_payload(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "title": self.title,
            "url": self.url,
            "snippet": truncate_text(self.snippet, 240),
            "source": self.source,
            "domain": self.domain,
        }


class WebFetchTool(BaseTool):
    name = "web_fetch"
    description = (
        "Fetch a HTTP/HTTPS URL, extract readable text when possible, and return source metadata."
    )
    args_model = WebFetchArgs

    def __init__(self, *, max_output_chars: int, client: httpx.AsyncClient | None = None) -> None:
        self.max_output_chars = max_output_chars
        self.client = client

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = WebFetchArgs.model_validate(args)
        try:
            if self.client is not None:
                response = await _request_with_retry(
                    self.client,
                    "GET",
                    typed_args.url,
                    follow_redirects=True,
                )
            else:
                async with _build_client() as client:
                    response = await _request_with_retry(
                        client,
                        "GET",
                        typed_args.url,
                        follow_redirects=True,
                    )
        except httpx.TimeoutException as exc:
            return ToolResult.failure(
                f"Fetch timed out: {exc}",
                error_type="network_timeout",
                retryable=True,
            )
        except httpx.HTTPError as exc:
            return ToolResult.failure(
                f"Fetch failed: {exc}",
                error_type="network_error",
                retryable=_is_retryable_http_error(exc),
            )

        content_type = response.headers.get("content-type", "unknown")
        document = _extract_document(str(response.url), response.text, content_type)
        body = truncate_text(document["content"], self.max_output_chars)
        source = {
            "title": document["title"],
            "url": str(response.url),
            "snippet": truncate_text(document["content"], 240),
            "source": "web_fetch",
            "domain": _domain_of(str(response.url)),
        }
        return ToolResult.success(
            (
                f"url={typed_args.url}\n"
                f"final_url={response.url}\n"
                f"title={document['title']}\n"
                f"content_type={content_type}\n\n{body}"
            ),
            meta={
                "sources": [source],
                "content_type": content_type,
                "final_url": str(response.url),
            },
        )


class WebSearchTool(BaseTool):
    name = "web_search"
    description = (
        "Search the web for recent documentation or references, "
        "fetch top pages, and return sources."
    )
    args_model = WebSearchArgs

    def __init__(
        self,
        *,
        max_output_chars: int,
        default_max_results: int = 5,
        provider: str = "duckduckgo",
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_output_chars = max_output_chars
        self.default_max_results = max(1, default_max_results)
        self.provider = provider.strip().lower() or "duckduckgo"
        self.api_key = api_key
        self.client = client

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = WebSearchArgs.model_validate(args)
        max_results = min(typed_args.max_results, self.default_max_results)
        try:
            if self.client is not None:
                hits = await self._search(self.client, typed_args.query, max_results)
            else:
                async with _build_client() as client:
                    hits = await self._search(client, typed_args.query, max_results)
        except httpx.TimeoutException as exc:
            return ToolResult.failure(
                f"Web search timed out: {exc}",
                error_type="network_timeout",
                retryable=True,
            )
        except httpx.HTTPError as exc:
            return ToolResult.failure(
                f"Web search failed: {exc}",
                error_type="network_error",
                retryable=_is_retryable_http_error(exc),
            )
        except ValueError as exc:
            return ToolResult.failure(
                str(exc),
                error_type="tool_error",
                retryable=False,
            )

        if not hits:
            return ToolResult.success(
                (
                    f"search_query={typed_args.query}\n"
                    f"provider={self.provider}\n\n"
                    "No search results found."
                ),
                meta={
                    "sources": [],
                    "search_query": typed_args.query,
                    "search_provider": self.provider,
                },
            )

        rendered = _render_search_results(
            typed_args.query,
            self.provider,
            hits,
            self.max_output_chars,
        )
        return ToolResult.success(
            rendered,
            meta={
                "sources": [hit.source_payload() for hit in hits],
                "search_query": typed_args.query,
                "search_provider": self.provider,
            },
        )

    async def _search(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> list[SearchHit]:
        if self.provider == "tavily":
            return await self._search_tavily(client, query, max_results)
        return await self._search_duckduckgo(client, query, max_results)

    async def _search_tavily(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> list[SearchHit]:
        if not self.api_key:
            raise ValueError("search_provider=tavily requires ASEN_SEARCH_API_KEY")

        response = await _request_with_retry(
            client,
            "POST",
            TAVILY_SEARCH_ENDPOINT,
            json={
                "api_key": self.api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": True,
            },
        )
        payload = response.json()
        hits: list[SearchHit] = []
        for rank, item in enumerate(payload.get("results") or [], start=1):
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            raw_content = item.get("raw_content") or item.get("content") or ""
            title = str(item.get("title") or "").strip() or _fallback_title(url)
            snippet = str(item.get("content") or "").strip()
            hits.append(
                SearchHit(
                    rank=rank,
                    title=title,
                    url=url,
                    snippet=snippet,
                    content=truncate_text(_normalize_block(raw_content), 1_200),
                    source="tavily",
                    domain=_domain_of(url),
                )
            )
            if len(hits) >= max_results:
                break
        return hits

    async def _search_duckduckgo(
        self,
        client: httpx.AsyncClient,
        query: str,
        max_results: int,
    ) -> list[SearchHit]:
        response = await _request_with_retry(
            client,
            "GET",
            DUCKDUCKGO_HTML_ENDPOINT,
            params={"q": query, "kl": "wt-wt"},
        )
        soup = BeautifulSoup(response.text, "html.parser")
        raw_hits: list[SearchHit] = []
        for block in soup.select("div.result"):
            link = block.select_one("a.result__a") or block.select_one("h2 a")
            if link is None:
                continue
            href = _resolve_search_result_url(str(link.get("href") or ""))
            if not href:
                continue
            title = _normalize_space(link.get_text(" ", strip=True)) or _fallback_title(href)
            snippet_node = block.select_one(".result__snippet") or block.select_one(
                ".snippet"
            )
            snippet = (
                _normalize_space(snippet_node.get_text(" ", strip=True))
                if snippet_node
                else ""
            )
            raw_hits.append(
                SearchHit(
                    rank=len(raw_hits) + 1,
                    title=title,
                    url=href,
                    snippet=snippet,
                    source="duckduckgo",
                    domain=_domain_of(href),
                )
            )
            if len(raw_hits) >= max_results:
                break

        if not raw_hits:
            return []

        enriched = await asyncio.gather(
            *(self._enrich_hit(client, hit) for hit in raw_hits),
        )
        return list(enriched)

    async def _enrich_hit(self, client: httpx.AsyncClient, hit: SearchHit) -> SearchHit:
        try:
            response = await _request_with_retry(client, "GET", hit.url, follow_redirects=True)
        except httpx.HTTPError:
            return hit
        document = _extract_document(
            str(response.url),
            response.text,
            response.headers.get("content-type", ""),
        )
        return hit.model_copy(
            update={
                "url": str(response.url),
                "title": document["title"] or hit.title,
                "content": truncate_text(document["content"], 1_200),
                "domain": _domain_of(str(response.url)),
            }
        )


def _build_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
        headers=DEFAULT_HEADERS,
    )


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            last_error = exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            last_error = exc
        except httpx.TransportError as exc:
            last_error = exc
        if attempt < 2:
            await asyncio.sleep(0.35 * (2**attempt))
    if last_error is None:
        raise RuntimeError("request failed without an error")
    raise last_error


def _extract_document(url: str, text: str, content_type: str) -> dict[str, str]:
    lowered_type = content_type.lower()
    title = ""
    content = text.strip()
    if "html" in lowered_type or "xml" in lowered_type or "<html" in text[:200].lower():
        extracted = trafilatura.extract(
            text,
            url=url,
            output_format="markdown",
            include_links=False,
            include_tables=True,
            favor_precision=True,
            deduplicate=True,
        )
        metadata = trafilatura.extract_metadata(text)
        if metadata and metadata.title:
            title = _normalize_space(metadata.title)
        if extracted:
            content = extracted.strip()
        else:
            soup = BeautifulSoup(text, "html.parser")
            if soup.title and soup.title.string:
                title = title or _normalize_space(soup.title.string)
            content = soup.get_text("\n", strip=True)
    content = _normalize_block(content)
    return {
        "title": title or _fallback_title(url),
        "content": content or f"No readable text extracted from {url}",
    }


def _render_search_results(
    query: str,
    provider: str,
    hits: list[SearchHit],
    max_output_chars: int,
) -> str:
    lines = [
        f"search_query={query}",
        f"provider={provider}",
        "",
        "Reference summary:",
    ]
    for hit in hits:
        summary = hit.content or hit.snippet or "No summary available."
        lines.append(f"- [{hit.rank}] {hit.title}: {truncate_text(summary, 260)}")
    lines.append("")
    lines.append("Sources:")
    for hit in hits:
        lines.append(f"[{hit.rank}] {hit.title}")
        lines.append(f"url={hit.url}")
        if hit.snippet:
            lines.append(f"snippet={truncate_text(hit.snippet, 240)}")
        if hit.content:
            lines.append(f"excerpt={truncate_text(hit.content, 700)}")
        lines.append("")
    return truncate_text("\n".join(lines).strip(), max_output_chars)


def _resolve_search_result_url(href: str) -> str:
    if not href:
        return ""
    absolute = urljoin("https://duckduckgo.com", href)
    parsed = urlparse(absolute)
    redirected = parse_qs(parsed.query).get("uddg")
    if redirected:
        return unquote(redirected[0])
    if parsed.scheme in {"http", "https"}:
        return absolute
    return ""


def _domain_of(url: str) -> str:
    return urlparse(url).netloc.lower()


def _fallback_title(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path and parsed.path != "/":
        slug = parsed.path.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
        if slug:
            return slug
    return parsed.netloc or url


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _normalize_block(value: str) -> str:
    lines = [line.strip() for line in value.splitlines()]
    filtered = [line for line in lines if line]
    return "\n".join(filtered)


def _is_retryable_http_error(exc: httpx.HTTPError) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_STATUS_CODES
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))
