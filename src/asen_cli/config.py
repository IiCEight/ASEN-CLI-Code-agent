from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from .utils.errors import ConfigError

SENSITIVE_CONFIG_KEYS = {"api_key", "token", "secret", "password", "authorization"}


class McpServerConfig(BaseModel):
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: Path | None = None
    timeout_seconds: int = 20
    enabled: bool = True
    description: str | None = None

    @field_validator("cwd", mode="before")
    @classmethod
    def parse_cwd(cls, value: Any) -> Path | None:
        if value in (None, ""):
            return None
        return Path(value).expanduser().resolve()


class AsenConfig(BaseModel):
    provider: str = "openai"
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
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)

    @field_validator("workspace", mode="before")
    @classmethod
    def parse_workspace(cls, value: Any) -> Path:
        return Path(value).expanduser().resolve()


def config_fields() -> list[str]:
    return sorted(AsenConfig.model_fields)


def default_config_template() -> dict[str, Any]:
    return {
        "provider": "openai",
        "api_key": "sk-your-api-key",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "workspace": ".",
        "max_steps": 8,
        "max_context_messages": 24,
        "max_context_tokens": 16_000,
        "reserve_output_tokens": 2_000,
        "command_timeout_seconds": 20,
        "max_file_bytes": 120_000,
        "max_tool_output_chars": 12_000,
        "require_approval": True,
        "mcp_servers": {},
    }


def _env_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


ENV_MAPPING: dict[str, tuple[str, Any]] = {
    "ASEN_PROVIDER": ("provider", str),
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


def get_config_path(scope: str = "project") -> Path:
    if scope == "global":
        return Path.home() / ".asen" / "config.yaml"
    if scope == "project":
        return Path.cwd() / ".asen" / "config.yaml"
    raise ConfigError(f"Unknown config scope: {scope}")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    return _read_yaml_if_exists(path)


def _read_yaml_if_exists(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ConfigError("Config file must contain a YAML object")
    return loaded


def _write_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


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
    data: dict[str, Any] = {}
    data.update(_dotenv_overrides(Path.cwd() / ".env"))
    data.update(_env_overrides())
    data.update(_read_yaml_if_exists(get_config_path("global")))
    data.update(_read_yaml_if_exists(get_config_path("project")))
    if config_path:
        data.update(_read_yaml(Path(config_path).expanduser().resolve()))
    if workspace is not None:
        data["workspace"] = Path(workspace)
    if overrides:
        data.update({key: value for key, value in overrides.items() if value is not None})
    return AsenConfig(**data)


def read_config_file(path: Path) -> dict[str, Any]:
    return _read_yaml_if_exists(path.expanduser().resolve())


def init_config_file(path: Path, *, force: bool = False) -> Path:
    target = path.expanduser().resolve()
    if target.exists() and not force:
        raise ConfigError(f"Config file already exists: {target}")
    _write_yaml(target, default_config_template())
    return target


def set_config_value(path: Path, key: str, raw_value: str) -> Path:
    if key not in AsenConfig.model_fields:
        raise ConfigError(f"Unknown config key: {key}. Available: {', '.join(config_fields())}")
    target = path.expanduser().resolve()
    data = _read_yaml_if_exists(target)
    data[key] = _coerce_config_value(key, raw_value)
    _write_yaml(target, data)
    return target


def set_mcp_server_config(path: Path, name: str, server: McpServerConfig) -> Path:
    target = path.expanduser().resolve()
    data = _read_yaml_if_exists(target)
    mcp_servers = data.setdefault("mcp_servers", {})
    if not isinstance(mcp_servers, dict):
        raise ConfigError("Config key `mcp_servers` must be a YAML object")
    mcp_servers[name] = server.model_dump(mode="json", exclude_none=True)
    _write_yaml(target, data)
    return target


def get_config_value(config: AsenConfig, key: str) -> Any:
    if key not in AsenConfig.model_fields:
        raise ConfigError(f"Unknown config key: {key}. Available: {', '.join(config_fields())}")
    return getattr(config, key)


def mask_config(data: dict[str, Any]) -> dict[str, Any]:
    return _mask_value(data)


def _mask_value(value: Any) -> Any:
    if isinstance(value, dict):
        masked: dict[str, Any] = {}
        for key, item in value.items():
            if _is_sensitive_key(key) and item not in (None, ""):
                masked[key] = "***"
            else:
                masked[key] = _mask_value(item)
        return masked
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in SENSITIVE_CONFIG_KEYS)


def _coerce_config_value(key: str, raw_value: str) -> Any:
    value = raw_value.strip()
    if key == "mcp_servers":
        loaded = yaml.safe_load(value) or {}
        if not isinstance(loaded, dict):
            raise ConfigError("mcp_servers must be a YAML/JSON object")
        return loaded

    field = AsenConfig.model_fields[key]
    annotation = field.annotation
    if annotation is bool:
        return _env_bool(value)
    if annotation is int:
        return int(value)
    if annotation is Path:
        return value
    if key == "api_key" and value.lower() in {"none", "null", ""}:
        return None
    return value
