from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from .utils.errors import ConfigError


class AsenConfig(BaseModel):
    api_key: str | None = None
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    workspace: Path = Field(default_factory=Path.cwd)
    max_steps: int = 8
    max_context_messages: int = 24
    max_context_tokens: int = 16_000
    reserve_output_tokens: int = 2_000
    command_timeout_seconds: int = 20
    max_file_bytes: int = 120_000
    max_tool_output_chars: int = 12_000
    require_approval: bool = True

    @field_validator("workspace", mode="before")
    @classmethod
    def parse_workspace(cls, value: Any) -> Path:
        return Path(value).expanduser().resolve()


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


ENV_MAPPING: dict[str, tuple[str, Any]] = {
    "ASEN_API_KEY": ("api_key", str),
    "ASEN_BASE_URL": ("base_url", str),
    "ASEN_MODEL": ("model", str),
    "ASEN_WORKSPACE": ("workspace", Path),
    "ASEN_MAX_STEPS": ("max_steps", int),
    "ASEN_MAX_CONTEXT_MESSAGES": ("max_context_messages", int),
    "ASEN_MAX_CONTEXT_TOKENS": ("max_context_tokens", int),
    "ASEN_RESERVE_OUTPUT_TOKENS": ("reserve_output_tokens", int),
    "ASEN_COMMAND_TIMEOUT_SECONDS": ("command_timeout_seconds", int),
    "ASEN_MAX_FILE_BYTES": ("max_file_bytes", int),
    "ASEN_MAX_TOOL_OUTPUT_CHARS": ("max_tool_output_chars", int),
    "ASEN_REQUIRE_APPROVAL": ("require_approval", _env_bool),
}


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ConfigError("Config file must contain a YAML object")
    return loaded


def _coerce_env_values(raw_values: dict[str, str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for env_name, (field_name, converter) in ENV_MAPPING.items():
        raw = raw_values.get(env_name)
        if raw is not None and raw != "":
            values[field_name] = converter(raw)
    return values


def _env_overrides() -> dict[str, Any]:
    return _coerce_env_values(dict(os.environ))


def _dotenv_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}

    raw_values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        raw_values[key.strip()] = value
    return _coerce_env_values(raw_values)


def load_config(
    config_path: Path | str | None = None,
    *,
    workspace: Path | str | None = None,
    overrides: dict[str, Any] | None = None,
) -> AsenConfig:
    data: dict[str, Any] = _dotenv_overrides(Path.cwd() / ".env")
    if config_path:
        data.update(_read_yaml(Path(config_path).expanduser().resolve()))
    data.update(_env_overrides())
    if workspace is not None:
        data["workspace"] = Path(workspace)
    if overrides:
        data.update({key: value for key, value in overrides.items() if value is not None})
    return AsenConfig(**data)
