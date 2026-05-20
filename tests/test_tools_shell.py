import sys

import pytest

from asen_cli.tools.shell import ShellCommandTool


@pytest.mark.asyncio
async def test_shell_command_runs_with_approval(tmp_path):
    tool = ShellCommandTool(
        tmp_path,
        timeout_seconds=5,
        max_output_chars=500,
        require_approval=True,
        confirm=lambda _: True,
    )

    result = await tool.execute({"command": f"{sys.executable} -c 'print(42)'"})

    assert result.ok
    assert "exit_code=0" in result.content
    assert "42" in result.content


@pytest.mark.asyncio
async def test_shell_command_rejected(tmp_path):
    tool = ShellCommandTool(
        tmp_path,
        timeout_seconds=5,
        max_output_chars=500,
        require_approval=True,
        confirm=lambda _: False,
    )

    result = await tool.execute({"command": "echo nope"})

    assert not result.ok
    assert "rejected" in result.error


@pytest.mark.asyncio
async def test_shell_dangerous_command_blocked(tmp_path):
    tool = ShellCommandTool(
        tmp_path,
        timeout_seconds=5,
        max_output_chars=500,
        require_approval=False,
    )

    result = await tool.execute({"command": "sudo rm -rf /"})

    assert not result.ok
    assert "Dangerous command" in result.error
