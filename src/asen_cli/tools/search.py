from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from ..utils.errors import SafetyError
from ..utils.safety import resolve_workspace_path, truncate_text
from .base import BaseTool, ToolResult

SKIPPED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    "dist",
    "build",
}


class FindFilesArgs(BaseModel):
    pattern: str = Field(..., description="Filename glob pattern, such as *.py or test_*.py.")
    path: str = Field(default=".", description="Directory path inside the workspace.")
    case_sensitive: bool = Field(default=False, description="Whether matching is case-sensitive.")
    include_hidden: bool = Field(
        default=False,
        description="Whether to include hidden files and dirs.",
    )
    limit: int = Field(default=100, ge=1, le=1000, description="Maximum matched files to return.")


class SearchTextArgs(BaseModel):
    query: str = Field(..., min_length=1, description="Literal text to search for.")
    path: str = Field(default=".", description="Directory path inside the workspace.")
    file_pattern: str = Field(default="*", description="File glob filter, such as *.py.")
    case_sensitive: bool = Field(default=False, description="Whether matching is case-sensitive.")
    max_matches: int = Field(default=50, ge=1, le=500, description="Maximum matches to return.")


class GrepContextArgs(BaseModel):
    pattern: str = Field(..., min_length=1, description="Regular expression pattern to search for.")
    path: str = Field(default=".", description="Directory path inside the workspace.")
    file_pattern: str = Field(default="*", description="File glob filter, such as *.py.")
    case_sensitive: bool = Field(default=False, description="Whether matching is case-sensitive.")
    context_lines: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Context lines before and after match.",
    )
    max_matches: int = Field(default=30, ge=1, le=200, description="Maximum matches to return.")

    @field_validator("pattern")
    @classmethod
    def validate_regex(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex: {exc}") from exc
        return value


class ShowTreeArgs(BaseModel):
    path: str = Field(default=".", description="Directory path inside the workspace.")
    max_depth: int = Field(
        default=3,
        ge=1,
        le=8,
        description="Maximum directory depth to display.",
    )
    include_hidden: bool = Field(
        default=False,
        description="Whether to include hidden files and dirs.",
    )
    max_entries: int = Field(
        default=200,
        ge=1,
        le=1000,
        description="Maximum tree entries to return.",
    )


class ReadManyFilesArgs(BaseModel):
    paths: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description="Files to read inside workspace.",
    )
    max_chars_per_file: int = Field(
        default=8000,
        ge=100,
        le=50000,
        description="Maximum characters to return per file.",
    )


