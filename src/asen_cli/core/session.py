from __future__ import annotations

from typing import Protocol

from ..config import AsenConfig
from ..tools.base import ToolResult
from ..ui.slash import ParsedSlashCommand, help_text, parse_slash_command
from ..utils.errors import AsenError
from .agent import Agent
from .shell_mode import InteractiveShellRunner, render_shell_context


class ConsoleLike(Protocol):
    def title(self, mode: str = "chat") -> None: ...
    def clear(self, mode: str = "chat") -> None: ...
    def info(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def assistant(self, message: str) -> None: ...
    def tools(self, schemas: list[dict]) -> None: ...
    def config(self, data: dict) -> None: ...
    def help(self, message: str) -> None: ...
    def paste_hint(self) -> None: ...
    def goodbye(self) -> None: ...
    def shell_command(self, command: str) -> None: ...
    def shell_result(self, command: str, rendered: str) -> None: ...


class InputReaderLike(Protocol):
    async def read(self) -> str: ...
    async def read_multiline(self, *, end_marker: str = "EOF") -> str: ...


class ShellRunnerLike(Protocol):
    async def execute(self, raw_command: str) -> ToolResult: ...


class ChatSession:
    def __init__(
        self,
        *,
        agent: Agent,
        config: AsenConfig,
        console: ConsoleLike,
        input_reader: InputReaderLike,
        shell_runner: ShellRunnerLike | None = None,
        session_mode: str = "chat",
    ) -> None:
        self.agent = agent
        self.config = config
        self.console = console
        self.input_reader = input_reader
        self.session_mode = session_mode
        confirm = getattr(console, "confirm", None)
        self.shell_runner = shell_runner or InteractiveShellRunner(config, confirm=confirm)

    async def run(self) -> None:
        self.console.title(self.session_mode)
        if self.session_mode == "shell":
            self.console.info(
                "Shell mode enabled. Use !command to run in the workspace; "
                "plain text still talks to the agent."
            )
        while True:
            user_input = await self.input_reader.read()
            if not user_input:
                continue

            if user_input.startswith("!"):
                await self._run_shell_command(user_input[1:])
                continue

            command = parse_slash_command(user_input)
            if command is not None:
                should_continue = await self._handle_slash(command)
                if not should_continue:
                    return
                continue

            await self._run_agent(user_input)

    async def _handle_slash(self, command: ParsedSlashCommand) -> bool:
        if command.name in {"/exit", "/quit"}:
            self.console.goodbye()
            return False
        if command.name == "/help":
            self.console.help(help_text())
            return True
        if command.name == "/clear":
            self.console.clear(self.session_mode)
            return True
        if command.name == "/tools":
            self.console.tools(self.agent.tools.schemas())
            return True
        if command.name == "/config":
            data = self.config.model_dump(mode="json")
            data["api_key"] = "***" if self.config.api_key else None
            self.console.config(data)
            return True
        if command.name == "/paste":
            self.console.paste_hint()
            pasted = await self.input_reader.read_multiline(end_marker="EOF")
            if pasted:
                await self._run_agent(pasted)
            return True

        self.console.error(f"Unknown slash command: {command.name}. Type /help.")
        return True

    async def _run_agent(self, user_input: str) -> None:
        try:
            answer = await self.agent.run(user_input)
            self.console.assistant(answer)
        except AsenError as exc:
            self.console.error(str(exc))

    async def _run_shell_command(self, raw_command: str) -> None:
        command = raw_command.strip()
        if not command:
            self.console.error("Shell command cannot be empty after '!'.")
            return

        self.console.shell_command(command)
        result = await self.shell_runner.execute(command)
        rendered = result.render()
        self.console.shell_result(command, rendered)
        self.agent.context.add_tool("shell", render_shell_context(command, rendered))
