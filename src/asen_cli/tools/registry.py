from __future__ import annotations

import time
from typing import Any

from .base import BaseTool, ToolExecutionLog, ToolResult


class ToolRegistry:
    def __init__(self, tools: list[BaseTool] | None = None) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._logs: list[ToolExecutionLog] = []
        for tool in tools or []:
            self.register(tool)

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def logs(self) -> list[ToolExecutionLog]:
        return list(self._logs)

    async def execute(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        started_at = time.perf_counter()
        tool = self._tools.get(name)
        if tool is None:
            result = ToolResult.failure(
                f"Unknown tool: {name}",
                error_type="unknown_tool",
                retryable=True,
            )
        else:
            result = await tool.execute(arguments)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        self._logs.append(
            ToolExecutionLog(
                name=name,
                arguments=arguments,
                ok=result.ok,
                error=result.error,
                error_type=result.error_type,
                retryable=result.retryable,
                elapsed_ms=elapsed_ms,
                meta=result.meta,
            )
        )
        return result
