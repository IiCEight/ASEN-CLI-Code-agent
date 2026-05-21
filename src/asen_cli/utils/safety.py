from __future__ import annotations

import re
from dataclasses import dataclass
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

HIGH_RISK_COMMAND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bcurl\b.*\|\s*(sh|bash|zsh)\b"),
        "downloads and executes a remote script",
    ),
    (
        re.compile(
            r"\bgit\s+(commit\b|push\b|reset\b|clean\b|checkout\b|switch\b|"
            r"restore\b|rebase\b|merge\b|cherry-pick\b|revert\b)"
        ),
        "changes git history, branch state, or remote state",
    ),
    (
        re.compile(
            r"\b(npm|pnpm|yarn|pip|pip3|poetry|uv|brew|apt|apt-get)\s+"
            r"(install|add|remove|uninstall|upgrade|update)\b"
        ),
        "installs, updates, or removes dependencies",
    ),
    (
        re.compile(r"\b(kubectl|docker|docker-compose|terraform|scp|rsync|ssh)\b"),
        "affects remote or container environments",
    ),
    (re.compile(r"\bsed\s+-i\b"), "edits files in place"),
    (re.compile(r"\b(chmod|chown|mv|cp|rm)\b"), "changes or deletes files in the workspace"),
    (re.compile(r"\s>>?\s*\S+"), "writes command output into a file"),
    (re.compile(r"\btee\b\s+\S+"), "writes command output into a file"),
]


@dataclass(frozen=True, slots=True)
class CommandSafetyCheck:
    level: str
    reason: str | None = None


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


def normalize_command(command: str) -> str:
    return " ".join(command.strip().split()).lower()


def is_dangerous_command(command: str) -> bool:
    normalized = normalize_command(command)
    return any(pattern.search(normalized) for pattern in DANGEROUS_COMMAND_PATTERNS)


def assess_command_safety(command: str) -> CommandSafetyCheck:
    normalized = normalize_command(command)
    if any(pattern.search(normalized) for pattern in DANGEROUS_COMMAND_PATTERNS):
        return CommandSafetyCheck(
            level="blocked",
            reason="matches a destructive command guard",
        )
    for pattern, reason in HIGH_RISK_COMMAND_PATTERNS:
        if pattern.search(normalized):
            return CommandSafetyCheck(level="confirm", reason=reason)
    return CommandSafetyCheck(level="safe")
