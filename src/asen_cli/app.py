from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from . import __version__
from .config import (
    get_config_path,
    get_config_value,
    init_config_file,
    load_config,
    mask_config,
    read_config_file,
    set_config_value,
)
from .core.agent import Agent, load_system_prompt
from .core.session import ChatSession
from .llm.factory import create_llm_client
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
config_app = typer.Typer(
    help="Show and manage asen cli configuration.",
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
    stream: Annotated[
        bool,
        typer.Option("--stream/--no-stream", help="Stream assistant output as it arrives."),
    ] = True,
) -> None:
    """Start an interactive coding-agent session."""
    asyncio.run(_chat(config, workspace, no_approval, verbose, stream))


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
    stream: Annotated[
        bool,
        typer.Option("--stream/--no-stream", help="Stream assistant output as it arrives."),
    ] = True,
) -> None:
    """Run a one-shot task and print the final answer."""
    asyncio.run(_ask(task, config, workspace, no_approval, verbose, stream))


@config_app.callback(invoke_without_command=True)
def config_callback(
    ctx: typer.Context,
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
) -> None:
    """Print resolved configuration without revealing the API key."""
    if ctx.invoked_subcommand is not None:
        return
    console = AsenConsole()
    try:
        cfg = load_config(config, workspace=workspace)
        console.config(mask_config(cfg.model_dump(mode="json")))
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@config_app.command("get")
def config_get(
    key: Annotated[str | None, typer.Argument(help="Config key to read.")] = None,
    global_config: Annotated[
        bool,
        typer.Option("--global", help="Read from ~/.asen/config.yaml instead of resolved config."),
    ] = False,
    project_config: Annotated[
        bool,
        typer.Option("--project", help="Read from .asen/config.yaml instead of resolved config."),
    ] = False,
) -> None:
    """Get resolved configuration or one key."""
    console = AsenConsole()
    try:
        if global_config or project_config:
            path = get_config_path(_config_scope(global_config, project_config))
            data = mask_config(read_config_file(path))
            if key is None:
                console.config(data)
                return
            console.info(str(data.get(key, "")))
            return

        cfg = load_config()
        if key is None:
            console.config(mask_config(cfg.model_dump(mode="json")))
            return
        value = get_config_value(cfg, key)
        console.info("***" if key == "api_key" and value else str(value))
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to set.")],
    value: Annotated[str, typer.Argument(help="Config value to write.")],
    global_config: Annotated[
        bool,
        typer.Option("--global", help="Write to ~/.asen/config.yaml."),
    ] = False,
    project_config: Annotated[
        bool,
        typer.Option("--project", help="Write to .asen/config.yaml. Default."),
    ] = False,
) -> None:
    """Set a config key in project or global config."""
    console = AsenConsole()
    try:
        path = get_config_path(_config_scope(global_config, project_config))
        set_config_value(path, key, value)
        console.success(f"Set {key} in {path}")
    except (AsenError, ValueError) as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@config_app.command("init")
def config_init(
    global_config: Annotated[
        bool,
        typer.Option("--global", help="Create ~/.asen/config.yaml."),
    ] = False,
    project_config: Annotated[
        bool,
        typer.Option("--project", help="Create .asen/config.yaml. Default."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing config."),
    ] = False,
) -> None:
    """Create a starter config file."""
    console = AsenConsole()
    try:
        path = get_config_path(_config_scope(global_config, project_config))
        created = init_config_file(path, force=force)
        console.success(f"Initialized config: {created}")
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


app.add_typer(config_app, name="config")


async def _chat(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
    stream: bool,
) -> None:
    console = AsenConsole(verbose=verbose)
    agent = _build_agent(config_path, workspace, no_approval, console, stream)
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
    stream: bool,
) -> None:
    console = AsenConsole(verbose=verbose)
    agent = _build_agent(config_path, workspace, no_approval, console, stream)
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
    stream: bool,
) -> Agent:
    overrides = {"require_approval": False} if no_approval else None
    cfg = load_config(config_path, workspace=workspace, overrides=overrides)
    registry = create_default_registry(cfg, confirm=console.confirm)
    return Agent(
        config=cfg,
        llm=create_llm_client(cfg),
        tools=registry,
        system_prompt=load_system_prompt(),
        events=console.agent_events(),
        stream=stream,
    )


def _config_scope(global_config: bool, project_config: bool) -> str:
    if global_config and project_config:
        raise AsenError("Use only one of --global or --project")
    return "global" if global_config else "project"
