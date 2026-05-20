import pytest

from asen_cli.tools.file import ReadFileTool
from asen_cli.tools.registry import ToolRegistry


@pytest.mark.asyncio
async def test_registry_records_successful_tool_execution(tmp_path):
    (tmp_path / "hello.txt").write_text("hello", encoding="utf-8")
    registry = ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)])

    result = await registry.execute("read_file", {"path": "hello.txt"})

    assert result.ok
    logs = registry.logs()
    assert len(logs) == 1
    assert logs[0].name == "read_file"
    assert logs[0].arguments == {"path": "hello.txt"}
    assert logs[0].ok is True
    assert logs[0].elapsed_ms >= 0


@pytest.mark.asyncio
async def test_registry_records_validation_failure(tmp_path):
    registry = ToolRegistry([ReadFileTool(tmp_path, max_file_bytes=100)])

    result = await registry.execute("read_file", {})

    assert not result.ok
    assert result.error_type == "validation_error"
    assert result.retryable is True
    logs = registry.logs()
    assert logs[0].ok is False
    assert logs[0].error_type == "validation_error"


@pytest.mark.asyncio
async def test_registry_unknown_tool_is_logged(tmp_path):
    registry = ToolRegistry([])

    result = await registry.execute("missing", {})

    assert not result.ok
    assert result.error_type == "unknown_tool"
    assert result.retryable is True
    assert registry.logs()[0].name == "missing"
