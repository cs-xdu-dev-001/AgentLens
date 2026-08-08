from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import sys
from threading import Lock, Thread
from typing import Any, TextIO

from ..services.agent_execution import AgentExecution
from ..services.agent_trace import sanitize_trace_value
from ..services.remote_agent import RemoteAgentClient, RemoteProfileStore
from .backend import TuiBackend


PROTOCOL_VERSION = 1


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
        self._request_id = ""
        self._run_id = ""

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
                }
            )

    def _execute(self, callback: Any) -> None:
        queued_decision = None
        try:
            with redirect_stdout(sys.stderr):
                execution = callback()
            self._complete(execution)
        except Exception as exc:
            self.send(
                {
                    "type": "turn_failed",
                    "requestId": self._request_id,
                    "message": self._public_error(exc),
                }
            )
        finally:
            self._set_running(False)
            with self._state_lock:
                if self._pending is not None and self._queued_decision is not None:
                    queued_decision = self._queued_decision
                    self._queued_decision = None
        if queued_decision is not None:
            self._approve({"decision": queued_decision})

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
        self._start(lambda: self.backend.run(text, self._agent_event))

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

    def _doctor(self) -> None:
        try:
            with redirect_stdout(sys.stderr):
                checks = self.backend.sandbox_diagnostics()
            self.send({"type": "doctor_result", "checks": checks})
        except Exception as exc:
            self.send({"type": "doctor_failed", "message": self._public_error(exc)})

    def handle(self, message: dict[str, Any]) -> None:
        message_type = str(message.get("type") or "")
        if message_type == "submit":
            self._submit(message)
        elif message_type == "approve":
            self._approve(message)
        elif message_type == "cancel":
            try:
                accepted = self.backend.cancel(self._run_id or None)
            except Exception as exc:
                self.send(
                    {
                        "type": "cancel_requested",
                        "accepted": False,
                        "message": self._public_error(exc),
                    }
                )
            else:
                self.send({"type": "cancel_requested", "accepted": bool(accepted)})
        elif message_type == "reset":
            if self._running:
                self.send({"type": "busy", "message": "请先取消当前任务。"})
            else:
                self.backend.reset()
                self._pending = None
                self._queued_decision = None
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
        elif message_type == "shutdown":
            self._stopping = True
            if self._running:
                self.backend.cancel(self._run_id or None)
        else:
            self.send({"type": "protocol_error", "message": "未知运行时命令。"})

    def run(self) -> None:
        self.send(
            {
                "type": "ready",
                "protocolVersion": PROTOCOL_VERSION,
                "model": self.backend.model_label,
                "commands": self.backend.command_catalog(),
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
        local_agent = _local_agent()
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
