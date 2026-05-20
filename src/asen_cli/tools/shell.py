from __future__ import annotations

import asyncio
from pathlib import Path

from pydantic import BaseModel, Field

from ..utils.safety import is_dangerous_command, truncate_text
from .base import ApprovalCallback, BaseTool, ToolResult


class ShellCommandArgs(BaseModel):
    command: str = Field(
        ...,
        min_length=1,
        description="Shell command to run from the workspace.",
    )


class ShellCommandTool(BaseTool):
    name = "shell"
    description = (
        "Run a shell command in the workspace with approval, timeout and output truncation."
    )
    args_model = ShellCommandArgs

    def __init__(
        self,
        workspace: Path,
        *,
        timeout_seconds: int,
        max_output_chars: int,
        require_approval: bool = True,
        confirm: ApprovalCallback | None = None,
    ) -> None:
        self.workspace = workspace
        self.timeout_seconds = timeout_seconds
        self.max_output_chars = max_output_chars
        self.require_approval = require_approval
        self.confirm = confirm

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ShellCommandArgs.model_validate(args)
        command = typed_args.command.strip()
        if is_dangerous_command(command):
            return ToolResult.failure(
                f"Dangerous command blocked: {command}",
                error_type="safety_error",
                retryable=False,
            )
        if self.require_approval:
            prompt = f"Run shell command in {self.workspace}: {command}?"
            if self.confirm is None or not self.confirm(prompt):
                return ToolResult.failure(
                    "Command rejected by user",
                    error_type="user_rejected",
                    retryable=False,
                )

        process = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds
            )
        except TimeoutError:
            process.kill()
            await process.communicate()
            return ToolResult.failure(
                f"Command timed out after {self.timeout_seconds}s",
                error_type="timeout",
                retryable=True,
            )

        output = ""
        if stdout:
            output += stdout.decode(errors="replace")
        if stderr:
            output += stderr.decode(errors="replace")
        rendered = f"exit_code={process.returncode}\n{truncate_text(output, self.max_output_chars)}"
        return ToolResult.success(rendered)
