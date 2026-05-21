from __future__ import annotations

from collections.abc import Callable

from ..config import AsenConfig
from ..tools.base import ToolResult
from ..tools.shell import ShellCommandTool
from ..utils.safety import assess_command_safety

ApprovalCallback = Callable[[str], bool]


class InteractiveShellRunner:
    def __init__(
        self,
        config: AsenConfig,
        *,
        confirm: ApprovalCallback | None = None,
    ) -> None:
        self.config = config
        self.confirm = confirm
        self.tool = ShellCommandTool(
            config.workspace,
            timeout_seconds=config.command_timeout_seconds,
            max_output_chars=config.max_tool_output_chars,
            require_approval=False,
        )

    async def execute(self, raw_command: str) -> ToolResult:
        command = raw_command.strip()
        if not command:
            return ToolResult.failure(
                "Shell command cannot be empty after '!'.",
                error_type="validation_error",
                retryable=True,
            )

        safety = assess_command_safety(command)
        if safety.level == "blocked":
            return ToolResult.failure(
                f"Blocked shell command: {command}",
                error_type="safety_error",
                retryable=False,
            )

        if safety.level == "confirm" and self.config.require_approval:
            prompt = (
                f"High-risk shell command in {self.config.workspace}:\n"
                f"{command}\n"
                f"Reason: {safety.reason or 'command may modify files or external state'}"
            )
            if self.confirm is None or not self.confirm(prompt):
                return ToolResult.failure(
                    "Command rejected by user",
                    error_type="user_rejected",
                    retryable=False,
                )

        return await self.tool.execute({"command": command})


def render_shell_context(command: str, rendered: str) -> str:
    return f"command={command}\n{rendered}"
