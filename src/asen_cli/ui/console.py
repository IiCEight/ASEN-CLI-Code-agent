from __future__ import annotations

from typing import Any

from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

from ..core.agent import AgentEvents
from ..core.protocol import PlanStep

BANNER = r"""
    ___   _____ ______ _   __
   /   | / ___// ____// | / /
  / /| | \__ \/ __/  /  |/ /
 / ___ |___/ / /___ / /|  /
/_/  |_/____/_____//_/ |_/
""".strip("\n")

STATUS_STYLES = {
    "pending": "dim",
    "in_progress": "yellow",
    "completed": "green",
    "failed": "red",
}

STATUS_LABELS = {
    "pending": "pending",
    "in_progress": "running",
    "completed": "done",
    "failed": "failed",
}


class AsenConsole:
    def __init__(self, *, verbose: bool = False) -> None:
        self.console = Console()
        self.verbose_enabled = verbose

    def title(self) -> None:
        banner = Text(BANNER, style="bold cyan")
        subtitle = Text(
            "Teaching-friendly CLI coding agent · type /help to start",
            style="dim white",
        )
        body = Group(Align.center(banner), Align.center(subtitle))
        self.console.print(
            Panel(
                body,
                title="[bold cyan]asen chat[/]",
                subtitle="[dim]/tools  /config  /paste  /exit[/]",
                border_style="bright_cyan",
                box=box.DOUBLE,
                padding=(1, 2),
            )
        )

    def clear(self) -> None:
        self.console.clear()
        self.title()

    def info(self, message: str) -> None:
        self.console.print(f"[cyan]{message}[/]")

    def success(self, message: str) -> None:
        self.console.print(f"[green]{message}[/]")

    def error(self, message: str) -> None:
        self.console.print(
            Panel(message, title="error", border_style="red", box=box.ROUNDED)
        )

    def assistant(self, message: str) -> None:
        self.console.print(
            Panel(
                Markdown(message),
                title="[bold green]asen[/]",
                border_style="green",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def thinking(self, step: int) -> None:
        self.console.print(f"[bright_cyan]╭─ thinking[/] [dim]step {step}[/]")

    def plan(self, steps: list[PlanStep]) -> None:
        table = Table(
            title="Execution Plan",
            box=box.SIMPLE_HEAVY,
            header_style="bold blue",
            border_style="blue",
        )
        table.add_column("#", style="bold blue", no_wrap=True)
        table.add_column("Status", no_wrap=True)
        table.add_column("Task", style="white")
        for step in steps:
            table.add_row(
                step.id,
                _render_status(step.status),
                step.content,
            )
        self.console.print(table)

    def plan_step(self, step: PlanStep) -> None:
        self.console.print(
            f"[blue]├─ plan[/] {step.id}. {step.content} [{_render_status(step.status)}]"
        )

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        if self.verbose_enabled:
            self.console.print(
                Panel(
                    str(arguments),
                    title=f"[yellow]tool call · {name}[/]",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
            return
        self.console.print(f"[yellow]├─ tool[/] [bold]{name}[/]")

    def tool_result(self, name: str, rendered: str) -> None:
        if self.verbose_enabled:
            self.console.print(
                Panel(
                    rendered,
                    title=f"[yellow]tool result · {name}[/]",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )

    def raw_llm_response(self, raw_response: str) -> None:
        if self.verbose_enabled:
            self.console.print(
                Panel(
                    raw_response,
                    title="raw llm response",
                    border_style="dim",
                    box=box.ROUNDED,
                )
            )

    def tools(self, schemas: list[dict[str, Any]]) -> None:
        table = Table(
            title="Agent Toolbelt",
            box=box.SIMPLE_HEAVY,
            header_style="bold cyan",
            border_style="cyan",
        )
        table.add_column("Tool", style="bold cyan", no_wrap=True)
        table.add_column("Description", style="white")
        for schema in schemas:
            table.add_row(str(schema.get("name", "")), str(schema.get("description", "")))
        self.console.print(table)

    def config(self, data: dict[str, Any]) -> None:
        table = Table(
            title="Runtime Config",
            box=box.SIMPLE_HEAVY,
            header_style="bold magenta",
            border_style="magenta",
        )
        table.add_column("Key", style="bold magenta", no_wrap=True)
        table.add_column("Value", style="white")
        for key, value in data.items():
            table.add_row(str(key), str(value))
        self.console.print(table)

    def help(self, message: str) -> None:
        self.console.print(
            Panel(
                message,
                title="slash commands",
                border_style="cyan",
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )

    def paste_hint(self) -> None:
        self.console.print(
            Panel(
                "Paste multiline input below. Finish with a single EOF line.",
                title="paste mode",
                border_style="blue",
                box=box.ROUNDED,
            )
        )

    def goodbye(self) -> None:
        self.console.print("[dim]session closed. bye.[/]")

    def verbose(self, message: str) -> None:
        if self.verbose_enabled:
            self.console.print(f"[dim]{message}[/]")

    def confirm(self, message: str) -> bool:
        self.console.print(
            Panel(message, title="approval required", border_style="magenta", box=box.ROUNDED)
        )
        return Confirm.ask("Approve", default=False)

    def agent_events(self) -> AgentEvents:
        return AgentEvents(
            on_thinking=self.thinking,
            on_llm_response=self.raw_llm_response,
            on_plan=self.plan,
            on_plan_step=self.plan_step,
            on_tool_call=self.tool_call,
            on_tool_result=self.tool_result,
        )


def _render_status(status: str) -> str:
    style = STATUS_STYLES.get(status, "white")
    label = STATUS_LABELS.get(status, status)
    return f"[{style}]{label}[/]"
