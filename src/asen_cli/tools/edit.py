from __future__ import annotations

import difflib
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.checkpoint_store import CheckpointStore
from ..utils.errors import SafetyError
from ..utils.safety import resolve_workspace_path, truncate_text
from .base import ApprovalCallback, BaseTool, ToolResult

HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


class ReplaceInFileArgs(BaseModel):
    path: str = Field(..., description="File path inside the workspace.")
    old_text: str = Field(..., min_length=1, description="Exact text to replace.")
    new_text: str = Field(..., description="Replacement text.")
    expected_replacements: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Expected number of replacements. Default requires exactly one match.",
    )
    dry_run: bool = Field(default=False, description="Show diff without writing the file.")


class ApplyPatchArgs(BaseModel):
    path: str = Field(..., description="Target file path inside the workspace.")
    patch: str = Field(..., min_length=1, description="Unified diff patch for the target file.")
    dry_run: bool = Field(
        default=False,
        description="Show resulting diff without writing the file.",
    )


class ReplaceInFileTool(BaseTool):
    name = "replace_in_file"
    description = "Safely replace exact text in a file using a diff-first workflow."
    args_model = ReplaceInFileArgs

    def __init__(
        self,
        workspace: Path,
        *,
        require_approval: bool = True,
        confirm: ApprovalCallback | None = None,
        max_output_chars: int,
    ) -> None:
        self.workspace = workspace
        self.require_approval = require_approval
        self.confirm = confirm
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ReplaceInFileArgs.model_validate(args)
        try:
            path = _resolve_text_file(self.workspace, typed_args.path)
            original = path.read_text(encoding="utf-8")
            count = original.count(typed_args.old_text)
            if count == 0:
                return ToolResult.failure(
                    "old_text was not found in the target file",
                    error_type="text_not_found",
                    retryable=True,
                )
            if count != typed_args.expected_replacements:
                return ToolResult.failure(
                    f"expected {typed_args.expected_replacements} replacements, found {count}",
                    error_type="replacement_count_mismatch",
                    retryable=True,
                )

            updated = original.replace(
                typed_args.old_text,
                typed_args.new_text,
                typed_args.expected_replacements,
            )
            return _maybe_write_diff_first(
                workspace=self.workspace,
                path=path,
                original=original,
                updated=updated,
                dry_run=typed_args.dry_run,
                require_approval=self.require_approval,
                confirm=self.confirm,
                max_output_chars=self.max_output_chars,
                tool_name=self.name,
            )
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except UnicodeDecodeError as exc:
            return ToolResult.failure(str(exc), error_type="decode_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = (
        "Apply a unified diff patch to one file using approval, snapshot and dry-run support."
    )
    args_model = ApplyPatchArgs

    def __init__(
        self,
        workspace: Path,
        *,
        require_approval: bool = True,
        confirm: ApprovalCallback | None = None,
        max_output_chars: int,
    ) -> None:
        self.workspace = workspace
        self.require_approval = require_approval
        self.confirm = confirm
        self.max_output_chars = max_output_chars

    async def _run(self, args: BaseModel) -> ToolResult:
        typed_args = ApplyPatchArgs.model_validate(args)
        try:
            path = _resolve_text_file(self.workspace, typed_args.path)
            original = path.read_text(encoding="utf-8")
            updated = _apply_unified_patch(original, typed_args.patch)
            return _maybe_write_diff_first(
                workspace=self.workspace,
                path=path,
                original=original,
                updated=updated,
                dry_run=typed_args.dry_run,
                require_approval=self.require_approval,
                confirm=self.confirm,
                max_output_chars=self.max_output_chars,
                tool_name=self.name,
            )
        except PatchApplyError as exc:
            return ToolResult.failure(str(exc), error_type="patch_conflict", retryable=True)
        except SafetyError as exc:
            return ToolResult.failure(str(exc), error_type="safety_error", retryable=False)
        except UnicodeDecodeError as exc:
            return ToolResult.failure(str(exc), error_type="decode_error", retryable=False)
        except OSError as exc:
            return ToolResult.failure(str(exc), error_type="io_error", retryable=True)


class PatchApplyError(Exception):
    """Raised when a unified diff cannot be applied cleanly."""


def _resolve_text_file(workspace: Path, raw_path: str) -> Path:
    path = resolve_workspace_path(workspace, raw_path)
    if not path.exists():
        raise OSError(f"File not found: {path}")
    if not path.is_file():
        raise OSError(f"Path is not a file: {path}")
    return path


