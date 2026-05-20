from __future__ import annotations

from .protocol import ChatMessage


class TokenBudget:
    def __init__(self, *, max_context_tokens: int, reserve_output_tokens: int = 2_000) -> None:
        self.max_context_tokens = max_context_tokens
        self.reserve_output_tokens = reserve_output_tokens

    @property
    def input_budget(self) -> int:
        return max(1, self.max_context_tokens - self.reserve_output_tokens)

    def estimate_text_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def estimate_message_tokens(self, message: ChatMessage) -> int:
        name_cost = self.estimate_text_tokens(message.name or "") if message.name else 0
        return self.estimate_text_tokens(message.content) + name_cost + 4

    def estimate_messages_tokens(self, messages: list[ChatMessage]) -> int:
        return sum(self.estimate_message_tokens(message) for message in messages)