class FindFilesTool(BaseTool):
    name = "find_files"
    description = "Find files by filename glob pattern inside the workspace."
    args_model = FindFilesArgs

    def __init__(self, workspace: Path, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = FindFilesArgs.model_validate(args)
        try:
            root = _resolve_directory(self.workspace, typed_args.path)
            matches: list[str] = []
            for file_path in _iter_files(root, include_hidden=typed_args.include_hidden):
                rel = _relative_to_workspace(self.workspace, file_path)
                matches_name = _glob_match(
                    file_path.name,
                    typed_args.pattern,
                    typed_args.case_sensitive,
                )
                matches_path = _glob_match(
                    rel,
                    typed_args.pattern,
                    typed_args.case_sensitive,
                )
                if matches_name or matches_path:
                    matches.append(rel)
                if len(matches) >= typed_args.limit:
                    break
            if not matches:
                return ToolResult.success("No files matched.")
            return ToolResult.success(truncate_text("\n".join(matches), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class SearchTextTool(BaseTool):
    name = "search_text"
    description = "Search literal text across files in the workspace."
    args_model = SearchTextArgs

    def __init__(self, workspace: Path, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = SearchTextArgs.model_validate(args)
        try:
            root = _resolve_directory(self.workspace, typed_args.path)
            needle = typed_args.query if typed_args.case_sensitive else typed_args.query.lower()
            matches: list[str] = []
            for file_path in _iter_matching_files(root, typed_args.file_pattern):
                lines = _safe_read_lines(file_path)
                if lines is None:
                    continue
                for line_number, line in enumerate(lines, start=1):
                    haystack = line if typed_args.case_sensitive else line.lower()
                    if needle in haystack:
                        rel = _relative_to_workspace(self.workspace, file_path)
                        matches.append(f"{rel}:{line_number}: {line.rstrip()}")
                        if len(matches) >= typed_args.max_matches:
                            return ToolResult.success(
                                truncate_text("\n".join(matches), self.max_output_chars)
                            )
            if not matches:
                return ToolResult.success("No text matches found.")
            return ToolResult.success(truncate_text("\n".join(matches), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class GrepContextTool(BaseTool):
    name = "grep_context"
    description = "Search regex matches and return surrounding context lines."
    args_model = GrepContextArgs

    def __init__(self, workspace: Path, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = GrepContextArgs.model_validate(args)
        flags = 0 if typed_args.case_sensitive else re.IGNORECASE
        regex = re.compile(typed_args.pattern, flags)
        try:
            root = _resolve_directory(self.workspace, typed_args.path)
            blocks: list[str] = []
            match_count = 0
            for file_path in _iter_matching_files(root, typed_args.file_pattern):
                lines = _safe_read_lines(file_path)
                if lines is None:
                    continue
                for index, line in enumerate(lines):
                    if not regex.search(line):
                        continue
                    rel = _relative_to_workspace(self.workspace, file_path)
                    start = max(0, index - typed_args.context_lines)
                    end = min(len(lines), index + typed_args.context_lines + 1)
                    rendered = [f"-- {rel}:{index + 1} --"]
                    for ctx_index in range(start, end):
                        marker = ">" if ctx_index == index else " "
                        rendered.append(f"{marker} {ctx_index + 1}: {lines[ctx_index].rstrip()}")
                    blocks.append("\n".join(rendered))
                    match_count += 1
                    if match_count >= typed_args.max_matches:
                        return ToolResult.success(
                            truncate_text("\n\n".join(blocks), self.max_output_chars)
                        )
            if not blocks:
                return ToolResult.success("No regex matches found.")
            return ToolResult.success(truncate_text("\n\n".join(blocks), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class ShowTreeTool(BaseTool):
    name = "show_tree"
    description = "Show a compact directory tree for the workspace."
    args_model = ShowTreeArgs

    def __init__(self, workspace: Path, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ShowTreeArgs.model_validate(args)
        try:
            root = _resolve_directory(self.workspace, typed_args.path)
            root_label = _relative_to_workspace(self.workspace, root) or "."
            lines = [f"{root_label}/"]
            entry_count = 0
            _append_tree(
                root,
                lines,
                prefix="",
                depth=1,
                max_depth=typed_args.max_depth,
                include_hidden=typed_args.include_hidden,
                max_entries=typed_args.max_entries,
                entry_count_ref=[entry_count],
            )
            return ToolResult.success(truncate_text("\n".join(lines), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class ReadManyFilesTool(BaseTool):
    name = "read_many_files"
    description = "Read multiple UTF-8 text files inside the workspace."
    args_model = ReadManyFilesArgs

    def __init__(self, workspace: Path, max_file_bytes: int, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_file_bytes = max_file_bytes
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ReadManyFilesArgs.model_validate(args)
        blocks: list[str] = []
        try:
            for raw_path in typed_args.paths:
                path = resolve_workspace_path(self.workspace, raw_path)
                rel = _relative_to_workspace(self.workspace, path)
                if not path.exists():
                    blocks.append(f"## {rel}\nERROR[file_not_found]: {path}")
                    continue
                if not path.is_file():
                    blocks.append(f"## {rel}\nERROR[invalid_path]: path is not a file")
                    continue
                size = path.stat().st_size
                if size > self.max_file_bytes:
                    blocks.append(f"## {rel}\nERROR[file_too_large]: {size} bytes")
                    continue
                try:
                    content = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:
                    blocks.append(f"## {rel}\nERROR[decode_error]: file is not UTF-8 text")
                    continue
                blocks.append(f"## {rel}\n{truncate_text(content, typed_args.max_chars_per_file)}")
            return ToolResult.success(truncate_text("\n\n".join(blocks), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


def _resolve_directory(workspace: Path, raw_path: str) -> Path:
    root = resolve_workspace_path(workspace, raw_path)
    if not root.exists():
        raise OSError(f"Directory not found: {root}")
    if not root.is_dir():
        raise OSError(f"Path is not a directory: {root}")
    return root


def _iter_files(root: Path, *, include_hidden: bool = False):
    for item in sorted(root.rglob("*")):
        if _should_skip(item, root, include_hidden=include_hidden):
            continue
        if item.is_file():
            yield item


def _iter_matching_files(root: Path, file_pattern: str):
    for file_path in _iter_files(root):
        rel = file_path.relative_to(root).as_posix()
        if fnmatch.fnmatch(file_path.name, file_pattern) or fnmatch.fnmatch(rel, file_pattern):
            yield file_path


def _should_skip(path: Path, root: Path, *, include_hidden: bool) -> bool:
    rel_parts = path.relative_to(root).parts
    for part in rel_parts:
        if not include_hidden and part.startswith("."):
            return True
        if part in SKIPPED_DIR_NAMES:
            return True
    return False


def _glob_match(value: str, pattern: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return fnmatch.fnmatch(value, pattern)
    return fnmatch.fnmatch(value.lower(), pattern.lower())


def _safe_read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return None


def _relative_to_workspace(workspace: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace.resolve()).as_posix()


def _append_tree(
    root: Path,
    lines: list[str],
    *,
    prefix: str,
    depth: int,
    max_depth: int,
    include_hidden: bool,
    max_entries: int,
    entry_count_ref: list[int],
) -> None:
    if depth > max_depth or entry_count_ref[0] >= max_entries:
        return
    entries = [
        item
        for item in sorted(root.iterdir(), key=lambda path: (not path.is_dir(), path.name.lower()))
        if not _should_skip(item, root, include_hidden=include_hidden)
    ]
    for index, item in enumerate(entries):
        if entry_count_ref[0] >= max_entries:
            lines.append(f"{prefix}└── ...[truncated at {max_entries} entries]")
            return
        connector = "└── " if index == len(entries) - 1 else "├── "
        suffix = "/" if item.is_dir() else ""
        lines.append(f"{prefix}{connector}{item.name}{suffix}")
        entry_count_ref[0] += 1
        if item.is_dir():
            extension = "    " if index == len(entries) - 1 else "│   "
            _append_tree(
                item,
                lines,
                prefix=prefix + extension,
                depth=depth + 1,
                max_depth=max_depth,
                include_hidden=include_hidden,
                max_entries=max_entries,
                entry_count_ref=entry_count_ref,
            )
