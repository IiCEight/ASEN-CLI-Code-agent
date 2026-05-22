from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

ApprovalCallback = Callable[[str], bool]


class ToolResult(BaseModel):
    ok: bool
    content: str = ""
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False
    meta: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def success(cls, content: str, *, meta: dict[str, Any] | None = None) -> ToolResult:
        return cls(ok=True, content=content, meta=meta or {})

    @classmethod
    def failure(
        cls,
        error: str,
        *,
        error_type: str = "tool_error",
        retryable: bool = False,
        meta: dict[str, Any] | None = None,
    ) -> ToolResult:
        return cls(
            ok=False,
            content="",
            error=error,
            error_type=error_type,
            retryable=retryable,
            meta=meta or {},
        )

    def render(self) -> str:
        if self.ok:
            return self.content
        prefix = f"ERROR[{self.error_type}]" if self.error_type else "ERROR"
        retry_hint = " retryable=true" if self.retryable else " retryable=false"
        return f"{prefix}{retry_hint}: {self.error}"

    def to_payload(self, *, rendered: str | None = None) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "content": self.content,
            "rendered": rendered if rendered is not None else self.render(),
            "error": self.error,
            "error_type": self.error_type,
            "retryable": self.retryable,
            "meta": self.meta,
        }


class ToolExecutionLog(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    ok: bool
    error: str | None = None
    error_type: str | None = None
    retryable: bool = False
    elapsed_ms: int
    meta: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    name: str
    description: str
    args_model: type[BaseModel]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.args_model.model_json_schema(),
        }

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            args = self.args_model.model_validate(arguments)
        except ValidationError as exc:
            return ToolResult.failure(
                f"Invalid arguments for {self.name}: {exc}",
                error_type="validation_error",
                retryable=True,
            )
        return await self._run(args)

    @abstractmethod
    async def _run(self, args: BaseModel) -> ToolResult:
        raise NotImplementedError
