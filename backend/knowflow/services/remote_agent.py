from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlsplit

import requests

from .agent_execution import AgentExecution


SESSION_COOKIE = "knowflow_session"
TERMINAL_EVENTS = {"done", "error", "cancelled"}


class RemoteAgentError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def normalize_server_url(value: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("服务器地址必须是完整的HTTP或HTTPS URL。")
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" and host not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise ValueError("远程服务器必须使用HTTPS。")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务器地址不能包含凭据、查询参数或片段。")
    if parsed.path not in {"", "/"}:
        raise ValueError("服务器地址只能填写站点根地址。")
    return raw


def iter_sse(lines: Iterable[str | bytes]) -> Iterable[dict[str, Any]]:
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in lines:
        line = (
            raw_line.decode("utf-8", errors="replace")
            if isinstance(raw_line, bytes)
            else str(raw_line)
        ).rstrip("\r")
        if not line:
            if data_lines:
                try:
                    payload = json.loads("\n".join(data_lines))
                except json.JSONDecodeError as exc:
                    raise RemoteAgentError(
                        "invalid_sse_payload",
                        "服务器返回了无法解析的事件。",
                    ) from exc
                if isinstance(payload, dict):
                    payload.setdefault("type", event_name)
                    yield payload
            event_name = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or "message"
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            payload = json.loads("\n".join(data_lines))
        except json.JSONDecodeError as exc:
            raise RemoteAgentError(
                "invalid_sse_payload",
                "服务器返回了无法解析的事件。",
            ) from exc
        if isinstance(payload, dict):
            payload.setdefault("type", event_name)
            yield payload


class RemoteProfileStore:
    def __init__(self, path: Path | None = None):
        self.path = path or Path.home() / ".knowflow" / "remote.json"

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(value, dict):
            return None
        server = str(value.get("server") or "")
        token = str(value.get("token") or "")
        if not server or not token:
            return None
        return value

    def save(self, profile: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.path.parent.chmod(0o700)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(profile, ensure_ascii=False),
            encoding="utf-8",
        )
        if os.name != "nt":
            temporary.chmod(0o600)
        temporary.replace(self.path)
        if os.name != "nt":
            self.path.chmod(0o600)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


