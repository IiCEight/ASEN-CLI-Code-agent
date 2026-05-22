from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field


class McpTool(BaseModel):
    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class McpServerInfo(BaseModel):
    name: str = ""
    version: str = ""
    title: str | None = None


class McpInitializeResult(BaseModel):
    protocolVersion: str = ""
    capabilities: dict[str, Any] = Field(default_factory=dict)
    serverInfo: McpServerInfo = Field(default_factory=McpServerInfo)
    instructions: str | None = None


class McpToolCallResult(BaseModel):
    content: list[dict[str, Any]] = Field(default_factory=list)
    structuredContent: dict[str, Any] | list[Any] | str | None = None
    isError: bool = False

    def render_text(self) -> str:
        text_parts: list[str] = []
        for item in self.content:
            if item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    text_parts.append(text)
                    continue
            text_parts.append(json.dumps(item, ensure_ascii=False, indent=2))

        if text_parts:
            return "\n\n".join(text_parts)
        if self.structuredContent is not None:
            return json.dumps(self.structuredContent, ensure_ascii=False, indent=2)
        return "(no content)"
