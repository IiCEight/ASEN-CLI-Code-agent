from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any, Protocol


class LlmClient(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> str: ...

    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str]: ...


class BaseLlmClient:
    async def stream_complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        yield await self.complete(messages, tools)  # type: ignore[attr-defined]


def messages_with_tool_instructions(
    messages: list[dict[str, str]], tools: list[dict[str, Any]]
) -> list[dict[str, str]]:
    if not tools:
        return [dict(message) for message in messages]

    tool_instructions = render_tool_instructions(tools)
    updated = [dict(message) for message in messages]
    if updated and updated[0].get("role") == "system":
        updated[0]["content"] = f"{updated[0].get('content', '')}\n\n{tool_instructions}"
    else:
        updated.insert(0, {"role": "system", "content": tool_instructions})
    return updated


def render_tool_instructions(tools: list[dict[str, Any]]) -> str:
    tool_json = json.dumps(tools, ensure_ascii=False, indent=2)
    return (
        "Available tools are listed below as JSON schemas. These are not native API tools; "
        "you must request them by returning exactly the asen JSON protocol.\n"
        f"{tool_json}\n\n"
        "If the user asks you to create, write, edit, read, list, fetch, or run anything, "
        "call the matching tool. Do not answer with only instructions or a code block for "
        "actions that should be performed in the workspace."
    )
