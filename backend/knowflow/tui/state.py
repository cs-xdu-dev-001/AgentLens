from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TuiSessionState:
    queued_questions: list[str] = field(default_factory=list)
    session_approvals: dict[str, str] = field(default_factory=dict)
    tool_calls: int = 0
    seen_tool_calls: set[str] = field(default_factory=set)
    cancel_requested: bool = False

    def reset_run(self) -> None:
        self.tool_calls = 0
        self.seen_tool_calls.clear()
        self.cancel_requested = False

    def record_tool(self, event: dict[str, Any]) -> None:
        name = str(
            event.get("toolName")
            or event.get("tool_name")
            or event.get("name")
            or "tool"
        )
        identifier = str(
            event.get("toolCallId")
            or event.get("callId")
            or event.get("id")
            or name
        )
        if identifier not in self.seen_tool_calls:
            self.seen_tool_calls.add(identifier)
            self.tool_calls += 1

    def reset_session(self) -> None:
        self.queued_questions.clear()
        self.session_approvals.clear()
        self.reset_run()
