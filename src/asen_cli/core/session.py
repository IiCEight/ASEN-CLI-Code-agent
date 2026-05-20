from __future__ import annotations

from typing import Protocol

from ..config import AsenConfig
from ..ui.slash import ParsedSlashCommand, help_text, parse_slash_command
from ..utils.errors import AsenError
from .agent import Agent


class ConsoleLike(Protocol):
    def title(self) -> None: ...
    def clear(self) -> None: ...
    def info(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...
    def assistant(self, message: str) -> None: ...
    def tools(self, schemas: list[dict]) -> None: ...
    def config(self, data: dict) -> None: ...


class InputReaderLike(Protocol):
    async def read(self) -> str: ...
    async def read_multiline(self, *, end_marker: str = "EOF") -> str: ...


class ChatSession:
    def __init__(
        self,
        *,
        agent: Agent,
        config: AsenConfig,
        console: ConsoleLike,
        input_reader: InputReaderLike,
    ) -> None:
        self.agent = agent
        self.config = config
        self.console = console
        self.input_reader = input_reader

    async def run(self) -> None:
        self.console.title()
        while True:
            user_input = await self.input_reader.read()
            if not user_input:
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
            self.console.clear()
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
            self.console.info("Paste multiline input. Finish with a single EOF line.")
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
