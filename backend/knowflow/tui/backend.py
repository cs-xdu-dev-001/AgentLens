from __future__ import annotations

from typing import Any

from ..services.agent_execution import AgentEventSink, AgentExecution


class TuiBackend:
    """Stateful adapter shared by the local and remote CLI transports."""

    def __init__(
        self,
        *,
        local_agent: Any | None,
        remote_client: Any | None,
        tools: bool,
        model_id: int | None,
        skill_id: int | None,
    ) -> None:
        self.local_agent = local_agent
        self.remote_client = remote_client
        self.tools = tools
        self.model_id = model_id
        self.skill_id = skill_id
        self.session_id: str | None = None
        self.conversation: list[dict[str, Any]] = []

    @property
    def model_label(self) -> str:
        if self.remote_client is not None:
            return f"模型 {self.model_id}" if self.model_id else "默认模型"
        if self.local_agent is None:
            return "未配置模型"
        try:
            value = self.local_agent.config_store.load()
            return str(value.get("model_name") or "默认模型")
        except Exception:
            return "默认模型"

    def reset(self) -> None:
        self.session_id = None
        self.conversation = []

    def run(
        self,
        question: str,
        event_sink: AgentEventSink,
    ) -> AgentExecution:
        if self.remote_client is not None:
            execution = self.remote_client.run(
                {
                    "question": question,
                    "sessionId": self.session_id,
                    "chatModelConfigId": self.model_id,
                    "autoAgent": True,
                    "enableTools": self.tools,
                    "skillId": self.skill_id,
                },
                event_sink,
            )
        else:
            if self.local_agent is None:
                raise RuntimeError("本地Agent尚未初始化。")
            execution = self.local_agent.run(
                question,
                history=self.conversation,
                tools=self.tools,
                event_sink=event_sink,
            )
        self._finish(execution)
        return execution

    def resolve(
        self,
        execution: AgentExecution,
        decision: str,
        event_sink: AgentEventSink,
    ) -> AgentExecution:
        run_id = str(execution.result.get("runId") or "")
        if not run_id:
            raise RuntimeError("Agent审批状态不完整。")
        if self.remote_client is not None:
            approval_id = execution.approval_id
            if not approval_id:
                raise RuntimeError("Agent审批信息不可用。")
            resolved = self.remote_client.resolve_approval(
                run_id,
                approval_id,
                decision,
                event_sink,
            )
        else:
            if self.local_agent is None:
                raise RuntimeError("本地Agent尚未初始化。")
            resolved = self.local_agent.run(
                "",
                history=list(execution.result.get("messages") or []),
                tools=self.tools,
                run_id=run_id,
                approval_decision=decision,
                event_sink=event_sink,
            )
        self._finish(resolved)
        return resolved

    def _finish(self, execution: AgentExecution) -> None:
        if execution.paused:
            return
        value = execution.result
        self.session_id = str(
            value.get("sessionId") or self.session_id or ""
        ) or None
        if self.remote_client is None:
            self.conversation = list(
                value.get("messages") or self.conversation
            )
            answer = str(value.get("answer") or "")
            if answer:
                self.conversation.append(
                    {"role": "assistant", "content": answer}
                )
