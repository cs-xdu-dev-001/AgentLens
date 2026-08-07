from __future__ import annotations

import re
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

    @staticmethod
    def _command_name(value: Any) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip())
        return normalized.strip("-").lower()

    def command_catalog(self) -> list[dict[str, str]]:
        catalog: list[dict[str, str]] = []
        if self.remote_client is None:
            if self.local_agent is None or not self.tools:
                return catalog
            for schema in self.local_agent.tool_schemas():
                function = schema.get("function") or {}
                name = self._command_name(function.get("name"))
                if name:
                    catalog.append(
                        {
                            "value": f"/tool:{name}",
                            "description": str(function.get("description") or "调用Agent工具"),
                            "source": "tool",
                        }
                    )
            return catalog

        sources = (
            ("/api/agent/tools", "tool", "name", "Agent工具"),
            ("/api/skills/", "skill", "name", "Skill"),
            ("/api/mcp/servers", "mcp", "slug", "MCP服务"),
        )
        for path, source, preferred_key, fallback in sources:
            try:
                payload = self.remote_client.request("GET", path, params={})
            except Exception:
                continue
            if not isinstance(payload, list):
                continue
            for item in payload:
                if not isinstance(item, dict):
                    continue
                raw_name = item.get(preferred_key) or item.get("name") or item.get("slug")
                name = self._command_name(raw_name)
                if not name:
                    continue
                description = str(
                    item.get("description")
                    or item.get("summary")
                    or f"使用{fallback} {raw_name}"
                )
                catalog.append(
                    {
                        "value": f"/{source}:{name}",
                        "description": description,
                        "source": source,
                    }
                )
        try:
            models = self.remote_client.request(
                "GET",
                "/api/model-configs",
                params={"modelType": "chat"},
            )
        except Exception:
            models = []
        if isinstance(models, list):
            for item in models:
                if not isinstance(item, dict) or item.get("id") is None:
                    continue
                model_id = str(item.get("id"))
                label = str(
                    item.get("name")
                    or item.get("configName")
                    or item.get("model")
                    or item.get("modelName")
                    or f"模型 {model_id}"
                )
                catalog.append(
                    {
                        "value": f"/model use {model_id}",
                        "description": f"切换到{label}",
                        "source": "builtin-model",
                    }
                )
        return catalog

    def cancel(self, run_id: str | None) -> bool:
        if self.remote_client is None or not run_id:
            return False
        self.remote_client.request(
            "POST",
            f"/api/agent/runs/{run_id}/cancel",
        )
        return True

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
