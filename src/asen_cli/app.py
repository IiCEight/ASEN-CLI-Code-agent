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
from .core.checkpoint_store import CheckpointStore
from .core.session import ChatSession
from .core.session_store import SessionStore
from .core.shell_mode import InteractiveShellRunner
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
session_app = typer.Typer(
    help="List and resume saved interactive sessions.",
    no_args_is_help=True,
)
checkpoint_app = typer.Typer(
    help="List, diff, and restore saved checkpoints.",
    no_args_is_help=True,
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


@app.command()
def shell(
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
    """Start a shell-heavy interactive session with !command support."""
    asyncio.run(_shell(config, workspace, no_approval, verbose, stream))


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
        typer.Option(
            "--global",
            help="Read from ~/.asen/config.yaml instead of resolved config.",
        ),
    ] = False,
    project_config: Annotated[
        bool,
        typer.Option(
            "--project",
            help="Read from .asen/config.yaml instead of resolved config.",
        ),
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


@session_app.command("list")
def session_list(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
) -> None:
    """List saved sessions in the current workspace."""
    console = AsenConsole()
    try:
        cfg = load_config(config, workspace=workspace)
        sessions = SessionStore.list(cfg.workspace)
        if not sessions:
            console.info("No saved sessions yet. Start one with `asen chat` or `asen shell`.")
            return
        rows = [
            {
                "session_id": item.session_id,
                "session_mode": item.session_mode,
                "updated_at": _compact_timestamp(item.updated_at),
                "turn_count": item.turn_count,
                "tool_call_count": item.tool_call_count,
                "summary_preview": item.summary_preview or item.title,
            }
            for item in sessions
        ]
        console.sessions(rows)
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@session_app.command("resume")
def session_resume(
    session_id: Annotated[
        str,
        typer.Argument(help="Session id or unique prefix to resume."),
    ],
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
    """Resume a saved interactive session."""
    asyncio.run(
        _resume_session(session_id, config, workspace, no_approval, verbose, stream)
    )


@checkpoint_app.command("list")
def checkpoint_list(
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
) -> None:
    """List saved checkpoints in the current workspace."""
    console = AsenConsole()
    try:
        cfg = load_config(config, workspace=workspace)
        checkpoints = CheckpointStore.list(cfg.workspace)
        if not checkpoints:
            console.info("No checkpoints yet. Modify files with asen to create one.")
            return
        rows = [
            {
                "checkpoint_id": item.checkpoint_id,
                "tool_name": item.tool_name,
                "updated_at": _compact_timestamp(item.updated_at),
                "file_count": item.file_count,
                "summary_preview": item.summary_preview or item.title,
            }
            for item in checkpoints
        ]
        console.checkpoints(rows)
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@checkpoint_app.command("diff")
def checkpoint_diff(
    checkpoint_id: Annotated[
        str,
        typer.Argument(help="Checkpoint id or unique prefix to inspect."),
    ],
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
) -> None:
    """Show the captured diff for a checkpoint."""
    console = AsenConsole()
    try:
        cfg = load_config(config, workspace=workspace)
        checkpoint = CheckpointStore.open(cfg.workspace, checkpoint_id)
        console.checkpoint_diff(checkpoint.checkpoint_id, checkpoint.render_diff())
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


@checkpoint_app.command("restore")
def checkpoint_restore(
    checkpoint_id: Annotated[
        str,
        typer.Argument(help="Checkpoint id or unique prefix to restore."),
    ],
    config: Annotated[Path | None, typer.Option("--config", "-c")] = None,
    workspace: Annotated[Path | None, typer.Option("--workspace", "-w")] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="Restore without interactive confirmation."),
    ] = False,
) -> None:
    """Restore files captured by a checkpoint."""
    console = AsenConsole()
    try:
        cfg = load_config(config, workspace=workspace)
        checkpoint = CheckpointStore.open(cfg.workspace, checkpoint_id)
        if not force:
            prompt = (
                f"Restore checkpoint {checkpoint.checkpoint_id}?\n"
                f"This will revert {checkpoint.meta.file_count} file(s).\n"
                f"{checkpoint.meta.summary_preview}"
            )
            if not console.confirm(prompt):
                console.info("Restore cancelled.")
                return
        actions = checkpoint.restore()
        console.success(f"Restored checkpoint {checkpoint.checkpoint_id}")
        for action in actions:
            console.info(action)
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


app.add_typer(config_app, name="config")
app.add_typer(session_app, name="session")
app.add_typer(checkpoint_app, name="checkpoint")


async def _chat(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
    stream: bool,
) -> None:
    await _interactive_session(
        config_path,
        workspace,
        no_approval,
        verbose,
        stream,
        session_mode="chat",
    )


async def _shell(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
    stream: bool,
) -> None:
    await _interactive_session(
        config_path,
        workspace,
        no_approval,
        verbose,
        stream,
        session_mode="shell",
    )


async def _resume_session(
    session_id: str,
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
    stream: bool,
) -> None:
    await _interactive_session(
        config_path,
        workspace,
        no_approval,
        verbose,
        stream,
        session_mode=None,
        resume_session_id=session_id,
    )


async def _interactive_session(
    config_path: Path | None,
    workspace: Path | None,
    no_approval: bool,
    verbose: bool,
    stream: bool,
    *,
    session_mode: str | None,
    resume_session_id: str | None = None,
) -> None:
    console = AsenConsole(verbose=verbose)
    try:
        agent = _build_agent(config_path, workspace, no_approval, console, stream)
        resumed = resume_session_id is not None
        store = (
            SessionStore.open(agent.config.workspace, resume_session_id)
            if resume_session_id is not None
            else SessionStore.create(agent.config, session_mode=session_mode or "chat")
        )
        snapshot = store.latest_snapshot()
        if snapshot:
            agent.load_context_snapshot(snapshot)
        resolved_mode = store.meta.session_mode if resumed else (session_mode or "chat")
        session = ChatSession(
            agent=agent,
            config=agent.config,
            console=console,
            input_reader=InputReader(),
            shell_runner=InteractiveShellRunner(agent.config, confirm=console.confirm),
            session_mode=resolved_mode,
            session_store=store,
            resumed=resumed,
        )
        await session.run()
    except AsenError as exc:
        console.error(str(exc))
        raise typer.Exit(code=1) from exc


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


def _compact_timestamp(value: str) -> str:
    return value.replace("T", " ").replace("+00:00", " UTC")[:23]