def _maybe_write_diff_first(
    *,
    workspace: Path,
    path: Path,
    original: str,
    updated: str,
    dry_run: bool,
    require_approval: bool,
    confirm: ApprovalCallback | None,
    max_output_chars: int,
    tool_name: str,
) -> ToolResult:
    diff = _unified_diff(workspace, path, original, updated)
    rendered_diff = truncate_text(diff or "No changes.", max_output_chars)
    if original == updated:
        return ToolResult.success("No changes.\n" + rendered_diff)
    if dry_run:
        return ToolResult.success("Dry run only. No file was changed.\n" + rendered_diff)
    if require_approval:
        prompt = f"Apply diff to {path}?\n{rendered_diff}"
        if confirm is None or not confirm(prompt):
            return ToolResult.failure(
                "Edit rejected by user",
                error_type="user_rejected",
                retryable=False,
            )
    snapshot_path = _create_snapshot(workspace, path, original)
    checkpoint = CheckpointStore.create_file_checkpoint(
        workspace.resolve(),
        tool_name=tool_name,
        path=path,
        before=original,
        after=updated,
    )
    path.write_text(updated, encoding="utf-8")
    rel_snapshot = snapshot_path.relative_to(workspace.resolve()).as_posix()
    checkpoint_note = (
        f" Checkpoint saved as {checkpoint.checkpoint_id}."
        if checkpoint is not None
        else ""
    )
    message = (
        f"Applied edit to {path}. Snapshot saved at {rel_snapshot}."
        f"{checkpoint_note}\n{rendered_diff}"
    )
    return ToolResult.success(message)


def _unified_diff(workspace: Path, path: Path, original: str, updated: str) -> str:
    rel = path.resolve().relative_to(workspace.resolve()).as_posix()
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
    )


def _create_snapshot(workspace: Path, path: Path, original: str) -> Path:
    root = workspace.resolve()
    rel = path.resolve().relative_to(root)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    snapshot_path = root / ".asen" / "snapshots" / stamp / rel
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(original, encoding="utf-8")
    return snapshot_path


def _apply_unified_patch(original: str, patch: str) -> str:
    original_lines = original.splitlines(keepends=True)
    patch_lines = patch.splitlines(keepends=True)
    output: list[str] = []
    source_index = 0
    patch_index = 0
    saw_hunk = False

    while patch_index < len(patch_lines):
        line = patch_lines[patch_index]
        if line.startswith(("--- ", "+++ ")):
            patch_index += 1
            continue
        match = HUNK_HEADER.match(line)
        if match is None:
            patch_index += 1
            continue

        saw_hunk = True
        old_start = int(match.group(1))
        target_index = max(old_start - 1, 0)
        if target_index < source_index:
            raise PatchApplyError("Patch hunks overlap or are out of order")
        output.extend(original_lines[source_index:target_index])
        source_index = target_index
        patch_index += 1

        while patch_index < len(patch_lines):
            hunk_line = patch_lines[patch_index]
            if HUNK_HEADER.match(hunk_line):
                break
            if hunk_line.startswith(("--- ", "+++ ")):
                break
            if hunk_line.startswith("\\"):
                patch_index += 1
                continue
            if not hunk_line:
                patch_index += 1
                continue

            marker = hunk_line[0]
            content = hunk_line[1:]
            if marker == " ":
                _assert_source_line(original_lines, source_index, content)
                output.append(original_lines[source_index])
                source_index += 1
            elif marker == "-":
                _assert_source_line(original_lines, source_index, content)
                source_index += 1
            elif marker == "+":
                output.append(content)
            else:
                raise PatchApplyError(f"Unsupported patch line: {hunk_line.rstrip()}")
            patch_index += 1

    if not saw_hunk:
        raise PatchApplyError("Patch does not contain any unified diff hunks")
    output.extend(original_lines[source_index:])
    return "".join(output)


def _assert_source_line(source_lines: list[str], source_index: int, expected: str) -> None:
    if source_index >= len(source_lines):
        raise PatchApplyError("Patch hunk refers past end of file")
    actual = source_lines[source_index]
    if actual.rstrip("\n") != expected.rstrip("\n"):
        raise PatchApplyError(
            "Patch context mismatch: "
            f"expected {expected.rstrip()!r}, got {actual.rstrip()!r}"
        )
