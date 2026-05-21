from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ..config import AsenConfig
from ..utils.errors import LlmError
from .base import BaseLlmClient, messages_with_tool_instructions


class OllamaClient(BaseLlmClient):
    def __init__(
        self,
        config: AsenConfig,
        *,
        base_url: str = "http://localhost:11434",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.base_url = base_url
        self.client = client

    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        payload = self._payload(messages, tools, stream=False)
        try:
            if self.client is not None:
                response = await self.client.post(self._endpoint(), json=payload)
            else:
                async with httpx.AsyncClient(timeout=120) as client:
                    response = await client.post(self._endpoint(), json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlmError(f"Ollama request failed: {exc}") from exc

        data = response.json()
        try:
            content = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise LlmError("Ollama response does not match /api/chat format") from exc
        if not isinstance(content, str):
            raise LlmError("Ollama response content must be a string")
        return content

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        payload = self._payload(messages, tools, stream=True)
        try:
            if self.client is not None:
                async with self.client.stream("POST", self._endpoint(), json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        chunk = _extract_ollama_stream_delta(line)
                        if chunk:
                            yield chunk
                return

            async with (
                httpx.AsyncClient(timeout=120) as client,
                client.stream("POST", self._endpoint(), json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = _extract_ollama_stream_delta(line)
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise LlmError(f"Ollama streaming request failed: {exc}") from exc

    def _endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/api/chat"

    def _payload(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
        *,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "messages": messages_with_tool_instructions(messages, tools),
            "stream": stream,
            "options": {"temperature": 0.2},
        }


def _extract_ollama_stream_delta(raw: str) -> str:
    try:
        data = json.loads(raw)
        content = data.get("message", {}).get("content", "")
    except (json.JSONDecodeError, TypeError):
        return ""
    return content if isinstance(content, str) else ""
