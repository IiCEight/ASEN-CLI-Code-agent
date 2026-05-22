from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from pathlib import Path
from typing import Any

from asen_cli import __version__

from ..config import McpServerConfig
from ..utils.errors import McpError
from .protocol import McpInitializeResult, McpTool, McpToolCallResult

PROTOCOL_VERSION = "2025-06-18"


class StdioMcpClient:
    def __init__(
        self,
        server_name: str,
        server_config: McpServerConfig,
        *,
        workspace: Path,
    ) -> None:
        self.server_name = server_name
        self.server_config = server_config
        self.workspace = workspace.resolve()
        self.process: asyncio.subprocess.Process | None = None
        self._stderr_tail: deque[str] = deque(maxlen=50)
        self._stderr_task: asyncio.Task[None] | None = None
        self._request_id = 0
        self.initialize_result: McpInitializeResult | None = None

    async def __aenter__(self) -> StdioMcpClient:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        if not self.server_config.enabled:
            raise McpError(f"MCP server `{self.server_name}` is disabled")

        cwd = (self.server_config.cwd or self.workspace).resolve()
        env = os.environ.copy()
        env.update(self.server_config.env)

        try:
            self.process = await asyncio.create_subprocess_exec(
                self.server_config.command,
                *self.server_config.args,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise McpError(
                f"Failed to start MCP server `{self.server_name}`: {self.server_config.command}"
            ) from exc

        self._stderr_task = asyncio.create_task(self._capture_stderr())
        self.initialize_result = await self.initialize()

    async def close(self) -> None:
        if self.process is None:
            return

        if self.process.stdin is not None and not self.process.stdin.is_closing():
            self.process.stdin.close()

        try:
            await asyncio.wait_for(self.process.wait(), timeout=0.5)
        except TimeoutError:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

        if self._stderr_task is not None:
            await self._stderr_task

    async def initialize(self) -> McpInitializeResult:
        response = await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "asen-cli",
                    "title": "asen cli",
                    "version": __version__,
                },
            },
        )
        result = McpInitializeResult.model_validate(response)
        if result.protocolVersion != PROTOCOL_VERSION:
            raise McpError(
                "Unsupported MCP protocol version from "
                f"`{self.server_name}`: {result.protocolVersion}"
            )
        await self._notify("notifications/initialized", {})
        return result

    async def list_tools(self) -> list[McpTool]:
        result = await self._request("tools/list", {})
        return [McpTool.model_validate(item) for item in result.get("tools", [])]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> McpToolCallResult:
        result = await self._request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )
        return McpToolCallResult.model_validate(result)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._request_id += 1
        request_id = self._request_id
        await self._send_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )

        while True:
            message = await self._read_message()
            if "id" not in message:
                continue
            if message["id"] != request_id:
                continue
            if "error" in message:
                error = message["error"]
                raise McpError(
                    f"MCP `{self.server_name}` {method} failed: "
                    f"{error.get('message', 'unknown error')}"
                )
            result = message.get("result")
            if not isinstance(result, dict):
                raise McpError(
                    f"MCP `{self.server_name}` returned invalid result for {method}: {result!r}"
                )
            return result

    async def _send_message(self, payload: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise McpError(f"MCP server `{self.server_name}` is not running")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        self.process.stdin.write(line.encode("utf-8"))
        await self.process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        if self.process is None or self.process.stdout is None:
            raise McpError(f"MCP server `{self.server_name}` is not running")

        try:
            raw = await asyncio.wait_for(
                self.process.stdout.readline(),
                timeout=self.server_config.timeout_seconds,
            )
        except TimeoutError as exc:
            raise McpError(
                f"Timed out waiting for MCP server `{self.server_name}` response"
            ) from exc

        if not raw:
            raise McpError(
                f"MCP server `{self.server_name}` closed stdout unexpectedly."
                f" stderr={self.stderr_tail()}"
            )

        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            return await self._read_message()
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise McpError(
                f"MCP server `{self.server_name}` returned invalid JSON: {line}"
            ) from exc
        if not isinstance(message, dict):
            raise McpError(
                f"MCP server `{self.server_name}` returned non-object message: {message!r}"
            )
        return message

    async def _capture_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        while True:
            raw = await self.process.stderr.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip()
            if line:
                self._stderr_tail.append(line)

    def stderr_tail(self) -> str:
        return " | ".join(self._stderr_tail)
