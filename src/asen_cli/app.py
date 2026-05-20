from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import load_config
from .core.agent import Agent, load_system_prompt
from .core.llm import OpenAICompatibleClient
from .core.session import ChatSession
from .tools import create_default_registry
from .ui.console import AsenConsole
from .ui.input import InputReader
from .utils.errors import AsenError

app = typer.Typer(
    name="asen",
    help="Teaching-friendly CLI coding agent.",
    no_args_is_help=True,
    invoke_without_command=True,
)


@app.callback()
def version_callback(
    version: Annotated[
        bool,
        typer.Option("--version", help="Show version.", is_eager=True),
    ] = False,
) -> None:
    if version:
        typer.echo(f"asen-cli {__version__}")
        raise typer.Exit()


@app.command()
def chat(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
    no_approval: Annotated[
        bool,
        typer.Option(help="Disable approval prompts for demo/testing."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show agent internals."),
    ] = False,
) -> None:
    """Start an interactive coding-agent session."""
    asyncio.run(_chat(config, workspace, no_approval, verbose))


@app.command()
def ask(
    task: Annotated[str, typer.Argument(help="One-shot task for asen cli.")],
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
    no_approval: Annotated[
        bool,
        typer.Option(help="Disable approval prompts for demo/testing."),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show agent internals."),
    ] = False,
) -> None:
    """Run a one-shot task and print the final answer."""
    asyncio.run(_ask(task, config, workspace, no_approval, verbose))


@app.command("config")
def show_config(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
) -> None:
    """Print resolved configuration without revealing the API key."""
    console = AsenConsole()
    cfg = load_config(config, workspace=workspace)
    data = cfg.model_dump(mode="json")
    data["api_key"] = "***" if cfg.api_key else None
    console.config(data)


async def _chat(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
) -> None:
    console = AsenConsole(verbose=verbose)
    agent = _build_agent(config_path, workspace, no_approval, console)
    session = ChatSession(
        agent=agent,
        config=agent.config,
        console=console,
        input_reader=InputReader(),
    )
    await session.run()


async def _ask(
    task: str,
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
) -> None:
    console = AsenConsole(verbose=verbose)
    agent = _build_agent(config_path, workspace, no_approval, console)
    try:
        answer = await agent.run(task)
        console.assistant(answer)
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


def _build_agent(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    console: AsenConsole,
) -> Agent:
    overrides = {"require_approval": False} if no_approval else None
    cfg = load_config(config_path, workspace=workspace, overrides=overrides)
    registry = create_default_registry(cfg, confirm=console.confirm)
    return Agent(
        config=cfg,
        llm=OpenAICompatibleClient(cfg),
        tools=registry,
        system_prompt=load_system_prompt(),
        events=console.agent_events(),
    )
