from __future__ import annotations

from collections import Counter

from ..utils.safety import truncate_text
from .protocol import ChatMessage, PlanStep
from .token_budget import TokenBudget

FACT_LIMIT = 20
SUMMARY_LIMIT = 4_000
SUMMARY_ITEM_LIMIT = 240
TOOL_COMPRESS_LIMIT = 4_000
TOOL_HEAD_CHARS = 1_600
TOOL_TAIL_CHARS = 1_200


class ContextManager:
    def __init__(
        self,
        system_prompt: str,
        *,
        token_budget: TokenBudget,
        max_recent_messages: int = 16,
        max_tool_result_chars: int = TOOL_COMPRESS_LIMIT,
    ) -> None:
        self.system_prompt = system_prompt
        self.token_budget = token_budget
        self.max_recent_messages = max(4, max_recent_messages)
        self.max_tool_result_chars = max(500, max_tool_result_chars)
        self.messages: list[ChatMessage] = []
        self.summary: str | None = None
        self.facts: list[str] = []
        self.plan_steps: list[PlanStep] = []

    def add_user(self, content: str) -> None:
        if not self.facts:
            self.remember_fact(f"User goal: {truncate_text(content, 240)}")
        self._append(ChatMessage(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        self._append(ChatMessage(role="assistant", content=content))

    def add_tool(self, name: str, content: str) -> None:
        compressed = compress_tool_result(name, content, self.max_tool_result_chars)
        self._append(ChatMessage(role="tool", name=name, content=compressed))
        self._extract_tool_fact(name, compressed)

    def set_plan(self, steps: list[PlanStep]) -> None:
        self.plan_steps = steps
        if steps:
            rendered = "; ".join(f"{step.id}. {step.content}" for step in steps)
            self.remember_fact(f"Current plan: {truncate_text(rendered, 500)}")

    def remember_fact(self, fact: str) -> None:
        normalized = fact.strip()
        if not normalized or normalized in self.facts:
            return
        self.facts.append(normalized)
        if len(self.facts) > FACT_LIMIT:
            self.facts = self.facts[-FACT_LIMIT:]

    def as_openai_messages(self) -> list[dict[str, str]]:
        self._compact_recent_messages()
        messages = self._compose_messages()
        messages = self._trim_to_budget(messages)
        return [message.to_openai() for message in messages]

    def _append(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self._compact_recent_messages()

    def _compact_recent_messages(self) -> None:
        if len(self.messages) <= self.max_recent_messages:
            return
        keep = self.max_recent_messages
        old_messages = self.messages[:-keep]
        self.messages = self.messages[-keep:]
        self._merge_summary(old_messages)

    def _merge_summary(self, old_messages: list[ChatMessage]) -> None:
        if not old_messages:
            return
        role_counts = Counter(message.role for message in old_messages)
        lines = []
        if self.summary:
            lines.append(self.summary)
        counts = ", ".join(f"{role}={count}" for role, count in sorted(role_counts.items()))
        lines.append(f"Compacted {len(old_messages)} older messages ({counts}).")
        for message in old_messages[-6:]:
            label = f"{message.role}:{message.name}" if message.name else message.role
            snippet = truncate_text(message.content.replace("\n", " "), SUMMARY_ITEM_LIMIT)
            lines.append(f"- {label}: {snippet}")
        self.summary = truncate_text("\n".join(lines), SUMMARY_LIMIT)

    def _compose_messages(self) -> list[ChatMessage]:
        composed = [ChatMessage(role="system", content=self.system_prompt)]
        if self.summary:
            composed.append(
                ChatMessage(role="user", content=f"Conversation summary:\n{self.summary}")
            )
        if self.facts:
            facts = "\n".join(f"- {fact}" for fact in self.facts)
            composed.append(ChatMessage(role="user", content=f"Key facts:\n{facts}"))
        if self.plan_steps:
            composed.append(ChatMessage(role="user", content=render_plan(self.plan_steps)))
        composed.extend(self.messages)
        return composed

    def _trim_to_budget(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        budget = self.token_budget.input_budget
        trimmed = list(messages)
        while len(trimmed) > 2 and self.token_budget.estimate_messages_tokens(trimmed) > budget:
            removable_index = self._first_removable_index(trimmed)
            if removable_index is None:
                break
            removed = trimmed.pop(removable_index)
            self._merge_summary([removed])
            trimmed = self._compose_messages()
        return trimmed

    def _first_removable_index(self, messages: list[ChatMessage]) -> int | None:
        for index, message in enumerate(messages):
            if index == 0:
                continue
            if message.content.startswith(("Key facts:", "Current plan:")):
                continue
            return index
        return None

    def _extract_tool_fact(self, name: str, content: str) -> None:
        if name in {"write_file", "replace_in_file", "apply_patch"} and "ERROR" not in content:
            first_line = content.splitlines()[0] if content else name
            self.remember_fact(f"File edit: {truncate_text(first_line, 220)}")
        if "ERROR" in content:
            first_line = content.splitlines()[0]
            self.remember_fact(f"Tool failure from {name}: {truncate_text(first_line, 220)}")


def compress_tool_result(tool_name: str, content: str, max_chars: int = TOOL_COMPRESS_LIMIT) -> str:
    if len(content) <= max_chars:
        return content

    head = content[: min(TOOL_HEAD_CHARS, max_chars // 2)]
    tail = content[-min(TOOL_TAIL_CHARS, max_chars // 3) :]
    omitted = len(content) - len(head) - len(tail)
    return (
        f"[compressed tool result]\n"
        f"tool={tool_name}\n"
        f"original_chars={len(content)}\n"
        f"kept_head_chars={len(head)}\n"
        f"kept_tail_chars={len(tail)}\n\n"
        f"--- head ---\n{head}\n"
        f"--- omitted {omitted} chars ---\n"
        f"--- tail ---\n{tail}"
    )


def render_plan(steps: list[PlanStep]) -> str:
    lines = ["Current plan:"]
    for step in steps:
        lines.append(f"- [{step.status}] {step.id}. {step.content}")
    return "\n".join(lines)