@dataclass
class RemoteAgentClient:
    server: str
    token: str = ""
    timeout: float = 30.0
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.server = normalize_server_url(self.server)
        if self.session is None:
            self.session = requests.Session()

    @property
    def headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.server}/{path.lstrip('/')}"

    @staticmethod
    def _error(response: requests.Response) -> RemoteAgentError:
        code = f"http_{response.status_code}"
        message = "远程请求失败。"
        try:
            payload = response.json()
            detail = payload.get("detail") if isinstance(payload, dict) else None
            source = detail if isinstance(detail, dict) else payload
            if isinstance(source, dict):
                code = str(source.get("code") or code)
                message = str(
                    source.get("message")
                    or source.get("detail")
                    or message
                )
            elif detail:
                message = str(detail)
        except (ValueError, TypeError):
            pass
        if response.status_code == 401:
            code = "authentication_required"
            message = "登录已失效，请重新执行knowflow auth login。"
        return RemoteAgentError(code, message)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        assert self.session is not None
        try:
            response = self.session.request(
                method,
                self._url(path),
                json=body,
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RemoteAgentError(
                "remote_unavailable",
                "无法连接KnowFlow服务器。",
            ) from exc
        if not response.ok:
            raise self._error(response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise RemoteAgentError(
                "invalid_remote_response",
                "服务器返回了无效响应。",
            ) from exc
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    def login(self, account: str, password: str) -> dict[str, Any]:
        assert self.session is not None
        data = self.request(
            "POST",
            "/api/auth/login",
            body={"account": account, "password": password},
        )
        token = self.session.cookies.get(SESSION_COOKIE) or ""
        if not token:
            raise RemoteAgentError(
                "session_cookie_missing",
                "服务器未返回CLI可用的登录会话。",
            )
        self.token = token
        return data if isinstance(data, dict) else {}

    def start_device_authorization(self) -> dict[str, Any]:
        data = self.request(
            "POST",
            "/api/auth/cli/device",
            body={"clientName": "KnowFlow CLI"},
        )
        if not isinstance(data, dict) or not data.get("deviceCode"):
            raise RemoteAgentError(
                "invalid_device_authorization",
                "服务器未返回有效的浏览器授权信息。",
            )
        return data

    def poll_device_authorization(self, device_code: str) -> dict[str, Any]:
        data = self.request(
            "POST",
            "/api/auth/cli/device/token",
            body={"deviceCode": device_code},
        )
        if not isinstance(data, dict):
            raise RemoteAgentError(
                "invalid_device_authorization",
                "服务器返回了无效的授权状态。",
            )
        if data.get("status") == "authorized":
            token = str(data.get("sessionToken") or "")
            if not token:
                raise RemoteAgentError(
                    "session_token_missing",
                    "服务器未返回CLI会话令牌。",
                )
            self.token = token
        return data

    def logout(self) -> None:
        if self.token:
            self.request("POST", "/api/auth/logout")

    def stream(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> Iterable[dict[str, Any]]:
        assert self.session is not None
        headers = {**self.headers, "Accept": "text/event-stream"}
        try:
            response = self.session.request(
                method,
                self._url(path),
                json=body,
                headers=headers,
                timeout=(10, 3600),
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise RemoteAgentError(
                "remote_unavailable",
                "无法连接KnowFlow服务器。",
            ) from exc
        if not response.ok:
            raise self._error(response)
        with response:
            yield from iter_sse(response.iter_lines(decode_unicode=True))

    def run(
        self,
        payload: dict[str, Any],
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentExecution:
        return self._collect(
            self.stream("POST", "/api/agent/chat/stream", body=payload),
            event_sink,
        )

    def watch_run(
        self,
        run_id: str,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentExecution:
        execution = self._collect(
            self.stream("GET", f"/api/agent/runs/{run_id}/events"),
            event_sink,
            run_id=run_id,
        )
        if not str(execution.result.get("answer") or "").strip():
            self._hydrate_answer(execution)
        return execution

    def _hydrate_answer(self, execution: AgentExecution) -> None:
        session_id = str(execution.result.get("sessionId") or "")
        if not session_id:
            return
        messages = self.request(
            "GET", f"/api/sessions/{session_id}/messages"
        )
        if not isinstance(messages, list):
            return
        message_id = execution.result.get("messageId")
        candidates = [
            item
            for item in messages
            if isinstance(item, dict) and item.get("role") == "assistant"
        ]
        selected = next(
            (
                item
                for item in candidates
                if message_id is not None
                and str(item.get("id")) == str(message_id)
            ),
            candidates[-1] if candidates else None,
        )
        if selected is not None:
            execution.result["answer"] = str(
                selected.get("content") or ""
            )

    def resume(
        self,
        run_id: str,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentExecution:
        self.request("POST", f"/api/agent/runs/{run_id}/resume")
        return self.watch_run(run_id, event_sink)

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        decision: str,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> AgentExecution:
        result = self.request(
            "POST",
            f"/api/agent/approvals/{approval_id}",
            body={"decision": decision},
        )
        if isinstance(result, dict) and result.get("resumeRequired"):
            self.request("POST", f"/api/agent/runs/{run_id}/resume")
        return self.watch_run(run_id, event_sink)

    @staticmethod
    def _collect(
        source: Iterable[dict[str, Any]],
        event_sink: Callable[[dict[str, Any]], None] | None,
        *,
        run_id: str | None = None,
    ) -> AgentExecution:
        events: list[dict[str, Any]] = []
        answer: list[str] = []
        result: dict[str, Any] = {}
        paused = False
        for event in source:
            events.append(event)
            if event_sink is not None:
                event_sink(event)
            event_type = str(event.get("type") or "")
            if event_type in {"message", "answer"}:
                answer.append(str(event.get("content") or ""))
            if event_type == "approval_required":
                paused = True
            snapshot = event.get("run")
            if isinstance(snapshot, dict):
                result["run"] = snapshot
                result["runId"] = snapshot.get("id") or run_id
                result["sessionId"] = snapshot.get("sessionId")
                result["messageId"] = snapshot.get("assistantMessageId")
                paused = snapshot.get("status") == "waiting_approval"
            for key in ("runId", "sessionId", "messageId", "memoryActivity"):
                if event.get(key) is not None:
                    result[key] = event[key]
            if event_type == "error":
                raise RemoteAgentError(
                    str(event.get("code") or "agent_run_failed"),
                    str(event.get("message") or "Agent运行失败。"),
                )
            if event_type in TERMINAL_EVENTS or paused:
                break
        result.setdefault("runId", run_id)
        result["answer"] = "".join(answer)
        result["paused"] = paused
        result.setdefault("trace", [])
        result.setdefault("toolCalls", [])
        result.setdefault("references", [])
        return AgentExecution(result=result, events=events)
