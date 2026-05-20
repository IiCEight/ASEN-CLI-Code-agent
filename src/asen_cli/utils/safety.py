from __future__ import annotations

import re
from pathlib import Path

from .errors import SafetyError

DANGEROUS_COMMAND_PATTERNS = [
    re.compile(r"\brm\s+(-[A-Za-z]*[rf][A-Za-z]*|-[A-Za-z]*[fr][A-Za-z]*)\s+(/|~|\$HOME)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs(\.|\s|$)"),
    re.compile(r"\bdd\s+.*\bof=/dev/"),
    re.compile(r"\b(shutdown|reboot|halt)\b"),
    re.compile(r":\s*\(\)\s*\{\s*:\s*\|\s*:\s*&\s*}\s*;\s*:"),
]


def normalize_workspace(workspace: Path | str) -> Path:
    return Path(workspace).expanduser().resolve()


def resolve_workspace_path(workspace: Path | str, user_path: Path | str) -> Path:
    root = normalize_workspace(workspace)
    raw_path = Path(user_path).expanduser()
    candidate = raw_path.resolve() if raw_path.is_absolute() else (root / raw_path).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SafetyError(f"Path is outside workspace: {candidate}") from exc
    return candidate


def truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n...[truncated {omitted} chars]"


def is_dangerous_command(command: str) -> bool:
    normalized = " ".join(command.strip().split()).lower()
    return any(pattern.search(normalized) for pattern in DANGEROUS_COMMAND_PATTERNS)
