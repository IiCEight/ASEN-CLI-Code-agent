import httpx
import pytest

from asen_cli.tools.web import WebFetchTool, WebSearchTool


@pytest.mark.asyncio
async def test_web_fetch_success():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text="hello web",
            headers={"content-type": "text/plain"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        tool = WebFetchTool(max_output_chars=100, client=client)
        result = await tool.execute({"url": "https://example.com"})

    assert result.ok
    assert "hello web" in result.content
    assert "text/plain" in result.content
    assert result.meta["sources"][0]["url"] == "https://example.com"


@pytest.mark.asyncio
async def test_web_fetch_extracts_main_content_from_html():
    html = """
    <html>
      <head><title>Example Docs</title></head>
      <body>
        <nav>Navigation</nav>
        <main>
          <h1>Quickstart</h1>
          <p>Install the package and run the CLI.</p>
        </main>
      </body>
    </html>
    """
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html; charset=utf-8"},
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        tool = WebFetchTool(max_output_chars=200, client=client)
        result = await tool.execute({"url": "https://docs.example.com/quickstart"})

    assert result.ok
    assert "title=Quickstart" in result.content
    assert "Install the package and run the CLI." in result.content


@pytest.mark.asyncio
async def test_web_search_duckduckgo_fetches_and_formats_sources():
    search_html = """
    <html>
      <body>
        <div class="result">
          <a
            class="result__a"
            href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.example.com%2Fagent"
          >Agent Docs</a>
          <a class="result__snippet">Official documentation for the agent runtime.</a>
        </div>
      </body>
    </html>
    """
    page_html = """
    <html>
      <head><title>Agent Docs</title></head>
      <body>
        <article>
          <h1>Agent Docs</h1>
          <p>The latest CLI supports web search with source citation.</p>
        </article>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            return httpx.Response(
                200,
                text=search_html,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if request.url.host == "docs.example.com":
            return httpx.Response(
                200,
                text=page_html,
                headers={"content-type": "text/html; charset=utf-8"},
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        tool = WebSearchTool(max_output_chars=1_000, client=client)
        result = await tool.execute({"query": "latest agent docs", "max_results": 1})

    assert result.ok
    assert "Reference summary:" in result.content
    assert "Agent Docs" in result.content
    assert "web search with source citation" in result.content
    assert result.meta["search_query"] == "latest agent docs"
    assert result.meta["sources"][0]["url"] == "https://docs.example.com/agent"


@pytest.mark.asyncio
async def test_web_search_tavily_requires_api_key():
    tool = WebSearchTool(max_output_chars=500, provider="tavily")

    result = await tool.execute({"query": "asen cli docs"})

    assert not result.ok
    assert "ASEN_SEARCH_API_KEY" in result.error
