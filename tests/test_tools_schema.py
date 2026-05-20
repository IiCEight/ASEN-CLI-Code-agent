import pytest

from asen_cli.tools.file import ReadFileTool, WriteFileTool
from asen_cli.tools.shell import ShellCommandTool
from asen_cli.tools.web import WebFetchTool


def test_read_file_schema_uses_json_schema(tmp_path):
    schema = ReadFileTool(tmp_path, max_file_bytes=100).schema()

    assert schema["name"] == "read_file"
    assert schema["parameters"]["type"] == "object"
    assert "path" in schema["parameters"]["properties"]
    assert "path" in schema["parameters"]["required"]
    assert "arguments" not in schema


def test_write_file_schema_includes_defaults(tmp_path):
    schema = WriteFileTool(tmp_path, require_approval=False).schema()

    overwrite = schema["parameters"]["properties"]["overwrite"]
    assert overwrite["default"] is True
    assert set(schema["parameters"]["required"]) == {"path", "content"}


@pytest.mark.asyncio
async def test_missing_required_argument_is_validation_error(tmp_path):
    tool = ReadFileTool(tmp_path, max_file_bytes=100)

    result = await tool.execute({})

    assert not result.ok
    assert result.error_type == "validation_error"
    assert result.retryable is True
    assert "path" in result.error


@pytest.mark.asyncio
async def test_shell_empty_command_is_validation_error(tmp_path):
    tool = ShellCommandTool(
        tmp_path,
        timeout_seconds=5,
        max_output_chars=100,
        require_approval=False,
    )

    result = await tool.execute({"command": ""})

    assert not result.ok
    assert result.error_type == "validation_error"
    assert result.retryable is True


@pytest.mark.asyncio
async def test_web_fetch_rejects_invalid_url_as_validation_error():
    tool = WebFetchTool(max_output_chars=100)

    result = await tool.execute({"url": "file:///etc/passwd"})

    assert not result.ok
    assert result.error_type == "validation_error"
    assert result.retryable is True
    assert "http" in result.error
