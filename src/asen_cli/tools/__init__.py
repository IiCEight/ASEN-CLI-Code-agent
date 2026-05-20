from __future__ import annotations

from collections.abc import Callable

from ..config import AsenConfig
from .edit import ApplyPatchTool, ReplaceInFileTool
from .file import ListFilesTool, ReadFileChunkTool, ReadFileTool, WriteFileTool
from .registry import ToolRegistry
from .search import (
    FindFilesTool,
    GrepContextTool,
    ReadManyFilesTool,
    SearchTextTool,
    ShowTreeTool,
)
from .shell import ShellCommandTool
from .web import WebFetchTool


def create_default_registry(
    config: AsenConfig,
    *,
    confirm: Callable[[str], bool] | None = None,
) -> ToolRegistry:
    return ToolRegistry(
        [
            ReadFileTool(config.workspace, config.max_file_bytes),
            ReadFileChunkTool(config.workspace, config.max_file_bytes),
            WriteFileTool(
                config.workspace,
                require_approval=config.require_approval,
                confirm=confirm,
            ),
            ReplaceInFileTool(
                config.workspace,
                require_approval=config.require_approval,
                confirm=confirm,
                max_output_chars=config.max_tool_output_chars,
            ),
            ApplyPatchTool(
                config.workspace,
                require_approval=config.require_approval,
                confirm=confirm,
                max_output_chars=config.max_tool_output_chars,
            ),
            ListFilesTool(config.workspace, config.max_tool_output_chars),
            FindFilesTool(config.workspace, config.max_tool_output_chars),
            SearchTextTool(config.workspace, config.max_tool_output_chars),
            GrepContextTool(config.workspace, config.max_tool_output_chars),
            ShowTreeTool(config.workspace, config.max_tool_output_chars),
            ReadManyFilesTool(
                config.workspace,
                max_file_bytes=config.max_file_bytes,
                max_output_chars=config.max_tool_output_chars,
            ),
            ShellCommandTool(
                config.workspace,
                timeout_seconds=config.command_timeout_seconds,
                max_output_chars=config.max_tool_output_chars,
                require_approval=config.require_approval,
                confirm=confirm,
            ),
            WebFetchTool(max_output_chars=config.max_tool_output_chars),
        ]
    )


__all__ = ["ToolRegistry", "create_default_registry"]
