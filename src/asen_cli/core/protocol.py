from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PlanStatus = Literal["pending", "in_progress", "completed", "failed"]


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None

    def to_openai(self) -> dict[str, str]:
        if self.role == "tool":
            tool_name = self.name or "unknown"
            return {"role": "user", "content": f"Tool result from {tool_name}:\n{self.content}"}

        return {"role": self.role, "content": self.content}


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class PlanStep(BaseModel):
    id: str
    content: str
    status: PlanStatus = "pending"


class AgentResponse(BaseModel):
    final_text: str | None = None
    plan_steps: list[PlanStep] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    invalid_reason: str | None = None
