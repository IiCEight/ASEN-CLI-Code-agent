from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import ValidationError

from ..config import AsenConfig
from ..tools.registry import ToolRegistry
from ..utils.safety import truncate_text
from .context_manager import ContextManager
from .protocol import AgentResponse, PlanStep, ToolCall
from .token_budget import TokenBudget


class LlmLike(Protocol):
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


@dataclass(slots=True)
class AgentEvents:
    on_thinking: Callable[[int], None] | None = None
    on_llm_response: Callable[[str], None] | None = None
    on_stream_delta: Callable[[str], None] | None = None
    on_stream_end: Callable[[], None] | None = None
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

    def stream_delta(self, chunk: str) -> None:
        if self.on_stream_delta:
            self.on_stream_delta(chunk)

    def stream_end(self) -> None:
        if self.on_stream_end:
            self.on_stream_end()

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
FINAL_FIELD_PATTERN = re.compile(r'^\{\s*"(?P<field>final|final_text)"\s*:\s*"')
JSON_ESCAPE_SEQUENCES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class Agent:
    def __init__(
        self,
        *,
        config: AsenConfig,
        llm: LlmLike,
        tools: ToolRegistry,
        system_prompt: str,
        events: AgentEvents | None = None,
        stream: bool = False,
    ) -> None:
        self.config = config
        self.llm = llm
        self.tools = tools
        self.events = events or AgentEvents()
        self.stream = stream
        self.plan_steps: list[PlanStep] = []
        self.context = ContextManager(
            system_prompt,
            token_budget=TokenBudget(
                max_context_tokens=config.max_context_tokens,
                reserve_output_tokens=config.reserve_output_tokens,
            ),
            max_recent_messages=config.max_context_messages,
            max_tool_result_chars=config.max_tool_output_chars,
        )

    def load_context_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.context.load_snapshot(snapshot)
        self.plan_steps = [
            step.model_copy() for step in self.context.plan_steps
        ]

    async def run(self, user_input: str) -> str:
        self.context.add_user(user_input)
        for step in range(1, self.config.max_steps + 1):
            self.events.thinking(step)
            messages = self.context.as_openai_messages()
            tool_schemas = self.tools.schemas()
            raw_response = await self._complete_once(messages, tool_schemas)
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

    async def _complete_once(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]],
    ) -> str:
        if not self.stream:
            return await self.llm.complete(messages, tools)

        raw_response = ""
        streamed_preview = ""
        try:
            async for chunk in self.llm.stream_complete(messages, tools):
                raw_response += chunk
                preview = _extract_partial_final_text(raw_response) or ""
                delta = preview[len(streamed_preview) :]
                if delta:
                    self.events.stream_delta(delta)
                streamed_preview = preview
        finally:
            self.events.stream_end()
        return raw_response

    def _set_plan(self, steps: list[PlanStep]) -> None:
        self.plan_steps = [
            PlanStep(id=step.id, content=step.content, status="pending") for step in steps
        ]
        self.context.set_plan(self.plan_steps)
        self.events.plan(self.plan_steps)

    def _start_next_plan_step(self) -> PlanStep | None:
        for index, step in enumerate(self.plan_steps):
            if step.status == "pending":
                updated = step.model_copy(update={"status": "in_progress"})
                self.plan_steps[index] = updated
                self.context.set_plan(self.plan_steps)
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
                self.context.set_plan(self.plan_steps)
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


def _extract_partial_final_text(text: str) -> str | None:
    payload = _extract_json_stream_candidate(text)
    if payload is None:
        return None
    match = FINAL_FIELD_PATTERN.match(payload)
    if match is None:
        return None
    value, _closed = _decode_partial_json_string(payload[match.end() :])
    return value


def _extract_json_payload(text: str) -> str | None:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    match = JSON_BLOCK_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    return None


def _extract_json_stream_candidate(text: str) -> str | None:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return stripped
    if not stripped.startswith("```"):
        return None
    newline = stripped.find("\n")
    if newline == -1:
        return None
    return stripped[newline + 1 :].lstrip()


def _decode_partial_json_string(text: str) -> tuple[str, bool]:
    chars: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == '"':
            return "".join(chars), True
        if char != "\\":
            chars.append(char)
            index += 1
            continue

        index += 1
        if index >= len(text):
            return "".join(chars), False

        escaped = text[index]
        if escaped == "u":
            hex_digits = text[index + 1 : index + 5]
            if len(hex_digits) < 4 or not re.fullmatch(r"[0-9a-fA-F]{4}", hex_digits):
                return "".join(chars), False
            chars.append(chr(int(hex_digits, 16)))
            index += 5
            continue

        mapped = JSON_ESCAPE_SEQUENCES.get(escaped)
        if mapped is None:
            return "".join(chars), False
        chars.append(mapped)
        index += 1
    return "".join(chars), False


def load_system_prompt() -> str:
    path = Path(__file__).resolve().parents[1] / "prompts" / "system.md"
    return path.read_text(encoding="utf-8")
