from __future__ import annotations

import difflib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from ..utils.errors import AsenError, SafetyError
from ..utils.safety import resolve_workspace_path, truncate_text

CHECKPOINT_ROOT_DIRNAME = "checkpoints"
SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class CheckpointFileEntry(BaseModel):
    path: str
    change_type: str
    existed_before: bool
    before_snapshot: str | None = None
    after_snapshot: str
    diff_path: str
    bytes_before: int = 0
    bytes_after: int = 0


class CheckpointManifest(BaseModel):
    files: list[CheckpointFileEntry] = Field(default_factory=list)


class CheckpointMetadata(BaseModel):
    checkpoint_id: str
    title: str
    tool_name: str
    workspace: str
    created_at: str
    updated_at: str
    file_count: int = 0
    summary_preview: str = ""
    restore_count: int = 0
    last_restored_at: str | None = None


class CheckpointStore:
    def __init__(
        self,
        workspace: Path,
        root: Path,
        meta: CheckpointMetadata,
        manifest: CheckpointManifest,
    ) -> None:
        self.workspace = workspace
        self.root = root
        self.meta = meta
        self.manifest = manifest
        self.meta_path = self.root / "meta.json"
        self.manifest_path = self.root / "manifest.json"
        self.diff_path = self.root / "diff.patch"

    @property
    def checkpoint_id(self) -> str:
        return self.meta.checkpoint_id

    @classmethod
    def create_file_checkpoint(
        cls,
        workspace: Path,
        *,
        tool_name: str,
        path: Path,
        before: str | None,
        after: str,
    ) -> CheckpointStore | None:
        workspace_root = workspace.expanduser().resolve()
        target = resolve_workspace_path(workspace_root, path)
        if before == after:
            return None

        root_dir = checkpoint_root(workspace_root)
        root_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_id = _next_checkpoint_id(root_dir, tool_name)
        checkpoint_dir = root_dir / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=False)

        rel = target.relative_to(workspace_root).as_posix()
        before_snapshot_rel: str | None = None
        if before is not None:
            before_path = checkpoint_dir / "before" / rel
            before_path.parent.mkdir(parents=True, exist_ok=True)
            before_path.write_text(before, encoding="utf-8")
            before_snapshot_rel = before_path.relative_to(checkpoint_dir).as_posix()

        after_path = checkpoint_dir / "after" / rel
        after_path.parent.mkdir(parents=True, exist_ok=True)
        after_path.write_text(after, encoding="utf-8")
        after_snapshot_rel = after_path.relative_to(checkpoint_dir).as_posix()

        diff_text = render_diff(rel, before, after)
        diff_path = checkpoint_dir / "diff.patch"
        diff_path.write_text(diff_text, encoding="utf-8")

        now = _utcnow()
        change_type = "created" if before is None else "modified"
        entry = CheckpointFileEntry(
            path=rel,
            change_type=change_type,
            existed_before=before is not None,
            before_snapshot=before_snapshot_rel,
            after_snapshot=after_snapshot_rel,
            diff_path=diff_path.relative_to(checkpoint_dir).as_posix(),
            bytes_before=len(before.encode("utf-8")) if before is not None else 0,
            bytes_after=len(after.encode("utf-8")),
        )
        manifest = CheckpointManifest(files=[entry])
        summary = truncate_text(
            _single_line(f"{change_type} {rel} via {tool_name}"),
            120,
        )
        meta = CheckpointMetadata(
            checkpoint_id=checkpoint_id,
            title=f"{tool_name} · {Path(rel).name}",
            tool_name=tool_name,
            workspace=str(workspace_root),
            created_at=now,
            updated_at=now,
            file_count=1,
            summary_preview=summary,
        )
        store = cls(workspace_root, checkpoint_dir, meta, manifest)
        store._write_meta()
        store._write_manifest()
        return store

    @classmethod
    def open(cls, workspace: Path, checkpoint_id: str) -> CheckpointStore:
        workspace_root = workspace.expanduser().resolve()
        checkpoint_dir = resolve_checkpoint_dir(workspace_root, checkpoint_id)
        if checkpoint_dir is None:
            raise AsenError(f"Checkpoint not found: {checkpoint_id}")
        meta_path = checkpoint_dir / "meta.json"
        manifest_path = checkpoint_dir / "manifest.json"
        if not meta_path.exists():
            raise AsenError(f"Checkpoint metadata missing: {meta_path}")
        if not manifest_path.exists():
            raise AsenError(f"Checkpoint manifest missing: {manifest_path}")
        meta = CheckpointMetadata.model_validate_json(meta_path.read_text(encoding="utf-8"))
        manifest = CheckpointManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        return cls(workspace_root, checkpoint_dir, meta, manifest)

    @staticmethod
    def list(workspace: Path) -> list[CheckpointMetadata]:
        root = checkpoint_root(workspace)
        if not root.exists():
            return []
        items: list[CheckpointMetadata] = []
        for meta_path in root.glob("*/meta.json"):
            try:
                items.append(
                    CheckpointMetadata.model_validate_json(
                        meta_path.read_text(encoding="utf-8")
                    )
                )
            except Exception:
                continue
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def render_diff(self, *, max_chars: int | None = None) -> str:
        if not self.diff_path.exists():
            return "No diff captured for this checkpoint."
        diff_text = self.diff_path.read_text(encoding="utf-8")
        if max_chars is None:
            return diff_text
        return truncate_text(diff_text, max_chars)

    def metadata_payload(self) -> dict[str, object]:
        return {
            **self.meta.model_dump(mode="json"),
            "checkpoint_root": str(self.root),
            "diff_file_path": str(self.diff_path),
        }

    def changed_files_payload(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for entry in self.manifest.files:
            items.append(
                {
                    **entry.model_dump(mode="json"),
                    "checkpoint_id": self.meta.checkpoint_id,
                    "tool_name": self.meta.tool_name,
                    "checkpoint_root": str(self.root),
                    "before_snapshot_path": (
                        str(self.root / entry.before_snapshot)
                        if entry.before_snapshot
                        else None
                    ),
                    "after_snapshot_path": str(self.root / entry.after_snapshot),
                    "diff_file_path": str(self.root / entry.diff_path),
                }
            )
        return items

    def restore(self) -> list[str]:
        actions: list[str] = []
        for entry in self.manifest.files:
            target = resolve_workspace_path(self.workspace, entry.path)
            if entry.existed_before:
                if not entry.before_snapshot:
                    raise AsenError(
                        f"Checkpoint is missing the original snapshot for {entry.path}"
                    )
                source = self.root / entry.before_snapshot
                if not source.exists():
                    raise AsenError(f"Original snapshot missing: {source}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                actions.append(f"Restored {entry.path}")
                continue

            if target.exists():
                if not target.is_file():
                    raise SafetyError(f"Cannot remove non-file path during restore: {target}")
                target.unlink()
                actions.append(f"Removed {entry.path}")
            else:
                actions.append(f"Already absent: {entry.path}")

        self.meta.restore_count += 1
        self.meta.last_restored_at = _utcnow()
        self.meta.updated_at = self.meta.last_restored_at
        self._write_meta()
        return actions

    def _write_meta(self) -> None:
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)
        self.meta_path.write_text(
            json.dumps(self.meta.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_manifest(self) -> None:
        self.manifest_path.write_text(
            json.dumps(self.manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def checkpoint_root(workspace: Path) -> Path:
    return workspace.expanduser().resolve() / ".asen" / CHECKPOINT_ROOT_DIRNAME


def resolve_checkpoint_dir(workspace: Path, checkpoint_id: str) -> Path | None:
    root = checkpoint_root(workspace)
    if not root.exists():
        return None
    exact = root / checkpoint_id
    if exact.exists():
        return exact
    matches = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith(checkpoint_id)
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        match_names = ", ".join(path.name for path in matches)
        raise AsenError(
            f"Checkpoint id '{checkpoint_id}' is ambiguous. Matches: {match_names}"
        )
    return None


def render_diff(rel_path: str, before: str | None, after: str) -> str:
    original = before or ""
    fromfile = f"a/{rel_path}" if before is not None else "/dev/null"
    return "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=fromfile,
            tofile=f"b/{rel_path}",
        )
    )


def _next_checkpoint_id(root: Path, tool_name: str) -> str:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    slug = _slugify(tool_name) or "checkpoint"
    base = f"{stamp}-{slug}"
    candidate = base
    index = 2
    while (root / candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _slugify(text: str) -> str:
    lowered = text.strip().lower()
    normalized = SLUG_PATTERN.sub("-", lowered).strip("-")
    return normalized[:32]


def _single_line(text: str) -> str:
    return " ".join(text.split())


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()
