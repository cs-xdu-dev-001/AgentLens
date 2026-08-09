from __future__ import annotations

import re
from typing import Any

from ..services.agent_execution import AgentEventSink, AgentExecution
from ..services.agent_trace import sanitize_trace_value


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
        self.transcript: list[dict[str, Any]] = []
        self.context_metadata: dict[str, Any] = {}
        self.current_run_id: str | None = None

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
        self.transcript = []
        self.context_metadata = {}
        self.current_run_id = None

    @staticmethod
    def _command_name(value: Any) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip())
        return normalized.strip("-").lower()

    @staticmethod
    def _command_description(value: Any, fallback: str) -> str:
        safe = str(sanitize_trace_value(value or fallback, max_chars=160) or fallback)
        return " ".join(safe.split())

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
                            "description": self._command_description(
                                function.get("description"), "调用Agent工具"
                            ),
                            "source": "tool",
                        }
                    )
            status = self.local_agent.capability_status()
            for item in (status.get("skills") or {}).get("items") or []:
                name = self._command_name(item.get("slug") or item.get("name"))
                if name:
                    catalog.append(
                        {
                            "value": f"/skill:{name}",
                            "description": self._command_description(
                                item.get("description"), "使用Skill"
                            ),
                            "source": "skill",
                        }
                    )
            for item in (status.get("mcp") or {}).get("servers") or []:
                if not item.get("enabled") or item.get("status") != "connected":
                    continue
                name = self._command_name(item.get("slug") or item.get("name"))
                if name:
                    catalog.append(
                        {
                            "value": f"/mcp:{name}",
                            "description": f"使用MCP服务 {item.get('name') or name}",
                            "source": "mcp",
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
                description = self._command_description(
                    item.get("description") or item.get("summary"),
                    f"使用{fallback} {raw_name}",
                )
                catalog.append(
                    {
                        "value": f"/{source}:{name}",
                        "description": description,
                        "source": source,
                    }
                )
        return catalog

    def capability_status(self) -> dict[str, Any]:
        if self.remote_client is None:
            if self.local_agent is None:
                return {}
            status = getattr(self.local_agent, "capability_status", None)
            return dict(status()) if callable(status) else {}
        result: dict[str, Any] = {}
        for key, path in (
            ("tools", "/api/agent/tools"),
            ("skills", "/api/skills/"),
            ("mcp", "/api/mcp/servers"),
            ("memory", "/api/memory/settings"),
        ):
            try:
                result[key] = self.remote_client.request("GET", path, params={})
            except Exception:
                result[key] = None
        return result

    def cancel(self, run_id: str | None) -> bool:
        if self.remote_client is None:
            cancel = getattr(self.local_agent, "cancel", None)
            return bool(cancel(run_id)) if callable(cancel) else False
        if not run_id:
            return False
        self.remote_client.request(
            "POST",
            f"/api/agent/runs/{run_id}/cancel",
        )
        return True

    def sandbox_diagnostics(self) -> list[dict[str, Any]]:
        if self.remote_client is not None:
            return [
                {
                    "name": "mode",
                    "ready": False,
                    "detail": "远程模式请在服务器运行knowflow doctor。",
                }
            ]
        diagnostic = getattr(self.local_agent, "sandbox_diagnostics", None)
        if not callable(diagnostic):
            return [
                {
                    "name": "sandbox",
                    "ready": False,
                    "detail": "当前CLI不支持SRT诊断。",
                }
            ]
        return list(diagnostic(smoke=True))

    def workspace_status(self) -> dict[str, Any]:
        if self.remote_client is not None:
            return {"remote": True, "message": "远程模式的工作区由服务器管理。"}
        if self.local_agent is None:
            return {}
        return dict(self.local_agent.workspace_status())

    def workspace_add_directory(self, path: str) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持从CLI添加本地目录。")
        return dict(self.local_agent.workspace_add_directory(path))

    def workspace_change_directory(self, path: str) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式不能修改服务器工作目录。")
        return dict(self.local_agent.workspace_change_directory(path))

    def workspace_diff(self, path: str | None = None) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持本地Diff视图。")
        return dict(self.local_agent.workspace_diff(path))

    def workspace_undo(self) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持本地文件撤销。")
        return dict(self.local_agent.workspace_undo())

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.remote_client is not None:
            return []
        return list(self.local_agent.list_sessions(limit=limit))

    def context_status(self) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持CLI上下文管理。")
        if self.local_agent is None:
            raise RuntimeError("本地Agent尚未初始化。")
        status = dict(self.local_agent.context_status(self.conversation))
        status["compaction"] = dict(self.context_metadata)
        status["transcriptMessageCount"] = len(self.transcript)
        return status

    def compact_context(self, instructions: str = "") -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持CLI上下文压缩。")
        if self.local_agent is None:
            raise RuntimeError("本地Agent尚未初始化。")
        result = dict(
            self.local_agent.compact_context(
                self.conversation,
                instructions=instructions,
                reason="manual",
            )
        )
        if result.get("compacted"):
            self.conversation = list(result.get("messages") or [])
            self.context_metadata = dict(result.get("metadata") or {})
            if self.current_run_id:
                self.local_agent.save_context_state(
                    self.current_run_id,
                    messages=self.conversation,
                    metadata=self.context_metadata,
                )
        result.pop("messages", None)
        result["transcriptMessageCount"] = len(self.transcript)
        return result

    def _auto_compact(
        self,
        event_sink: AgentEventSink,
        pending_user_text: str = "",
    ) -> None:
        if self.local_agent is None or not self.conversation:
            return
        preview = list(self.conversation)
        if pending_user_text:
            preview.append({"role": "user", "content": pending_user_text})
        status = dict(self.local_agent.context_status(preview))
        if not status.get("shouldAutoCompact"):
            return
        event_sink(
            {
                "type": "context_compaction_started",
                "reason": "automatic",
                "usedTokens": status.get("usedTokens"),
                "maxTokens": status.get("maxTokens"),
            }
        )
        try:
            result = dict(
                self.local_agent.compact_context(
                    self.conversation,
                    reason="automatic",
                )
            )
        except Exception:
            event_sink(
                {
                    "type": "context_compaction_failed",
                    "reason": "automatic",
                    "message": "自动压缩失败，已保留原上下文。",
                }
            )
            return
        if not result.get("compacted"):
            event_sink(
                {
                    "type": "context_compaction_failed",
                    "reason": "automatic",
                    "message": "当前会话缺少可安全压缩的早期轮次，已保留原上下文。",
                }
            )
            return
        self.conversation = list(result.get("messages") or [])
        self.context_metadata = dict(result.get("metadata") or {})
        compacted_status = dict(result.get("status") or {})
        event_sink(
            {
                "type": "context_compacted",
                "reason": "automatic",
                "originalTokens": self.context_metadata.get("originalTokens"),
                "compactedTokens": self.context_metadata.get("compactedTokens"),
                "usagePercent": compacted_status.get("usagePercent"),
            }
        )

    def restore_session(
        self,
        run_id: str,
        event_sink: AgentEventSink,
    ) -> AgentExecution:
        if self.remote_client is not None:
            raise RuntimeError("远程会话请使用Web端恢复。")
        session = self.local_agent.load_session(run_id)
        self.current_run_id = run_id
        status = str(session.get("status") or "")
        if status == "completed":
            self.conversation = list(
                session.get("contextMessages")
                or session.get("messages")
                or []
            )
            self.transcript = list(session.get("messages") or [])
            self.context_metadata = dict(session.get("compaction") or {})
            return AgentExecution(
                result={
                    "paused": False,
                    "runId": run_id,
                    "answer": "",
                    "messages": self.transcript,
                    "contextMessages": self.conversation,
                    "compaction": self.context_metadata,
                    "restored": True,
                    "status": status,
                },
                events=[],
            )
        execution = self.local_agent.resume_session(
            run_id,
            event_sink=event_sink,
        )
        self._finish(execution)
        return execution

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
            self._auto_compact(event_sink, question)
            execution = self.local_agent.run(
                question,
                history=self.conversation,
                transcript=self.transcript,
                context_metadata=self.context_metadata,
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
                transcript=list(
                    execution.result.get("transcriptMessages")
                    or self.transcript
                    or execution.result.get("messages")
                    or []
                ),
                context_metadata=dict(
                    execution.result.get("compaction")
                    or self.context_metadata
                ),
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
        run_id = str(value.get("runId") or "")
        if run_id:
            self.current_run_id = run_id
        self.session_id = str(
            value.get("sessionId") or self.session_id or ""
        ) or None
        if self.remote_client is None:
            self.conversation = list(
                value.get("messages") or self.conversation
            )
            self.transcript = list(
                value.get("transcriptMessages")
                or self.transcript
                or self.conversation
            )
            self.context_metadata = dict(
                value.get("compaction") or self.context_metadata
            )
            answer = str(value.get("answer") or "")
            if answer:
                self.conversation.append(
                    {"role": "assistant", "content": answer}
                )
                self.transcript.append(
                    {"role": "assistant", "content": answer}
                )
