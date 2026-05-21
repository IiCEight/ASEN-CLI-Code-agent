import sys

import pytest

from asen_cli.config import AsenConfig
from asen_cli.core.shell_mode import InteractiveShellRunner


@pytest.mark.asyncio
async def test_interactive_shell_runner_executes_safe_command_without_confirmation(tmp_path):
    confirmations = []
    runner = InteractiveShellRunner(
        AsenConfig(
            workspace=tmp_path,
            require_approval=True,
            command_timeout_seconds=5,
            max_tool_output_chars=500,
        ),
        confirm=lambda prompt: confirmations.append(prompt) or True,
    )

    result = await runner.execute(f"{sys.executable} -c 'print(42)'")

    assert result.ok
    assert "42" in result.content
    assert confirmations == []


@pytest.mark.asyncio
async def test_interactive_shell_runner_confirms_high_risk_command(tmp_path):
    confirmations = []
    runner = InteractiveShellRunner(
        AsenConfig(
            workspace=tmp_path,
            require_approval=True,
            command_timeout_seconds=5,
            max_tool_output_chars=500,
        ),
        confirm=lambda prompt: confirmations.append(prompt) or True,
    )

    result = await runner.execute("echo hello > created.txt")

    assert result.ok
    assert (tmp_path / "created.txt").read_text(encoding="utf-8").strip() == "hello"
    assert len(confirmations) == 1
    assert "High-risk shell command" in confirmations[0]


@pytest.mark.asyncio
async def test_interactive_shell_runner_rejects_high_risk_command_when_not_approved(tmp_path):
    runner = InteractiveShellRunner(
        AsenConfig(workspace=tmp_path, require_approval=True),
        confirm=lambda _: False,
    )

    result = await runner.execute("echo hello > blocked.txt")

    assert not result.ok
    assert result.error_type == "user_rejected"
    assert not (tmp_path / "blocked.txt").exists()


@pytest.mark.asyncio
async def test_interactive_shell_runner_blocks_dangerous_command(tmp_path):
    runner = InteractiveShellRunner(
        AsenConfig(workspace=tmp_path, require_approval=False),
        confirm=lambda _: True,
    )

    result = await runner.execute("sudo rm -rf /")

    assert not result.ok
    assert result.error_type == "safety_error"


@pytest.mark.asyncio
async def test_interactive_shell_runner_skips_confirmation_when_approvals_disabled(tmp_path):
    confirmations = []
    runner = InteractiveShellRunner(
        AsenConfig(
            workspace=tmp_path,
            require_approval=False,
            command_timeout_seconds=5,
            max_tool_output_chars=500,
        ),
        confirm=lambda prompt: confirmations.append(prompt) or True,
    )

    result = await runner.execute("echo hello > auto.txt")

    assert result.ok
    assert (tmp_path / "auto.txt").read_text(encoding="utf-8").strip() == "hello"
    assert confirmations == []
