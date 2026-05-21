from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import AsenConfig
from ..utils.errors import ConfigError, LlmError
from .base import BaseLlmClient, messages_with_tool_instructions


class OpenAICompatibleClient(BaseLlmClient):
    def __init__(
        self,
        config: AsenConfig,
        *,
        base_url: str | None = None,
        provider_name: str = "openai",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.base_url = base_url or config.base_url
        self.provider_name = provider_name
        self.client = client

    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        response = await self._post_chat_completion(messages, tools, stream=False)
        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError(
                f"{self.provider_name} response does not match OpenAI chat format"
            ) from exc
        if not isinstance(content, str):
            raise LlmError(f"{self.provider_name} response content must be a string")
        return content

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, tools, stream=True)
        headers = self._headers()
        endpoint = self._endpoint()
        try:
            async with (
                httpx.AsyncClient(timeout=60) as client,
                client.stream(
                    "POST",
                    endpoint,
                    json=payload,
                    headers=headers,
                ) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    raw = line.removeprefix("data: ").strip()
                    if raw == "[DONE]":
                        break
                    chunk = _extract_openai_stream_delta(raw)
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise LlmError(f"{self.provider_name} streaming request failed: {exc}") from exc

    async def _post_chat_completion(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        stream: bool,
    ) -> httpx.Response:
        payload = self._payload(messages, tools, stream=stream)
        headers = self._headers()
        endpoint = self._endpoint()
        try:
            if self.client is not None:
                response = await self.client.post(endpoint, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=60) as client:
                    response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlmError(f"{self.provider_name} request failed: {exc}") from exc
        return response

    def _endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    def _headers(self) -> dict[str, str]:
        if not self.config.api_key:
            raise ConfigError(
                f"Missing API key for {self.provider_name}. "
                "Set ASEN_API_KEY or configure api_key in YAML."
            )
        return {"Authorization": f"Bearer {self.config.api_key}"}

    def _payload(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages_with_tool_instructions(messages, tools),
            "temperature": 0.2,
        }
        if stream:
            payload["stream"] = True
        return payload


def _extract_openai_stream_delta(raw: str) -> str:
    try:
        data = json.loads(raw)
        content = data["choices"][0].get("delta", {}).get("content", "")
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        return ""
    return content if isinstance(content, str) else ""
