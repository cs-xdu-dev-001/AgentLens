from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Any

from ..services.agent_execution import AgentEventSink, AgentExecution
from ..services.agent_trace import sanitize_trace_value
from ..services.session_portability import (
    available_export_path,
    render_session_markdown,
    safe_export_filename,
)


MAX_TUI_ATTACHMENT_PATHS = 8


def _workspace_reference_token(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.startswith("@"):
        raw = raw[1:].strip()
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        raw = raw[1:-1]
    raw = raw.replace("\\", "/")
    while raw.startswith("./"):
        raw = raw[2:]
    if (
        not raw
        or raw.startswith("/")
        or re.match(r"^[A-Za-z]:/", raw)
        or '"' in raw
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
        or ".." in raw.split("/")
    ):
        return ""
    return f'@"{raw}"' if any(character.isspace() for character in raw) else f"@{raw}"


def question_with_workspace_attachments(
    question: str,
    attachment_paths: list[str] | tuple[str, ...] | None,
) -> str:
    text = str(question or "").strip()
    tokens: list[str] = []
    seen: set[str] = set()
    for value in attachment_paths or []:
        token = _workspace_reference_token(value)
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)
        if len(tokens) >= MAX_TUI_ATTACHMENT_PATHS:
            break
    if not tokens:
        return text
    return f"{text}\n\n工作区上下文：\n" + "\n".join(tokens)


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
        self.reasoning_effort = "default"
        self._model_label: str | None = None
        self.session_id: str | None = None
        self.conversation: list[dict[str, Any]] = []
        self.transcript: list[dict[str, Any]] = []
        self.context_metadata: dict[str, Any] = {}
        self.current_run_id: str | None = None

    @property
    def model_label(self) -> str:
        if self._model_label:
            return self._model_label
        if self.remote_client is not None:
            return f"模型 {self.model_id}" if self.model_id else "默认模型"
        if self.local_agent is None:
            return "未配置模型"
        try:
            value = self.local_agent.config_store.load()
            return str(value.get("model_name") or "默认模型")
        except Exception:
            return "默认模型"

    def model_catalog(self) -> list[dict[str, Any]]:
        """Return chat models that can be selected without exposing credentials."""
        if self.remote_client is None:
            if self.local_agent is None:
                return []
            value = self.local_agent.config_store.load()
            name = str(value.get("model_name") or "默认模型")
            self._model_label = name
            return [
                {
                    "id": "local",
                    "name": name,
                    "modelName": name,
                    "provider": str(value.get("provider") or "custom"),
                    "apiMode": str(value.get("api_mode") or "responses"),
                    "selected": True,
                    "switchable": False,
                }
            ]

        payload = self.remote_client.request(
            "GET",
            "/api/model-configs",
            params={"modelType": "chat"},
        )
        rows = payload if isinstance(payload, list) else []
        selected_id = self.model_id
        if selected_id is None:
            default = next((row for row in rows if row.get("isDefault")), None)
            selected_id = default.get("id") if default else None
        models: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict) or row.get("modelType") not in {None, "chat"}:
                continue
            identifier = row.get("id")
            selected = identifier == selected_id
            name = str(row.get("name") or row.get("modelName") or f"模型 {identifier}")
            models.append(
                {
                    "id": identifier,
                    "name": name,
                    "modelName": str(row.get("modelName") or ""),
                    "provider": str(row.get("provider") or ""),
                    "apiMode": str(row.get("apiMode") or "chat_completions"),
                    "selected": selected,
                    "switchable": True,
                }
            )
            if selected:
                self._model_label = name
        return models

    def select_model(self, model_id: Any) -> dict[str, Any]:
        if self.remote_client is None:
            models = self.model_catalog()
            if models and str(model_id) in {"", "local", str(models[0]["id"])}:
                return models[0]
            raise RuntimeError("本地CLI只有当前配置；请运行agentlens configure修改模型。")
        try:
            identifier = int(model_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("请选择有效的模型配置。") from exc
        models = self.model_catalog()
        selected = next((item for item in models if item.get("id") == identifier), None)
        if selected is None:
            raise ValueError("模型配置不存在或不可用。")
        self.model_id = identifier
        self._model_label = str(selected.get("name") or selected.get("modelName") or f"模型 {identifier}")
        for item in models:
            item["selected"] = item.get("id") == identifier
        return {**selected, "selected": True, "label": self._model_label}

    def local_model_configuration(self) -> dict[str, Any]:
        """Return editable local model metadata without exposing credentials."""
        if self.remote_client is not None or self.local_agent is None:
            raise RuntimeError("远程模式请到Web设置页管理模型配置。")
        value = self.local_agent.config_store.editable_snapshot()
        return {
            "provider": str(value.get("provider") or "custom"),
            "baseUrl": str(value.get("base_url") or ""),
            "modelName": str(value.get("model_name") or ""),
            "apiMode": str(value.get("api_mode") or "responses"),
            "hasApiKey": bool(value.get("has_api_key")),
            "overriddenFields": dict(value.get("overridden_fields") or {}),
        }

    def configure_local_model(self, value: dict[str, Any]) -> dict[str, Any]:
        """Test and persist a local BYOK model without restarting the TUI."""
        if self.remote_client is not None or self.local_agent is None:
            raise RuntimeError("远程模式请到Web设置页管理模型配置。")
        from ..services.local_cli_runtime import test_local_connection

        store = self.local_agent.config_store
        current = store.load()
        candidate = store.validate_editable(
            provider=str(value.get("provider") or current.get("provider") or "custom"),
            base_url=str(value.get("baseUrl") or ""),
            model_name=str(value.get("modelName") or ""),
            api_mode=str(value.get("apiMode") or "responses"),
            api_key=(
                str(value.get("apiKey") or "").strip()
                if "apiKey" in value
                else None
            ),
        )
        detail = test_local_connection(candidate)
        saved = store.save_editable(
            provider=candidate["provider"],
            base_url=candidate["base_url"],
            model_name=candidate["model_name"],
            api_mode=candidate["api_mode"],
            api_key=(candidate["api_key"] if "apiKey" in value else None),
        )
        self._model_label = saved["model_name"]
        return {
            "detail": str(detail or "连接可用"),
            "model": self._model_label,
            "config": self.local_model_configuration(),
        }

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
            result = dict(status()) if callable(status) else {}
            tools = dict(result.get("tools") or {})
            tools["enabled"] = bool(self.tools)
            result["tools"] = tools
            return result
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
        tool_rows = result.get("tools")
        if isinstance(tool_rows, list):
            result["tools"] = {
                "count": len(tool_rows),
                "enabled": bool(self.tools),
                "items": tool_rows,
            }
        skill_rows = result.get("skills")
        if isinstance(skill_rows, list):
            result["skills"] = {
                "count": len(skill_rows),
                "items": skill_rows,
            }
        mcp_rows = result.get("mcp")
        if isinstance(mcp_rows, list):
            result["mcp"] = {
                "count": len(mcp_rows),
                "connected": sum(
                    1
                    for item in mcp_rows
                    if isinstance(item, dict)
                    and item.get("enabled")
                    and item.get("status") == "connected"
                ),
                "servers": mcp_rows,
            }
        memory = result.get("memory")
        if isinstance(memory, dict):
            try:
                rows = self.remote_client.request(
                    "GET",
                    "/api/memories",
                    params={"limit": 10},
                )
            except Exception:
                rows = []
            result["memory"] = {
                **memory,
                "items": rows if isinstance(rows, list) else [],
            }
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
                    "detail": "远程模式请在服务器运行agentlens doctor。",
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

    def workspace_switch_root(self, path: str) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式不能切换服务器工作区。")
        if self.local_agent is None:
            raise RuntimeError("本地Agent尚未初始化。")
        result = dict(self.local_agent.workspace_switch_root(path))
        self.reset()
        return result

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

    def workspace_undo(
        self,
        operation_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持本地文件撤销。")
        return dict(self.local_agent.workspace_undo(operation_id, run_id))

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        if self.remote_client is not None:
            return []
        return list(self.local_agent.list_sessions(limit=limit))

    def rename_session(self, title: str) -> dict[str, Any]:
        next_title = " ".join(str(title or "").split())
        if not next_title:
            raise ValueError("请输入新的会话名称。")
        if self.remote_client is not None:
            if not self.session_id:
                raise RuntimeError("当前没有可重命名的远程会话。")
            session = self.remote_client.rename_session(self.session_id, next_title)
            return {
                "runId": "",
                "sessionId": self.session_id,
                "title": session.get("title") or next_title,
            }
        if self.local_agent is None or not self.current_run_id:
            raise RuntimeError("当前没有可重命名的本地会话。")
        session = self.local_agent.rename_session(self.current_run_id, next_title)
        return {
            "runId": self.current_run_id,
            "sessionId": "",
            "title": session.get("title") or next_title,
        }

    def rewind_points(self) -> list[dict[str, Any]]:
        if self.remote_client is not None:
            if not self.session_id:
                raise RuntimeError("当前没有可回退的远程会话。")
            source = self.remote_client.request(
                "GET",
                f"/api/sessions/{self.session_id}/messages",
            )
            messages = source if isinstance(source, list) else []
        else:
            if self.local_agent is None or not self.current_run_id:
                raise RuntimeError("当前没有可回退的本地会话。")
            source = self.local_agent.load_session(self.current_run_id)
            messages = list(source.get("messages") or [])
        return [
            {
                "messageId": message.get("id"),
                "messageIndex": index,
                "preview": str(message.get("content") or "").strip(),
            }
            for index, message in enumerate(messages)
            if message.get("role") == "user"
            and str(message.get("content") or "").strip()
        ]

    def branch_session(
        self,
        title: str = "",
        *,
        before_message_id: int | None = None,
        before_message_index: int | None = None,
    ) -> dict[str, Any]:
        if self.remote_client is not None:
            if not self.session_id:
                raise RuntimeError("当前没有可创建分支的远程会话。")
            branch = self.remote_client.branch_session(
                self.session_id,
                title,
                before_message_id=before_message_id,
            )
            branch_id = str(branch.get("id") or "")
            if not branch_id:
                raise RuntimeError("服务器未返回新的会话分支。")
            messages = self.remote_client.request(
                "GET",
                f"/api/sessions/{branch_id}/messages",
            )
            self.session_id = branch_id
            self.current_run_id = None
            self.conversation = [
                {
                    "id": item.get("id"),
                    "role": item.get("role"),
                    "content": item.get("content"),
                }
                for item in (messages if isinstance(messages, list) else [])
                if item.get("role") in {"user", "assistant"}
            ]
            self.transcript = list(self.conversation)
            self.context_metadata = {}
            return {
                "runId": "",
                "sessionId": branch_id,
                "title": branch.get("title"),
                "messageCount": len(self.transcript),
                "messages": self.transcript,
                "restoredQuestion": branch.get("restoredQuestion") or "",
            }
        if self.local_agent is None or not self.current_run_id:
            raise RuntimeError("当前没有可创建分支的本地会话。")
        branch = self.local_agent.branch_session(
            self.current_run_id,
            title,
            before_message_index=before_message_index,
        )
        branch_id = str(branch.get("runId") or "")
        self.current_run_id = branch_id or self.current_run_id
        self.conversation = list(
            branch.get("contextMessages") or branch.get("messages") or []
        )
        self.transcript = list(branch.get("messages") or self.conversation)
        self.context_metadata = dict(branch.get("compaction") or {})
        return {
            "runId": branch_id,
            "sessionId": "",
            "title": branch.get("title"),
            "messageCount": len(self.transcript),
            "messages": self.transcript,
            "restoredQuestion": branch.get("restoredQuestion") or "",
        }

    def export_session(self, filename: str = "") -> dict[str, Any]:
        if not self.transcript and not self.session_id:
            raise RuntimeError("当前没有可导出的会话。")
        if self.remote_client is not None:
            if not self.session_id:
                raise RuntimeError("当前没有可导出的远程会话。")
            exported = self.remote_client.export_session(self.session_id)
            content = str(exported.get("content") or "")
            default_filename = str(
                exported.get("filename") or "agentlens-session.md"
            )
            message_count = int(exported.get("messageCount") or 0)
            directory = Path.cwd()
        else:
            session = (
                self.local_agent.load_session(self.current_run_id)
                if self.local_agent is not None and self.current_run_id
                else {}
            )
            title = str(session.get("title") or "AgentLens会话")
            content = render_session_markdown(title, self.transcript)
            default_filename = safe_export_filename(title)
            message_count = sum(
                1 for item in self.transcript
                if item.get("role") in {"user", "assistant"}
                and str(item.get("content") or "").strip()
            )
            workspace = self.workspace_status()
            directory = Path(str(workspace.get("cwd") or Path.cwd()))
        path = available_export_path(
            directory,
            safe_export_filename(filename or default_filename),
        )
        path.write_text(content, encoding="utf-8")
        if os.name != "nt":
            try:
                path.chmod(0o600)
            except OSError:
                pass
        return {
            "path": str(path),
            "filename": path.name,
            "messageCount": message_count,
        }

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
            execution = self.remote_client.resume(run_id, event_sink)
            self._finish(execution)
            return execution
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
        if status == "waiting_input":
            pending = session.get("pendingQuestion")
            if not isinstance(pending, dict):
                raise RuntimeError("等待回答的会话缺少问题状态。")
            self.conversation = list(
                session.get("contextMessages") or session.get("messages") or []
            )
            self.transcript = list(session.get("messages") or [])
            self.context_metadata = dict(session.get("compaction") or {})
            event = {**pending, "type": "user_question_required", "runId": run_id}
            event_sink(event)
            return AgentExecution(
                result={
                    "paused": True,
                    "runId": run_id,
                    "answer": "",
                    "messages": self.conversation,
                    "transcriptMessages": self.transcript,
                    "compaction": self.context_metadata,
                    "status": status,
                },
                events=[event],
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
        reasoning_effort: str = "default",
        execution_mode: str = "auto",
        attachment_paths: list[str] | None = None,
    ) -> AgentExecution:
        self.reasoning_effort = str(reasoning_effort or "default")
        execution_mode = (
            "plan_only" if execution_mode == "plan_only" else "auto"
        )
        runtime_question = question_with_workspace_attachments(
            question,
            attachment_paths,
        )
        if self.remote_client is not None:
            execution = self.remote_client.run(
                {
                    "question": runtime_question,
                    "sessionId": self.session_id,
                    "chatModelConfigId": self.model_id,
                    "reasoningEffort": self.reasoning_effort,
                    "executionMode": execution_mode,
                    "autoAgent": True,
                    "enableTools": self.tools,
                    "skillId": self.skill_id,
                },
                event_sink,
            )
        else:
            if self.local_agent is None:
                raise RuntimeError("本地Agent尚未初始化。")
            self._auto_compact(event_sink, runtime_question)
            execution = self.local_agent.run(
                runtime_question,
                history=self.conversation,
                transcript=self.transcript,
                context_metadata=self.context_metadata,
                tools=self.tools,
                reasoning_effort=self.reasoning_effort,
                execution_mode=execution_mode,
                event_sink=event_sink,
            )
        self._finish(execution)
        return execution

    def run_shell(
        self,
        command: str,
        event_sink: AgentEventSink,
    ) -> AgentExecution:
        if self.remote_client is not None:
            raise RuntimeError("远程模式暂不支持本地Shell，请在服务器终端运行命令。")
        if self.local_agent is None:
            raise RuntimeError("本地Agent尚未初始化。")
        runner = getattr(self.local_agent, "run_shell_command", None)
        if not callable(runner):
            raise RuntimeError("当前本地运行时不支持Shell模式。")
        return runner(command, event_sink=event_sink)

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
                reasoning_effort=self.reasoning_effort,
                run_id=run_id,
                approval_decision=decision,
                event_sink=event_sink,
            )
        self._finish(resolved)
        return resolved

    def answer_question(
        self,
        execution: AgentExecution,
        answer: dict[str, Any],
        event_sink: AgentEventSink,
    ) -> AgentExecution:
        run_id = str(execution.result.get("runId") or "")
        question_id = execution.question_id
        if not run_id or not question_id:
            raise RuntimeError("Agent问题状态不完整。")
        payload = {
            "questionId": question_id,
            "answer": str(answer.get("answer") or "").strip()[:4000],
            "selectedOptions": [
                str(value)[:120]
                for value in (answer.get("selectedOptions") or [])
                if str(value).strip()
            ][:4],
        }
        if not payload["answer"]:
            raise ValueError("请先选择或输入回答。")
        if self.remote_client is not None:
            resolved = self.remote_client.answer_question(
                run_id,
                payload,
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
                reasoning_effort=self.reasoning_effort,
                run_id=run_id,
                resume_value=payload,
                resume_from_checkpoint=True,
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
