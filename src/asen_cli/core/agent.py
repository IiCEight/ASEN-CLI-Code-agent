from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from ..config import AsenConfig
from ..tools.registry import ToolRegistry
from ..utils.safety import truncate_text
from .context import ConversationContext
from .protocol import AgentResponse, PlanStep, ToolCall


class LlmLike(Protocol):
    async def complete(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> str: ...


@dataclass(slots=True)
class AgentEvents:
    on_thinking: Callable[[int], None] | None = None
    on_llm_response: Callable[[str], None] | None = None
    on_plan: Callable[[list[PlanStep]], None] | None = None
    on_plan_step: Callable[[PlanStep], None] | None = None
    on_tool_call: Callable[[str, dict[str, Any]], None] | None = None
    on_tool_result: Callable[[str, str], None] | None = None

    def thinking(self, step: int) -> None:
        if self.on_thinking:
            self.on_thinking(step)

    def llm_response(self, raw_response: str) -> None:
        if self.on_llm_response:
            self.on_llm_response(raw_response)

    def plan(self, steps: list[PlanStep]) -> None:
        if self.on_plan:
            self.on_plan(steps)

    def plan_step(self, step: PlanStep) -> None:
        if self.on_plan_step:
            self.on_plan_step(step)

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        if self.on_tool_call:
            self.on_tool_call(name, arguments)

    def tool_result(self, name: str, rendered: str) -> None:
        if self.on_tool_result:
            self.on_tool_result(name, rendered)


JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class Agent:
    def __init__(
        self,
        *,
        config: AsenConfig,
        llm: LlmLike,
        tools: ToolRegistry,
        system_prompt: str,
        events: AgentEvents | None = None,
    ) -> None:
        self.config = config
        self.llm = llm
        self.tools = tools
        self.events = events or AgentEvents()
        self.plan_steps: list[PlanStep] = []
        self.context = ConversationContext(
            system_prompt,
            max_messages=config.max_context_messages,
        )

    async def run(self, user_input: str) -> str:
        self.context.add_user(user_input)
        for step in range(1, self.config.max_steps + 1):
            self.events.thinking(step)
            raw_response = await self.llm.complete(
                self.context.as_openai_messages(), self.tools.schemas()
            )
            self.events.llm_response(raw_response)
            parsed = parse_agent_response(raw_response)
            if parsed.invalid_reason:
                self.context.add_assistant(raw_response)
                self.context.add_user(_format_invalid_response_feedback(parsed.invalid_reason))
                continue
            if parsed.plan_steps:
                self._set_plan(parsed.plan_steps)
                self.context.add_assistant(raw_response)
                self.context.add_user(_format_plan_accepted_feedback())
                continue
            if not parsed.tool_calls:
                final = parsed.final_text or raw_response
                self.context.add_assistant(final)
                return final

            self.context.add_assistant(raw_response)
            active_step = self._start_next_plan_step()
            all_tools_ok = True
            for call in parsed.tool_calls:
                self.events.tool_call(call.name, call.arguments)
                result = await self.tools.execute(call.name, call.arguments)
                all_tools_ok = all_tools_ok and result.ok
                rendered = truncate_text(result.render(), self.config.max_tool_output_chars)
                self.events.tool_result(call.name, rendered)
                self.context.add_tool(call.name, rendered)
                if not result.ok:
                    self.context.add_user(_format_tool_failure_feedback(call.name, result))
            self._finish_plan_step(active_step, success=all_tools_ok)

        final = (
            "Agent stopped because max_steps was reached. "
            "Try a smaller task or increase max_steps."
        )
        self.context.add_assistant(final)
        return final

    def _set_plan(self, steps: list[PlanStep]) -> None:
        self.plan_steps = [
            PlanStep(id=step.id, content=step.content, status="pending") for step in steps
        ]
        self.events.plan(self.plan_steps)

    def _start_next_plan_step(self) -> PlanStep | None:
        for index, step in enumerate(self.plan_steps):
            if step.status == "pending":
                updated = step.model_copy(update={"status": "in_progress"})
                self.plan_steps[index] = updated
                self.events.plan_step(updated)
                return updated
        return None

    def _finish_plan_step(self, step: PlanStep | None, *, success: bool) -> None:
        if step is None:
            return
        status = "completed" if success else "failed"
        for index, current in enumerate(self.plan_steps):
            if current.id == step.id:
                updated = current.model_copy(update={"status": status})
                self.plan_steps[index] = updated
                self.events.plan_step(updated)
                return


def parse_agent_response(raw_response: str) -> AgentResponse:
    payload = _extract_json_payload(raw_response)
    if payload is None:
        return AgentResponse(invalid_reason="response was not a JSON object")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return AgentResponse(invalid_reason=f"response JSON was invalid: {exc.msg}")

    if isinstance(data, dict) and "final" in data:
        return AgentResponse(final_text=str(data.get("final") or ""))
    if isinstance(data, dict) and "final_text" in data:
        return AgentResponse(final_text=str(data.get("final_text") or ""))
    if isinstance(data, dict) and "plan" in data:
        try:
            return AgentResponse(plan_steps=_parse_plan_steps(data.get("plan")))
        except ValueError as exc:
            return AgentResponse(invalid_reason=str(exc))
    if isinstance(data, dict) and "tool_calls" in data:
        try:
            calls = [ToolCall.model_validate(item) for item in data.get("tool_calls") or []]
        except ValidationError as exc:
            return AgentResponse(invalid_reason=f"tool_calls did not match schema: {exc}")
        return AgentResponse(tool_calls=calls)
    return AgentResponse(invalid_reason="JSON must contain final, plan, or tool_calls")


def _parse_plan_steps(raw_plan: Any) -> list[PlanStep]:
    if not isinstance(raw_plan, list) or not raw_plan:
        raise ValueError("plan must be a non-empty list")
    steps: list[PlanStep] = []
    for index, item in enumerate(raw_plan, start=1):
        if isinstance(item, str):
            content = item.strip()
            if not content:
                raise ValueError("plan step content must not be empty")
            steps.append(PlanStep(id=str(index), content=content))
            continue
        if isinstance(item, dict):
            content = str(item.get("content") or item.get("task") or "").strip()
            if not content:
                raise ValueError("plan step content must not be empty")
            step_id = str(item.get("id") or index)
            steps.append(PlanStep(id=step_id, content=content))
            continue
        raise ValueError("plan steps must be strings or objects")
    return steps


def _format_invalid_response_feedback(reason: str) -> str:
    return (
        f"Your previous response could not be used because {reason}. "
        "Retry with exactly one JSON object and no surrounding prose. "
        "Use {\"final\": \"...\"} for final answers, "
        "{\"plan\": [{\"id\": \"1\", \"content\": \"...\"}]} for plans, or "
        "{\"tool_calls\": [{\"name\": \"...\", \"arguments\": {...}}]} for tool calls. "
        "If the user asked you to create, write, edit, read, list, fetch, or run something, "
        "call the appropriate tool instead of only describing the action."
    )


def _format_plan_accepted_feedback() -> str:
    return (
        "Plan accepted. Execute it step by step. Use tools as needed. "
        "If a step fails, correct the action or return a revised plan before continuing. "
        "Return a final answer only after the plan is complete or clearly blocked."
    )


def _format_tool_failure_feedback(tool_name: str, result: Any) -> str:
    retry_instruction = (
        "Please correct the tool name or arguments and retry if needed. "
        "If the failure changes the approach, return a revised plan."
        if result.retryable
        else (
            "Do not repeat the same unsafe or rejected action. "
            "Explain the failure or choose a safer alternative."
        )
    )
    return (
        f"The previous tool call `{tool_name}` failed with {result.error_type}: "
        f"{result.error}. {retry_instruction}"
    )


def _extract_json_payload(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = JSON_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def load_system_prompt() -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / "system.md"
    return path.read_text(encoding="utf-8")
