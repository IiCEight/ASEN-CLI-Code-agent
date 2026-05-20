import httpx
import pytest

from asen_cli.tools.web import WebFetchTool


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


@pytest.mark.asyncio
async def test_web_fetch_rejects_non_http_url():
    tool = WebFetchTool(max_output_chars=100)

    result = await tool.execute({"url": "file:///etc/passwd"})

    assert not result.ok
    assert "http" in result.error
