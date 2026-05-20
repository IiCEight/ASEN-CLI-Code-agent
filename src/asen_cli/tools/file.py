from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..utils.errors import SafetyError
from ..utils.safety import resolve_workspace_path, truncate_text
from .base import ApprovalCallback, BaseTool, ToolResult


class ReadFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Relative or absolute path inside the workspace.",
    )


class WriteFileArgs(BaseModel):
    path: str = Field(
        ...,
        description="Relative or absolute path inside the workspace.",
    )
    content: str = Field(..., description="UTF-8 text content to write.")
    overwrite: bool = Field(
        default=True,
        description="Whether to overwrite an existing file.",
    )


class ReadFileChunkArgs(BaseModel):
    path: str = Field(
        ...,
        description="Relative or absolute path inside the workspace.",
    )
    start_line: int = Field(default=1, ge=1, description="1-based line number to start from.")
    max_lines: int = Field(default=200, ge=1, le=1000, description="Maximum lines to read.")


class ListFilesArgs(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path inside the workspace.",
    )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a UTF-8 text file inside the workspace."
    args_model = ReadFileArgs

    def __init__(self, workspace: Path, max_file_bytes: int) -> None:
        self.workspace = workspace
        self.max_file_bytes = max_file_bytes

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ReadFileArgs.model_validate(args)
        try:
            path = resolve_workspace_path(self.workspace, typed_args.path)
            if not path.exists():
                return ToolResult.failure(
                    f"File not found: {path}",
                    error_type="file_not_found",
                    retryable=True,
                )
            if not path.is_file():
                return ToolResult.failure(
                    f"Path is not a file: {path}",
                    error_type="invalid_path",
                    retryable=True,
                )
            size = path.stat().st_size
            if size > self.max_file_bytes:
                return ToolResult.failure(
                    f"File is too large: {size} bytes",
                    error_type="file_too_large",
                    retryable=False,
                )
            return ToolResult.success(path.read_text(encoding="utf-8"))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class ReadFileChunkTool(BaseTool):
    name = "read_file_chunk"
    description = "Read a line range from a UTF-8 text file inside the workspace."
    args_model = ReadFileChunkArgs

    def __init__(self, workspace: Path, max_file_bytes: int) -> None:
        self.workspace = workspace
        self.max_file_bytes = max_file_bytes

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ReadFileChunkArgs.model_validate(args)
        try:
            path = resolve_workspace_path(self.workspace, typed_args.path)
            if not path.exists():
                return ToolResult.failure(
                    f"File not found: {path}",
                    error_type="file_not_found",
                    retryable=True,
                )
            if not path.is_file():
                return ToolResult.failure(
                    f"Path is not a file: {path}",
                    error_type="invalid_path",
                    retryable=True,
                )
            size = path.stat().st_size
            if size > self.max_file_bytes * 10:
                return ToolResult.failure(
                    f"File is too large for chunked reading: {size} bytes",
                    error_type="file_too_large",
                    retryable=False,
                )
            lines = path.read_text(encoding="utf-8").splitlines()
            start_index = typed_args.start_line - 1
            end_index = min(len(lines), start_index + typed_args.max_lines)
            selected = lines[start_index:end_index]
            numbered = [
                f"{line_number}: {line}"
                for line_number, line in enumerate(selected, start=typed_args.start_line)
            ]
            header = (
                f"{path.name} lines {typed_args.start_line}-{end_index} "
                f"of {len(lines)}"
            )
            return ToolResult.success(header + "\n" + "\n".join(numbered))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except (OSError, UnicodeDecodeError) as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write a UTF-8 text file inside the workspace after approval."
    args_model = WriteFileArgs

    def __init__(
        self,
        workspace: Path,
        *,
        require_approval: bool = True,
        confirm: ApprovalCallback | None = None,
    ) -> None:
        self.workspace = workspace
        self.require_approval = require_approval
        self.confirm = confirm

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = WriteFileArgs.model_validate(args)
        try:
            path = resolve_workspace_path(self.workspace, typed_args.path)
            if path.exists() and not typed_args.overwrite:
                return ToolResult.failure(
                    f"File already exists: {path}",
                    error_type="file_exists",
                    retryable=True,
                )
            if self.require_approval:
                prompt = f"Write {len(typed_args.content)} chars to {path}?"
                if self.confirm is None or not self.confirm(prompt):
                    return ToolResult.failure(
                        "Write rejected by user",
                        error_type="user_rejected",
                        retryable=False,
                    )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(typed_args.content, encoding="utf-8")
            return ToolResult.success(f"Wrote {len(typed_args.content)} chars to {path}")
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files under a directory inside the workspace."
    args_model = ListFilesArgs

    def __init__(self, workspace: Path, max_output_chars: int) -> None:
        self.workspace = workspace
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ListFilesArgs.model_validate(args)
        try:
            root = resolve_workspace_path(self.workspace, typed_args.path)
            if not root.exists():
                return ToolResult.failure(
                    f"Directory not found: {root}",
                    error_type="file_not_found",
                    retryable=True,
                )
            if not root.is_dir():
                return ToolResult.failure(
                    f"Path is not a directory: {root}",
                    error_type="invalid_path",
                    retryable=True,
                )
            lines: list[str] = []
            for item in sorted(root.rglob("*")):
                if any(part.startswith(".") for part in item.relative_to(root).parts):
                    continue
                marker = "/" if item.is_dir() else ""
                lines.append(f"{item.relative_to(root)}{marker}")
            return ToolResult.success(truncate_text("\n".join(lines), self.max_output_chars))
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)
