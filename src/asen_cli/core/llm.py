from __future__ import annotations

import json
from typing import Any

import httpx

from ..config import AsenConfig
from ..utils.errors import ConfigError, LlmError


class OpenAICompatibleClient:
    def __init__(self, config: AsenConfig) -> None:
        self.config = config

    async def complete(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> str:
        if not self.config.api_key:
            raise ConfigError("Missing API key. Set ASEN_API_KEY or configure api_key in YAML.")

        endpoint = f"{self.config.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": _messages_with_tool_instructions(messages, tools),
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {self.config.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LlmError(f"LLM request failed: {exc}") from exc

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LlmError("LLM response does not match OpenAI chat completions format") from exc
        if not isinstance(content, str):
            raise LlmError("LLM response content must be a string")
        return content


def _messages_with_tool_instructions(
    messages: list[dict[str, str]], tools: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not tools:
        return [dict(message) for message in messages]

    tool_instructions = _render_tool_instructions(tools)
    updated = [dict(message) for message in messages]
    if updated and updated[0].get("role") == "system":
        updated[0]["content"] = f"{updated[0].get('content', '')}\n\n{tool_instructions}"
    else:
        updated.insert(0, {"role": "system", "content": tool_instructions})
    return updated


def _render_tool_instructions(tools: list[dict[str, Any]]) -> str:
    tool_json = json.dumps(tools, ensure_ascii=False, indent=2)
    return (
        "Available tools are listed below as JSON schemas. These are not native API tools; "
        "you must request them by returning exactly the asen JSON protocol.\n"
        f"{tool_json}\n\n"
        "If the user asks you to create, write, edit, read, list, fetch, or run anything, "
        "call the matching tool. Do not answer with only instructions or a code block for "
        "actions that should be performed in the workspace."
    )
