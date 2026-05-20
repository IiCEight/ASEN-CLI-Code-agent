from __future__ import annotations

from .protocol import ChatMessage


class ConversationContext:
    def __init__(self, system_prompt: str, max_messages: int = 24) -> None:
        self.max_messages = max_messages
        self.messages: list[ChatMessage] = [ChatMessage(role="system", content=system_prompt)]

    def add_user(self, content: str) -> None:
        self._append(ChatMessage(role="user", content=content))

    def add_assistant(self, content: str) -> None:
        self._append(ChatMessage(role="assistant", content=content))

    def add_tool(self, name: str, content: str) -> None:
        self._append(ChatMessage(role="tool", name=name, content=content))

    def as_openai_messages(self) -> list[dict[str, str]]:
        return [message.to_openai() for message in self.messages]

    def _append(self, message: ChatMessage) -> None:
        self.messages.append(message)
        self._trim()

    def _trim(self) -> None:
        if self.max_messages < 2:
            self.max_messages = 2
        while len(self.messages) > self.max_messages:
            del self.messages[1]
