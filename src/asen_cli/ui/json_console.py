from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..core.agent import AgentEvents
from ..core.protocol import PlanStep
from .console import AsenConsole


class AsenJsonConsole(AsenConsole):
    def __init__(self, *, verbose: bool = False) -> None:
        super().__init__(verbose=verbose)
        self.events_log: list[dict[str, Any]] = []
        self.final_text = ""
        self.error_message: str | None = None
        self.tool_results: list[dict[str, Any]] = []
        self.tool_failures: list[dict[str, Any]] = []
        self.changed_files: list[dict[str, Any]] = []
        self.checkpoints: list[dict[str, Any]] = []
        self._changed_file_keys: set[tuple[str, str]] = set()
        self._checkpoint_ids: set[str] = set()

    def title(self, mode: str = "chat") -> None:
        return

    def clear(self, mode: str = "chat") -> None:
        return

    def info(self, message: str) -> None:
        self._append_event("info", message=message)

    def success(self, message: str) -> None:
        self._append_event("success", message=message)

    def error(self, message: str) -> None:
        self.error_message = message
        self._append_event("error", message=message)

    def assistant(self, message: str) -> None:
        self.final_text = message
        self._append_event("assistant", text=message)

    def stream_delta(self, chunk: str) -> None:
        if chunk:
            self._append_event("stream_delta", text=chunk)

    def stream_end(self) -> None:
        self._append_event("stream_end")

    def thinking(self, step: int) -> None:
        self._append_event("thinking", step=step)

    def plan(self, steps: list[PlanStep]) -> None:
        self._append_event(
            "plan",
            steps=[step.model_dump(mode="json") for step in steps],
        )

    def plan_step(self, step: PlanStep) -> None:
        self._append_event("plan_step", step=step.model_dump(mode="json"))

    def tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        self._append_event("tool_call", name=name, arguments=arguments)

    def tool_result(self, name: str, rendered: str) -> None:
        return

    def tool_result_structured(self, name: str, payload: dict[str, Any]) -> None:
        result = {"name": name, **payload}
        self.tool_results.append(result)
        if not payload.get("ok", True):
            self.tool_failures.append(result)
        self._append_event("tool_result", name=name, result=payload)
        meta = payload.get("meta") or {}
        for item in meta.get("changed_files", []):
            key = (
                str(item.get("checkpoint_id") or ""),
                str(item.get("path") or ""),
            )
            if key in self._changed_file_keys:
                continue
            self._changed_file_keys.add(key)
            self.changed_files.append(item)
        for checkpoint in meta.get("checkpoints", []):
            checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
            if not checkpoint_id or checkpoint_id in self._checkpoint_ids:
                continue
            self._checkpoint_ids.add(checkpoint_id)
            self.checkpoints.append(checkpoint)

    def raw_llm_response(self, raw_response: str) -> None:
        if self.verbose_enabled:
            self._append_event("raw_llm_response", text=raw_response)

    def sessions(self, rows: list[dict[str, Any]]) -> None:
        self._append_event("sessions", rows=rows)

    def checkpoints_view(self, rows: list[dict[str, Any]]) -> None:
        self._append_event("checkpoints", rows=rows)

    def checkpoint_diff(self, checkpoint_id: str, rendered: str) -> None:
        self._append_event(
            "checkpoint_diff",
            checkpoint_id=checkpoint_id,
            diff=rendered,
        )

    def help(self, message: str) -> None:
        self._append_event("help", message=message)

    def paste_hint(self) -> None:
        self._append_event("paste_hint")

    def goodbye(self) -> None:
        self._append_event("goodbye")

    def verbose(self, message: str) -> None:
        if self.verbose_enabled:
            self._append_event("verbose", message=message)

    def confirm(self, message: str) -> bool:
        self._append_event("confirm_required", message=message)
        return False

    def agent_events(self) -> AgentEvents:
        return AgentEvents(
            on_thinking=self.thinking,
            on_llm_response=self.raw_llm_response,
            on_stream_delta=self.stream_delta,
            on_stream_end=self.stream_end,
            on_plan=self.plan,
            on_plan_step=self.plan_step,
            on_tool_call=self.tool_call,
            on_tool_result=self.tool_result,
            on_tool_result_structured=self.tool_result_structured,
        )

    def build_ask_payload(self, *, task: str, workspace: Path) -> dict[str, Any]:
        return {
            "ok": self.error_message is None,
            "command": "ask",
            "task": task,
            "workspace": str(workspace),
            "final_text": self.final_text,
            "events": self.events_log,
            "tool_results": self.tool_results,
            "tool_failures": self.tool_failures,
            "checkpoints": self.checkpoints,
            "changed_files": self.changed_files,
        }

    def _append_event(self, event_type: str, **payload: Any) -> None:
        self.events_log.append(
            {
                "type": event_type,
                "timestamp": datetime.now(UTC).isoformat(),
                **payload,
            }
        )
