from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

SLASH_COMMANDS = [
    "/help",
    "/clear",
    "/exit",
    "/quit",
    "/tools",
    "/config",
    "/paste",
]

PROMPT_STYLE = Style.from_dict(
    {
        "prompt.app": "bold ansicyan",
        "prompt.sep": "ansibrightblack",
        "toolbar": "ansibrightblack bg:#111827",
    }
)


class InputReader:
    def __init__(self, history_path: Path | None = None) -> None:
        if history_path is None:
            history_path = Path.home() / ".asen" / "history.txt"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        self.session: PromptSession[str] = PromptSession(
            history=FileHistory(str(history_path)),
            completer=WordCompleter(SLASH_COMMANDS, ignore_case=True),
            complete_while_typing=True,
            style=PROMPT_STYLE,
            bottom_toolbar=HTML(
                "<toolbar> /help  /tools  /config  /paste  /clear  /exit </toolbar>"
            ),
        )

    async def read(self) -> str:
        prompt = HTML('<prompt.app>asen</prompt.app><prompt.sep> ❯ </prompt.sep>')
        return (await self.session.prompt_async(prompt)).strip()

    async def read_multiline(self, *, end_marker: str = "EOF") -> str:
        lines: list[str] = []
        while True:
            prompt = HTML('<prompt.sep>...</prompt.sep> ')
            line = await self.session.prompt_async(prompt)
            if line.strip() == end_marker:
                break
            lines.append(line)
        return "\n".join(lines).strip()
