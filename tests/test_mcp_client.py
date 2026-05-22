import sys

import pytest

from asen_cli.config import McpServerConfig
from asen_cli.mcp.client import StdioMcpClient


@pytest.mark.asyncio
async def test_stdio_mcp_client_lists_tools_and_calls_demo_server(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "hello.txt").write_text("hello mcp\n", encoding="utf-8")

    server = McpServerConfig(
        command=sys.executable,
        args=["-m", "asen_cli.mcp.demo_server"],
        cwd=workspace,
        timeout_seconds=5,
    )

    async with StdioMcpClient("filesystem-demo", server, workspace=workspace) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        assert {"list_directory", "read_file", "stat_path"}.issubset(tool_names)

        result = await client.call_tool("read_file", {"path": "hello.txt"})
        assert result.isError is False
        assert "hello mcp" in result.render_text()


@pytest.mark.asyncio
async def test_stdio_mcp_client_reports_tool_error(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    server = McpServerConfig(
        command=sys.executable,
        args=["-m", "asen_cli.mcp.demo_server"],
        cwd=workspace,
        timeout_seconds=5,
    )

    async with StdioMcpClient("filesystem-demo", server, workspace=workspace) as client:
        result = await client.call_tool("read_file", {"path": "missing.txt"})
        assert result.isError is True
        assert "missing.txt" in result.render_text()
