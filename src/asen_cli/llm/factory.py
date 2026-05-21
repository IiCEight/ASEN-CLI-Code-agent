from __future__ import annotations

from ..config import AsenConfig
from ..utils.errors import ConfigError
from .base import LlmClient
from .ollama_client import OllamaClient
from .openai_client import OpenAICompatibleClient

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
PROVIDER_BASE_URLS = {
    "openai": DEFAULT_OPENAI_BASE_URL,
    "openai-compatible": DEFAULT_OPENAI_BASE_URL,
    "deepseek": "https://api.deepseek.com",
    "kimi": "https://api.moonshot.cn/v1",
    "tongyi": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "ollama": "http://localhost:11434",
}
OPENAI_COMPATIBLE_PROVIDERS = {"openai", "openai-compatible", "deepseek", "kimi", "tongyi", "zhipu"}


def create_llm_client(config: AsenConfig) -> LlmClient:
    provider = normalize_provider(config.provider)
    base_url = resolve_provider_base_url(config, provider)
    if provider == "ollama":
        return OllamaClient(config, base_url=base_url)
    if provider in OPENAI_COMPATIBLE_PROVIDERS:
        return OpenAICompatibleClient(config, base_url=base_url, provider_name=provider)
    raise ConfigError(
        f"Unknown LLM provider: {config.provider}. "
        f"Available: {', '.join(sorted(PROVIDER_BASE_URLS))}"
    )


def normalize_provider(provider: str) -> str:
    return provider.strip().lower().replace("_", "-")


def resolve_provider_base_url(config: AsenConfig, provider: str | None = None) -> str:
    normalized = normalize_provider(provider or config.provider)
    configured = config.base_url.rstrip("/")
    default = DEFAULT_OPENAI_BASE_URL.rstrip("/")
    if configured and configured != default:
        return configured
    if normalized in PROVIDER_BASE_URLS:
        return PROVIDER_BASE_URLS[normalized]
    return configured
