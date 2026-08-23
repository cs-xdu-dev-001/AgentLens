from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from hashlib import sha256
import json
from pathlib import Path
import sys
from threading import Lock, Thread
from typing import Any, TextIO

from ..services.agent_event_protocol import (
    AGENT_EVENT_SCHEMA_VERSION,
    normalize_agent_event,
)
from ..services.agent_execution import AgentExecution
from ..services.agent_trace import sanitize_trace_value
from ..services.remote_agent import RemoteAgentClient, RemoteProfileStore
from ..services.local_cli_runtime import local_data_dir
from .backend import TuiBackend
from .state import PromptHistoryStore


PROTOCOL_VERSION = 7


def _history_scope(backend: TuiBackend) -> str:
    """Keep prompt history local and isolated to the active workspace/server."""
    remote_client = getattr(backend, "remote_client", None)
    if remote_client is not None:
        source = f"remote:{remote_client.server}"
    else:
        status = backend.workspace_status()
        root = str(status.get("projectRoot") or status.get("cwd") or Path.cwd())
        source = f"local:{Path(root).expanduser()}"
    return sha256(source.encode("utf-8")).hexdigest()[:24]


def _public_history(values: Any) -> list[str]:
    return [
        str(sanitize_trace_value(value, max_chars=10_000) or "")
        for value in values if str(value or "").strip()
    ][-500:]


def _public_session(value: dict[str, Any]) -> dict[str, Any]:
    """Bound session summaries before they cross the terminal protocol."""
    return {
        "runId": str(value.get("runId") or "")[:80],
        "title": str(sanitize_trace_value(value.get("title"), max_chars=160) or ""),
        "status": str(value.get("status") or "")[:40],
        "updatedAt": value.get("updatedAt"),
        "cwd": str(sanitize_trace_value(value.get("cwd"), max_chars=240) or ""),
        "answer": str(sanitize_trace_value(value.get("answer"), max_chars=320) or ""),
    }


def _public_sessions(values: Any) -> list[dict[str, Any]]:
    return [
        _public_session(value)
        for value in values if isinstance(value, dict) and value.get("runId")
    ]


