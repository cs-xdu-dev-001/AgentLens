from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


AgentEventSink = Callable[[dict[str, Any]], None]


@dataclass
class AgentExecution:
    result: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def paused(self) -> bool:
        return bool(self.result.get("paused"))

    @property
    def approval_id(self) -> str | None:
        for event in reversed(self.events):
            if event.get("type") == "approval_required":
                value = str(event.get("approvalId") or "").strip()
                return value or None
        return None

    @property
    def question_id(self) -> str | None:
        for event in reversed(self.events):
            if event.get("type") == "user_question_required":
                value = str(event.get("questionId") or "").strip()
                return value or None
        return None

    @property
    def interrupt_type(self) -> str | None:
        if self.question_id:
            return "user_question"
        if self.approval_id:
            return "tool_approval"
        return None
