from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {
    "name": "asen-filesystem-demo",
    "title": "ASEN Filesystem Demo",
    "version": "0.1.0",
}
TOOLS = [
    {
        "name": "list_directory",
        "description": (
            "List files and directories under a relative path "
            "inside the allowed workspace root."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative directory path. Defaults to .",
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file inside the allowed workspace root.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative file path inside the workspace root.",
                },
                "max_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional byte limit. Defaults to 20000.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "stat_path",
        "description": (
            "Return basic metadata for a file or directory "
            "under the allowed workspace root."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path inside the workspace root.",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
]


def main() -> None:
    root = Path.cwd().resolve()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        _handle_message(root, message)


def _handle_message(root: Path, message: dict[str, Any]) -> None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        _respond(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                    }
                },
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "This demo server only exposes safe filesystem read tools "
                    "under its working directory."
                ),
            },
        )
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        _respond(request_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        tool_name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        try:
            result = _call_tool(root, tool_name, arguments)
            _respond(request_id, result)
        except Exception as exc:
            _respond(
                request_id,
                {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            )
        return

    if request_id is not None:
        _error(request_id, -32601, f"Unsupported MCP method: {method}")


def _call_tool(root: Path, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if tool_name == "list_directory":
        target = _safe_path(root, str(arguments.get("path", ".")))
        if not target.is_dir():
            raise ValueError(f"Not a directory: {target.relative_to(root)}")
        entries = [
            {
                "name": child.name,
                "path": child.relative_to(root).as_posix(),
                "is_dir": child.is_dir(),
            }
            for child in sorted(target.iterdir(), key=lambda item: item.name)
        ]
        return _tool_result(entries)

    if tool_name == "read_file":
        target = _safe_path(root, str(arguments.get("path", "")))
        if not target.is_file():
            raise ValueError(f"Not a file: {target.relative_to(root)}")
        max_bytes = int(arguments.get("max_bytes", 20_000))
        content = target.read_text(encoding="utf-8")
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            content = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return {
            "content": [
                {
                    "type": "text",
                    "text": content,
                }
            ],
            "structuredContent": {
                "path": target.relative_to(root).as_posix(),
                "bytes": min(len(encoded), max_bytes),
            },
            "isError": False,
        }

    if tool_name == "stat_path":
        target = _safe_path(root, str(arguments.get("path", "")))
        if not target.exists():
            raise ValueError(f"Path does not exist: {arguments.get('path', '')}")
        info = {
            "path": target.relative_to(root).as_posix(),
            "is_dir": target.is_dir(),
            "size": target.stat().st_size,
        }
        return _tool_result(info)

    raise ValueError(f"Unknown tool: {tool_name}")


def _tool_result(data: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, indent=2),
            }
        ],
        "structuredContent": data,
        "isError": False,
    }


def _safe_path(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Path escapes allowed root: {relative_path}") from exc
    return candidate


def _respond(request_id: int | str | None, result: dict[str, Any]) -> None:
    message = {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(request_id: int | str | None, code: int, message: str) -> None:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