class InkRuntimeBridge:
    """Line-delimited JSON bridge between Ink and the Python Agent runtime."""

    def __init__(
        self,
        backend: TuiBackend,
        *,
        input_stream: TextIO,
        output_stream: TextIO,
    ) -> None:
        self.backend = backend
        self.input_stream = input_stream
        self.output_stream = output_stream
        self._write_lock = Lock()
        self._state_lock = Lock()
        self._running = False
        self._stopping = False
        self._pending: AgentExecution | None = None
        self._queued_decision: str | None = None
        self._queued_answer: dict[str, Any] | None = None
        self._request_id = ""
        self._run_id = ""
        self.history_store = PromptHistoryStore(
            local_data_dir() / "history" / f"{_history_scope(backend)}.jsonl"
        )

    def send(self, payload: dict[str, Any]) -> None:
        with self._write_lock:
            self.output_stream.write(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            self.output_stream.flush()

    def _public_error(self, exc: Exception) -> str:
        value = sanitize_trace_value(str(exc), max_chars=500)
        return str(value or type(exc).__name__)

    def _agent_event(self, event: dict[str, Any]) -> None:
        event = normalize_agent_event(event, run_id=self._run_id or None)
        run_id = str(event.get("runId") or "")
        if run_id:
            self._run_id = run_id
        safe_event = _public_value(event, max_chars=12_000)
        if not isinstance(safe_event, dict):
            safe_event = {
                "type": str(event.get("type") or "runtime_event"),
                "runId": run_id,
                "toolCallId": str(event.get("toolCallId") or ""),
                "toolName": str(event.get("toolName") or ""),
                "status": str(event.get("status") or ""),
                "output": safe_event,
            }
        self.send(
            {
                "type": "agent_event",
                "requestId": self._request_id,
                "event": safe_event,
            }
        )

    def _set_running(self, value: bool) -> bool:
        with self._state_lock:
            if value and self._running:
                return False
            self._running = value
            return True

    def _complete(self, execution: AgentExecution) -> None:
        if execution.paused:
            with self._state_lock:
                self._pending = execution
            self.send(
                {
                    "type": "turn_paused",
                    "requestId": self._request_id,
                    "runId": str(execution.result.get("runId") or self._run_id),
                    "approvalId": execution.approval_id,
                    "questionId": execution.question_id,
                    "interruptType": execution.interrupt_type,
                }
            )
        else:
            with self._state_lock:
                self._pending = None
            self.send(
                {
                    "type": "turn_completed",
                    "requestId": self._request_id,
                    "runId": str(execution.result.get("runId") or self._run_id),
                    "answer": str(execution.result.get("answer") or ""),
                    "cancelled": bool(execution.result.get("cancelled")),
                    "restored": bool(execution.result.get("restored")),
                    "messages": (
                        self._public_messages(execution.result.get("messages"))
                        if execution.result.get("restored")
                        else None
                    ),
                    "changes": self._workspace_changes(),
                }
            )

    @staticmethod
    def _public_messages(value: Any) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in value if isinstance(value, list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            if role not in {"user", "assistant"}:
                continue
            content = sanitize_trace_value(item.get("content"), max_chars=20_000)
            messages.append({"role": role, "content": str(content or "")})
        return messages[-50:]

    def _workspace_changes(self) -> list[dict[str, Any]]:
        try:
            value = self.backend.workspace_diff()
        except Exception:
            return []
        files = value.get("files") if isinstance(value, dict) else []
        return list(files) if isinstance(files, list) else []

    def _execute(self, callback: Any) -> None:
        queued_decision = None
        queued_answer = None
        try:
            with redirect_stdout(sys.stderr):
                execution = callback()
            self._complete(execution)
        except Exception as exc:
            self.send(
                {
                    "type": "turn_failed",
                    "requestId": self._request_id,
                    "runId": self._run_id,
                    "message": self._public_error(exc),
                }
            )
        finally:
            self._set_running(False)
            with self._state_lock:
                if self._pending is not None and self._queued_decision is not None:
                    queued_decision = self._queued_decision
                    self._queued_decision = None
                if self._pending is not None and self._queued_answer is not None:
                    queued_answer = self._queued_answer
                    self._queued_answer = None
        if queued_decision is not None:
            self._approve({"decision": queued_decision})
        elif queued_answer is not None:
            self._answer_question(queued_answer)

    def _start(self, callback: Any) -> None:
        if not self._set_running(True):
            self.send({"type": "busy", "message": "当前任务尚未结束。"})
            return
        Thread(target=self._execute, args=(callback,), daemon=True).start()

    def _submit(self, message: dict[str, Any]) -> None:
        text = str(message.get("text") or "").strip()
        if not text:
            return
        with self._state_lock:
            if self._running:
                self.send({"type": "busy", "message": "当前任务尚未结束。"})
                return
        self._request_id = str(message.get("requestId") or "")
        self._run_id = ""
        self._pending = None
        self._queued_decision = None
        self._queued_answer = None
        self._queued_answer = None
        if not self.history_store.append(text):
            self.send(
                {
                    "type": "history_failed",
                    "action": "append",
                    "message": "输入历史无法保存，本次任务仍会继续。",
                }
            )
        reasoning_effort = str(
            message.get("reasoningEffort") or "default"
        )
        self._start(
            lambda: self.backend.run(
                text,
                self._agent_event,
                reasoning_effort=reasoning_effort,
            )
        )

    def _shell(self, message: dict[str, Any]) -> None:
        command = str(message.get("command") or "").strip()
        if not command:
            return
        with self._state_lock:
            if self._running:
                self.send({"type": "busy", "message": "当前任务尚未结束。"})
                return
        self._request_id = str(message.get("requestId") or "")
        self._run_id = ""
        self._pending = None
        self._queued_decision = None
        self._queued_answer = None
        if not self.history_store.append(f"!{command}"):
            self.send(
                {
                    "type": "history_failed",
                    "action": "append",
                    "message": "输入历史无法保存，本次命令仍会继续。",
                }
            )
        self._start(lambda: self.backend.run_shell(command, self._agent_event))

    def _history(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "list")
        if action == "list":
            self.send(
                {
                    "type": "history_result",
                    "action": action,
                    "history": _public_history(self.history_store.load()),
                }
            )
            return
        if action == "clear":
            cleared = self.history_store.clear()
            self.send(
                {
                    "type": "history_result" if cleared else "history_failed",
                    "action": action,
                    "history": [],
                    "message": (
                        "本工作区的输入历史已清空。"
                        if cleared
                        else "输入历史文件无法删除。"
                    ),
                }
            )
            return
        self.send(
            {
                "type": "history_failed",
                "action": action,
                "message": "未知历史操作。",
            }
        )

    def _approve(self, message: dict[str, Any]) -> None:
        decision = str(message.get("decision") or "deny")
        if decision not in {"allow_once", "allow_session", "deny"}:
            decision = "deny"
        with self._state_lock:
            if self._running:
                self._queued_decision = decision
                self.send({"type": "approval_queued"})
                return
            execution = self._pending
        if execution is None:
            self.send({"type": "protocol_error", "message": "没有等待审批的任务。"})
            return
        self._pending = None
        self._start(
            lambda: self.backend.resolve(execution, decision, self._agent_event)
        )

    def _answer_question(self, message: dict[str, Any]) -> None:
        answer = str(message.get("answer") or "").strip()[:4000]
        selected = [
            str(value)[:120]
            for value in (message.get("selectedOptions") or [])
            if str(value).strip()
        ][:4]
        if not answer:
            self.send({"type": "protocol_error", "message": "请先选择或输入回答。"})
            return
        payload = {"answer": answer, "selectedOptions": selected}
        with self._state_lock:
            if self._running:
                self._queued_answer = payload
                self.send({"type": "question_answer_queued"})
                return
            execution = self._pending
        if execution is None or execution.interrupt_type != "user_question":
            self.send({"type": "protocol_error", "message": "没有等待回答的问题。"})
            return
        self._pending = None
        self._start(
            lambda: self.backend.answer_question(
                execution,
                payload,
                self._agent_event,
            )
        )

    def _doctor(self) -> None:
        try:
            with redirect_stdout(sys.stderr):
                checks = self.backend.sandbox_diagnostics()
            self.send({"type": "doctor_result", "checks": checks})
        except Exception as exc:
            self.send({"type": "doctor_failed", "message": self._public_error(exc)})

    def _workspace(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "status")
        try:
            if action == "status":
                result = self.backend.workspace_status()
            elif action == "add":
                result = self.backend.workspace_add_directory(str(message.get("path") or ""))
            elif action == "cd":
                result = self.backend.workspace_change_directory(str(message.get("path") or ""))
            elif action == "diff":
                result = self.backend.workspace_diff(str(message.get("path") or "") or None)
            elif action == "undo":
                result = self.backend.workspace_undo(
                    str(message.get("operationId") or "") or None,
                    str(message.get("runId") or "") or None,
                )
            else:
                raise ValueError("Unknown workspace action.")
        except Exception as exc:
            self.send(
                {
                    "type": "workspace_failed",
                    "action": action,
                    "message": self._public_error(exc),
                }
            )
        else:
            self.send(
                {
                    "type": "workspace_result",
                    "action": action,
                    "result": _public_value(result, max_chars=100_000),
                }
            )

    def _resume_session(self, message: dict[str, Any]) -> None:
        run_id = str(message.get("runId") or "")
        if not run_id:
            self.send({"type": "protocol_error", "message": "请选择要恢复的会话。"})
            return
        self._request_id = str(message.get("requestId") or "")
        self._run_id = run_id
        self._pending = None
        self._queued_decision = None
        self._start(lambda: self.backend.restore_session(run_id, self._agent_event))

    def _context(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "status")
        if action == "status":
            try:
                result = self.backend.context_status()
            except Exception as exc:
                self.send(
                    {
                        "type": "context_failed",
                        "action": action,
                        "message": self._public_error(exc),
                    }
                )
            else:
                self.send(
                    {
                        "type": "context_status",
                        "status": _public_value(result, max_chars=20_000),
                    }
                )
            return
        if action != "compact":
            self.send({"type": "protocol_error", "message": "未知上下文操作。"})
            return
        if not self._set_running(True):
            self.send({"type": "busy", "message": "请等待当前任务结束后再压缩上下文。"})
            return

        def compact() -> None:
            try:
                with redirect_stdout(sys.stderr):
                    result = self.backend.compact_context(
                        str(message.get("instructions") or "")
                    )
            except Exception as exc:
                self.send(
                    {
                        "type": "context_failed",
                        "action": action,
                        "message": self._public_error(exc),
                    }
                )
            else:
                self.send(
                    {
                        "type": "context_compacted",
                        "reason": "manual",
                        **_public_value(result, max_chars=20_000),
                    }
                )
            finally:
                self._set_running(False)

        Thread(target=compact, daemon=True).start()

    def _models(self, message: dict[str, Any]) -> None:
        action = str(message.get("action") or "list")
        if self._running:
            self.send({"type": "busy", "message": "请等待当前任务结束后再切换模型。"})
            return
        try:
            if action == "list":
                models = self.backend.model_catalog()
                self.send(
                    {
                        "type": "model_list",
                        "models": _public_value(models, max_chars=20_000),
                        "model": self.backend.model_label,
                    }
                )
                return
            if action != "use":
                raise ValueError("未知模型操作。")
            selected = self.backend.select_model(message.get("modelId"))
            self.send(
                {
                    "type": "model_changed",
                    "model": self.backend.model_label,
                    "selected": _public_value(selected, max_chars=2_000),
                }
            )
        except Exception as exc:
            self.send(
                {
                    "type": "model_failed",
                    "action": action,
                    "message": self._public_error(exc),
                }
            )

    def handle(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        if message_type == "submit":
            self._submit(message)
        elif message_type == "shell":
            self._shell(message)
        elif message_type == "approve":
            self._approve(message)
        elif message_type == "answer_question":
            self._answer_question(message)
        elif message_type == "cancel":
            try:
                accepted = self.backend.cancel(self._run_id or None)
            except Exception as exc:
                self.send(
                    {
                        "type": "cancel_requested",
                        "requestId": self._request_id,
                        "runId": self._run_id,
                        "accepted": False,
                        "message": self._public_error(exc),
                    }
                )
            else:
                self.send(
                    {
                        "type": "cancel_requested",
                        "requestId": self._request_id,
                        "runId": self._run_id,
                        "accepted": bool(accepted),
                    }
                )
        elif message_type == "reset":
            if self._running:
                self.send({"type": "busy", "message": "请先取消当前任务。"})
            else:
                self.backend.reset()
                self._pending = None
                self._queued_decision = None
                self._queued_answer = None
                self.send({"type": "session_reset"})
        elif message_type == "catalog":
            self.send({"type": "command_catalog", "commands": self.backend.command_catalog()})
        elif message_type == "capabilities":
            try:
                status = self.backend.capability_status()
            except Exception as exc:
                self.send(
                    {
                        "type": "capability_failed",
                        "section": str(message.get("section") or ""),
                        "message": self._public_error(exc),
                    }
                )
            else:
                self.send(
                    {
                        "type": "capability_status",
                        "section": str(message.get("section") or ""),
                        "status": _public_value(status, max_chars=20_000),
                    }
                )
        elif message_type == "doctor":
            Thread(target=self._doctor, daemon=True).start()
        elif message_type == "workspace":
            self._workspace(message)
        elif message_type == "sessions":
            try:
                sessions = self.backend.list_sessions(limit=int(message.get("limit") or 20))
            except Exception as exc:
                self.send({"type": "sessions_failed", "message": self._public_error(exc)})
            else:
                self.send({"type": "session_list", "sessions": _public_sessions(sessions)})
        elif message_type == "resume_session":
            self._resume_session(message)
        elif message_type == "context":
            self._context(message)
        elif message_type == "history":
            self._history(message)
        elif message_type == "models":
            self._models(message)
        elif message_type == "shutdown":
            self._stopping = True
            if self._running:
                self.backend.cancel(self._run_id or None)
        else:
            self.send({"type": "protocol_error", "message": "未知运行时命令。"})

    def run(self) -> None:
        workspace = _public_value(self.backend.workspace_status(), max_chars=20_000)
        try:
            models = _public_value(self.backend.model_catalog(), max_chars=20_000)
        except Exception:
            models = []
        self.send(
            {
                "type": "runtime_handshake",
                "protocolVersion": PROTOCOL_VERSION,
                "agentEventSchemaVersion": AGENT_EVENT_SCHEMA_VERSION,
                "python": sys.executable,
                "model": self.backend.model_label,
                "workspace": workspace,
            }
        )
        self.send(
            {
                "type": "ready",
                "protocolVersion": PROTOCOL_VERSION,
                "agentEventSchemaVersion": AGENT_EVENT_SCHEMA_VERSION,
                "model": self.backend.model_label,
                "commands": self.backend.command_catalog(),
                "workspace": workspace,
                "sessions": _public_sessions(self.backend.list_sessions(limit=8)),
                "history": _public_history(self.history_store.load()),
                "models": models,
            }
        )
        for line in self.input_stream:
            if self._stopping:
                break
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                self.send({"type": "protocol_error", "message": "运行时消息不是有效JSON。"})
                continue
            if not isinstance(payload, dict):
                self.send({"type": "protocol_error", "message": "运行时消息必须是对象。"})
                continue
            self.handle(payload)


def _parse_config() -> dict[str, Any]:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    value = json.loads(args.config)
    if not isinstance(value, dict):
        raise ValueError("Ink runtime config must be an object")
    return value


def _public_value(value: Any, *, max_chars: int) -> Any:
    safe = sanitize_trace_value(value, max_chars=max_chars)
    if safe is None:
        return None
    if not isinstance(safe, str):
        return safe
    try:
        return json.loads(safe)
    except json.JSONDecodeError:
        return safe


def _backend(config: dict[str, Any]) -> TuiBackend:
    mode = str(config.get("mode") or "local")
    if mode == "remote":
        server = str(config.get("server") or "")
        if not server:
            raise RuntimeError("远程服务器地址为空。")
        profile = RemoteProfileStore().load() or {}
        token = (
            str(profile.get("token") or "")
            if str(profile.get("server") or "").rstrip("/") == server.rstrip("/")
            else ""
        )
        if not token:
            raise RuntimeError("远程登录已失效，请重新运行knowflow auth login。")
        remote = RemoteAgentClient(server, token=token)
        local_agent = None
    else:
        from ..cli import _local_agent

        remote = None
        workspace_root = str(config.get("workspaceRoot") or "").strip()
        local_agent = _local_agent(Path(workspace_root) if workspace_root else None)
    return TuiBackend(
        local_agent=local_agent,
        remote_client=remote,
        tools=bool(config.get("tools", True)),
        model_id=config.get("modelId"),
        skill_id=config.get("skillId"),
    )


def main() -> None:
    protocol_output = sys.stdout
    try:
        config = _parse_config()
        with redirect_stdout(sys.stderr):
            backend = _backend(config)
        InkRuntimeBridge(
            backend,
            input_stream=sys.stdin,
            output_stream=protocol_output,
        ).run()
    except Exception as exc:
        value = sanitize_trace_value(str(exc), max_chars=500)
        protocol_output.write(
            json.dumps(
                {"type": "startup_failed", "message": str(value or type(exc).__name__)},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
        protocol_output.flush()
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
