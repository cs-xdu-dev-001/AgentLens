from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from threading import Event, Lock
import time
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

import requests

from .agent_event_protocol import (
    AgentEventNormalizer,
    artifact_event_from_tool_execution,
)
from .agent_execution import AgentExecution, AgentEventSink
from .agent_loop import ToolExecution, ToolRegistry
from .agent_tooling import (
    register_mcp_tools,
    register_user_question_tool,
    register_web_fetch_tool,
    register_web_search_tool,
)
from .agent_trace import AgentTraceRecorder, sanitize_trace_value
from .context_compaction import (
    compact_context,
    context_status,
)
from .langgraph_agent_engine import (
    AgentRunCancelledError,
    LangGraphAgentEngine,
)
from .model_gateway import ModelGateway
from .local_cli_extensions import LocalExtensionStore
from .mcp_client import McpRunSessionPool
from .mcp_config import MCP_MAX_EXPOSED_TOOLS
from .mcp_oauth import McpOAuthCoordinator
from .skill_runtime import SkillActivationSession
from .web_fetch import PublicWebFetcher
from .web_search import TavilyWebSearch
from .workspace_runtime import (
    RunSandboxCommandArguments,
    SrtSandboxRunner,
    WorkspaceContext,
    WorkspaceRuntime,
    register_workspace_tools,
)
from .workspace_references import (
    extract_workspace_references,
    load_workspace_references,
    workspace_reference_trace_title,
)
from .session_portability import unique_branch_title


LOCAL_USER_ID = 1
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_LOCAL_MAX_TOOL_ROUNDS = 50
DEFAULT_LOCAL_MAX_CONTEXT_TOKENS = 96_000


def local_cli_max_tool_rounds() -> int:
    try:
        configured = int(
            os.getenv(
                "KNOWFLOW_CLI_MAX_TOOL_ROUNDS",
                str(DEFAULT_LOCAL_MAX_TOOL_ROUNDS),
            )
        )
    except ValueError:
        configured = DEFAULT_LOCAL_MAX_TOOL_ROUNDS
    return max(1, min(200, configured))


def local_cli_max_context_tokens() -> int:
    try:
        configured = int(
            os.getenv(
                "KNOWFLOW_CLI_MAX_CONTEXT_TOKENS",
                str(DEFAULT_LOCAL_MAX_CONTEXT_TOKENS),
            )
        )
    except ValueError:
        configured = DEFAULT_LOCAL_MAX_CONTEXT_TOKENS
    return max(8_000, min(1_000_000, configured))


def _public_event_value(value: Any, *, max_chars: int) -> Any:
    safe = sanitize_trace_value(value, max_chars=max_chars)
    if safe is None:
        return None
    try:
        parsed = json.loads(safe)
    except json.JSONDecodeError:
        return safe
    if isinstance(parsed, (dict, list)):
        return parsed
    return safe


def _xdg_path(environment_name: str, fallback: Path) -> Path:
    configured = os.getenv(environment_name, "").strip()
    return Path(configured).expanduser() if configured else fallback


def local_config_dir() -> Path:
    return _xdg_path(
        "XDG_CONFIG_HOME",
        Path.home() / ".config",
    ) / "knowflow"


def local_data_dir() -> Path:
    return _xdg_path(
        "XDG_DATA_HOME",
        Path.home() / ".local" / "share",
    ) / "knowflow"


class LocalCliConfigError(ValueError):
    pass


class LocalCliConfigStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or local_config_dir()).expanduser().resolve()
        self.config_path = self.root / "config.json"
        self.credentials_path = self.root / "credentials.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name != "nt":
            path.chmod(mode)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._chmod(self.root, 0o700)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._chmod(temporary, 0o600)
        temporary.replace(path)
        self._chmod(path, 0o600)

    def load_public(self) -> dict[str, Any]:
        return self._read_json(self.config_path)

    def load_credentials(self) -> dict[str, Any]:
        return self._read_json(self.credentials_path)

    def update_public(self, update: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        value = self.load_public()
        update(value)
        self._write_json(self.config_path, value)
        return value

    def update_credentials(
        self,
        update: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        value = self.load_credentials()
        update(value)
        self._write_json(self.credentials_path, value)
        return value

    def load(self) -> dict[str, Any]:
        public = self._read_json(self.config_path)
        credentials = self._read_json(self.credentials_path)
        values = {
            "provider": str(public.get("provider") or "custom"),
            "base_url": str(public.get("base_url") or ""),
            "model_name": str(public.get("model_name") or ""),
            "api_mode": str(public.get("api_mode") or "responses"),
            "api_key": str(credentials.get("api_key") or ""),
        }
        overrides = {
            "provider": "KNOWFLOW_PROVIDER",
            "base_url": "KNOWFLOW_API_BASE",
            "model_name": "KNOWFLOW_MODEL",
            "api_mode": "KNOWFLOW_API_MODE",
            "api_key": "KNOWFLOW_API_KEY",
        }
        for key, environment_name in overrides.items():
            value = os.getenv(environment_name, "").strip()
            if value:
                values[key] = value
        return values

    def save(
        self,
        *,
        provider: str,
        base_url: str,
        model_name: str,
        api_mode: str,
        api_key: str,
    ) -> None:
        config = validate_local_config(
            {
                "provider": provider,
                "base_url": base_url,
                "model_name": model_name,
                "api_mode": api_mode,
                "api_key": api_key,
            }
        )
        def update_public(value: dict[str, Any]) -> None:
            value.update(
                {
                    "provider": config["provider"],
                    "base_url": config["base_url"],
                    "model_name": config["model_name"],
                    "api_mode": config["api_mode"],
                }
            )

        def update_credentials(value: dict[str, Any]) -> None:
            value["api_key"] = config["api_key"]

        self.update_public(update_public)
        self.update_credentials(update_credentials)


def validate_local_config(value: dict[str, Any]) -> dict[str, str]:
    config = {
        "provider": str(value.get("provider") or "custom").strip(),
        "base_url": str(value.get("base_url") or "").strip().rstrip("/"),
        "model_name": str(value.get("model_name") or "").strip(),
        "api_mode": str(value.get("api_mode") or "responses").strip(),
        "api_key": str(value.get("api_key") or "").strip(),
    }
    missing = [
        name
        for name in ("base_url", "model_name", "api_key")
        if not config[name]
    ]
    if missing:
        raise LocalCliConfigError(
            "本地模型配置不完整，请先运行knowflow configure。"
        )
    if config["api_mode"] not in {"responses", "chat_completions"}:
        raise LocalCliConfigError(
            "接口协议必须是responses或chat_completions。"
        )
    parsed = urlparse(config["base_url"])
    is_loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    if parsed.scheme not in {"https", "http"} or (
        parsed.scheme == "http" and not is_loopback
    ):
        raise LocalCliConfigError(
            "接口地址必须使用HTTPS；仅本机地址允许HTTP。"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise LocalCliConfigError("接口地址格式无效。")
    return config


class _PlaintextCipher:
    @staticmethod
    def decrypt(value: Any) -> str:
        return str(value or "")


class LocalSessionStore:
    """Small, local-only session index; LangGraph remains execution state."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._chmod(self.root, 0o700)

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name != "nt":
            try:
                path.chmod(mode)
            except OSError:
                pass

    @staticmethod
    def _identifier(value: str) -> str:
        identifier = str(value or "")
        if not identifier.startswith("run_") or not identifier[4:].isalnum():
            raise ValueError("Invalid local session ID.")
        return identifier

    def _path(self, run_id: str) -> Path:
        return self.root / f"{self._identifier(run_id)}.json"

    def load(self, run_id: str) -> dict[str, Any] | None:
        path = self._path(run_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def save(self, run_id: str, **updates: Any) -> dict[str, Any]:
        path = self._path(run_id)
        payload = self.load(run_id) or {"runId": run_id, "createdAt": time.time()}
        payload.update(updates)
        payload["updatedAt"] = time.time()
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._chmod(temporary, 0o600)
        temporary.replace(path)
        self._chmod(path, 0o600)
        return payload

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        sessions: list[dict[str, Any]] = []
        for path in self.root.glob("run_*.json"):
            payload = self.load(path.stem)
            if payload is None:
                continue
            sessions.append(
                {
                    key: payload.get(key)
                    for key in (
                        "runId",
                        "title",
                        "status",
                        "updatedAt",
                        "projectRoot",
                        "cwd",
                        "answer",
                    )
                }
            )
        sessions.sort(key=lambda item: float(item.get("updatedAt") or 0), reverse=True)
        return sessions[: max(1, min(100, int(limit)))]


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]):
    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(10, 120),
    )


def _stream_json(url: str, headers: dict[str, str], payload: dict[str, Any]):
    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=(10, 120),
        stream=True,
    )


def _gateway() -> ModelGateway:
    return ModelGateway(
        fetch_one=lambda *_args, **_kwargs: None,
        cipher=_PlaintextCipher(),
        post_model_json=_post_json,
        stream_model_json=_stream_json,
        local_embedding=lambda _text: [],
    )


def gateway_config(value: dict[str, Any]) -> dict[str, Any]:
    config = validate_local_config(value)
    return {
        "provider": config["provider"],
        "base_url": config["base_url"],
        "model_name": config["model_name"],
        "api_mode": config["api_mode"],
        "api_key_cipher": config["api_key"],
        "model_type": "chat",
    }


def test_local_connection(value: dict[str, Any]) -> str:
    status, detail = _gateway().test(gateway_config(value))
    if status != "available":
        raise LocalCliConfigError(detail)
    return detail


class LocalAgentRuntime:
    def __init__(
        self,
        *,
        config_store: LocalCliConfigStore | None = None,
        workspace_root: Path | None = None,
        data_root: Path | None = None,
    ) -> None:
        self.config_store = config_store or LocalCliConfigStore()
        self.workspace_root = (workspace_root or Path.cwd()).resolve()
        self.data_root = (data_root or local_data_dir()).resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            self.data_root.chmod(0o700)
        self.gateway = _gateway()
        workspace_state = self.data_root / "workspace-state" / hashlib.sha256(
            str(self.workspace_root).encode("utf-8")
        ).hexdigest()[:16]
        self.workspace = WorkspaceContext(
            self.workspace_root,
            state_root=workspace_state,
        )
        self.sessions = LocalSessionStore(self.data_root / "sessions")
        self.extensions = LocalExtensionStore(
            self.config_store,
            self.data_root,
        )
        self.max_context_tokens = local_cli_max_context_tokens()
        self.engine = LangGraphAgentEngine(
            gateway=self.gateway,
            max_tool_rounds=local_cli_max_tool_rounds(),
            max_context_tokens=self.max_context_tokens,
            checkpoint_db_path=(
                self.data_root / "langgraph" / "checkpoints.sqlite3"
            ),
            allow_volatile_checkpoint=True,
        )
        self._cancel_lock = Lock()
        self._cancel_events: dict[str, Event] = {}

    def cancel(self, run_id: str | None = None) -> bool:
        """Cancel interruptible tools now and stop at the next graph boundary."""
        with self._cancel_lock:
            targets = (
                [self._cancel_events[run_id]]
                if run_id and run_id in self._cancel_events
                else (
                    list(self._cancel_events.values())
                    if not run_id
                    else []
                )
            )
        for target in targets:
            target.set()
        return bool(targets)

    def _workspace(self) -> WorkspaceRuntime:
        return WorkspaceRuntime(
            self.workspace_root,
            user_id=LOCAL_USER_ID,
            max_file_bytes=DEFAULT_MAX_FILE_BYTES,
            isolated_namespace=False,
            manage_root_permissions=False,
            context=self.workspace,
        )

    def workspace_status(self) -> dict[str, Any]:
        return self.workspace.status()

    def workspace_add_directory(self, path: str) -> dict[str, Any]:
        return self.workspace.add_directory(path)

    def workspace_change_directory(self, path: str) -> dict[str, Any]:
        return self.workspace.change_directory(path)

    def workspace_diff(self, path: str | None = None) -> dict[str, Any]:
        return self.workspace.diff(path or None)

    def workspace_undo(
        self,
        operation_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        result = (
            self.workspace.undo_file(
                operation_id=operation_id,
                run_id=run_id,
            )
            if operation_id and run_id
            else self.workspace.undo()
        )
        return {**result, "workspace": self.workspace.status()}

    def _session_workspace_fields(self) -> dict[str, Any]:
        return {
            "projectRoot": str(self.workspace.project_root),
            "cwd": str(self.workspace.cwd),
            "allowedDirectories": [
                str(path) for path in self.workspace.allowed_roots
            ],
        }

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        project = str(self.workspace.project_root)
        return [
            session
            for session in self.sessions.list(limit=limit * 3)
            if str(session.get("projectRoot") or "") == project
        ][:limit]

    def load_session(self, run_id: str) -> dict[str, Any]:
        session = self.sessions.load(run_id)
        if session is None:
            raise ValueError("Local session was not found.")
        if str(session.get("projectRoot") or "") != str(self.workspace.project_root):
            raise ValueError("This session belongs to a different workspace.")
        for directory in session.get("allowedDirectories") or []:
            path = str(directory or "").strip()
            if path and path != str(self.workspace.project_root):
                self.workspace.add_directory(path)
        cwd = str(session.get("cwd") or "")
        if cwd:
            self.workspace.change_directory(cwd)
        return session

    def branch_session(self, run_id: str, title: str = "") -> dict[str, Any]:
        source = self.load_session(run_id)
        if str(source.get("status") or "") not in {"completed", "cancelled"}:
            raise ValueError("请等待当前运行结束后再创建分支。")
        existing = self.list_sessions(limit=100)
        branch_title = unique_branch_title(
            str(source.get("title") or "新会话"),
            [str(item.get("title") or "") for item in existing],
            title,
            max_length=160,
        )
        branch_id = f"run_{uuid4().hex[:12]}"
        messages = list(source.get("messages") or [])
        context_messages = list(source.get("contextMessages") or messages)
        payload = self.sessions.save(
            branch_id,
            title=branch_title,
            status="completed",
            parentRunId=run_id,
            **self._session_workspace_fields(),
            messages=messages,
            contextMessages=context_messages,
            compaction=dict(source.get("compaction") or {}),
            answer=str(source.get("answer") or ""),
        )
        return payload

    def _registry(
        self,
        *,
        tools: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        mcp_pool: McpRunSessionPool | None = None,
    ) -> ToolRegistry:
        registry = ToolRegistry()
        register_user_question_tool(registry)
        if not tools:
            return registry
        workspace = self._workspace()
        sandbox = SrtSandboxRunner(workspace)
        register_workspace_tools(
            registry,
            workspace,
            sandbox=sandbox,
            progress_callback=progress_callback,
            cancel_check=cancel_check,
        )
        register_web_fetch_tool(
            registry,
            provider=PublicWebFetcher(cancel_check=cancel_check),
            cancel_check=cancel_check,
        )
        web = self.extensions.web_search()
        if web["enabled"] and web["configured"]:
            provider = TavilyWebSearch(
                api_key=str(web["api_key"]),
                post_json=lambda url, headers, payload, timeout: requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                ),
                timeout=20,
                max_results=10,
            )
            register_web_search_tool(
                registry,
                provider=provider,
                cancel_check=cancel_check,
            )
        if mcp_pool is not None:
            enabled_tools: list[dict[str, Any]] = []
            for server in self.extensions.list_mcp():
                if not server["enabled"] or server["status"] != "connected":
                    continue
                selected = set(server.get("enabledTools") or [])
                for item in server.get("tools") or []:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("modelName") or "") not in selected:
                        continue
                    enabled_tools.append(
                        {
                            **item,
                            "serverId": server["id"],
                            "serverName": server["name"],
                        }
                    )
            oauth = McpOAuthCoordinator(
                configs=self.extensions,
                base_url="http://127.0.0.1",
                allow_private=False,
            )

            def call_local_mcp(item: dict[str, Any], args: dict[str, Any], _safe_read: bool):
                server_id = str(item["serverId"])
                remote_name = str(item.get("remoteName") or item.get("name"))
                try:
                    return mcp_pool.call_tool(server_id, remote_name, args)
                except Exception as exc:
                    marker = f"{getattr(exc, 'code', '')} {exc}".lower()
                    if "401" not in marker and "unauthorized" not in marker:
                        raise
                    oauth.ensure_access_token(
                        LOCAL_USER_ID,
                        server_id,
                        force_refresh=True,
                    )
                    mcp_pool.invalidate(server_id)
                    return mcp_pool.call_tool(server_id, remote_name, args)

            register_mcp_tools(
                registry,
                tools=enabled_tools[:MCP_MAX_EXPOSED_TOOLS],
                max_tools=MCP_MAX_EXPOSED_TOOLS,
                call_tool=call_local_mcp,
            )
        return registry

    def sandbox_diagnostics(self, *, smoke: bool = True) -> list[dict[str, Any]]:
        return [
            self.engine.checkpoint_diagnostic(),
            *SrtSandboxRunner(self._workspace()).diagnostics(smoke=smoke),
        ]

    def run_shell_command(
        self,
        command: str,
        *,
        event_sink: AgentEventSink | None = None,
        timeout_seconds: int = 120,
    ) -> AgentExecution:
        """Run an explicit user shell command through the existing SRT boundary."""
        arguments = RunSandboxCommandArguments(
            command=str(command or "").strip(),
            timeout_seconds=timeout_seconds,
        )
        identifier = f"shell_{uuid4().hex[:12]}"
        tool_call_id = f"shell_call_{uuid4().hex[:12]}"
        events: list[dict[str, Any]] = []
        normalize_event = AgentEventNormalizer(identifier)
        cancel_event = Event()
        with self._cancel_lock:
            self._cancel_events[identifier] = cancel_event
        self.workspace.begin_turn(identifier)

        def emit(event: dict[str, Any]) -> None:
            normalized = normalize_event(event)
            if (
                normalized.get("type") == "tool_progress"
                and events
                and events[-1].get("type") == "tool_progress"
                and events[-1].get("toolCallId") == tool_call_id
            ):
                events[-1] = normalized
            else:
                events.append(normalized)
            if event_sink is not None:
                event_sink(normalized)

        def progress(value: dict[str, Any]) -> None:
            emit(
                {
                    "type": "tool_progress",
                    "runId": identifier,
                    "toolCallId": tool_call_id,
                    "toolName": "run_sandbox_command",
                    "status": "running",
                    "output": _public_event_value(value.get("output"), max_chars=4_000),
                    "stdout": _public_event_value(value.get("stdout"), max_chars=2_000),
                    "stderr": _public_event_value(value.get("stderr"), max_chars=2_000),
                    "elapsedSeconds": value.get("elapsedSeconds"),
                    "totalLines": value.get("totalLines"),
                    "totalBytes": value.get("totalBytes"),
                    "timeoutSeconds": value.get("timeoutSeconds"),
                }
            )

        emit(
            {
                "type": "run_started",
                "runId": identifier,
                "goalSummary": f"! {arguments.command}"[:160],
            }
        )
        emit(
            {
                "type": "tool_started",
                "runId": identifier,
                "toolCallId": tool_call_id,
                "toolName": "run_sandbox_command",
                "status": "running",
                "arguments": {"command": arguments.command},
            }
        )
        try:
            result = SrtSandboxRunner(self._workspace()).run(
                arguments.command,
                timeout_seconds=arguments.timeout_seconds,
                progress_callback=progress,
                cancel_check=cancel_event.is_set,
            )
            output = result.__dict__
            status = (
                "cancelled"
                if result.cancelled
                else "failed"
                if result.timed_out or result.exit_code != 0
                else "success"
            )
            error_code = (
                "tool_cancelled"
                if result.cancelled
                else "tool_timeout"
                if result.timed_out
                else "shell_exit_nonzero"
                if result.exit_code != 0
                else None
            )
            emit(
                {
                    "type": "tool_result",
                    "runId": identifier,
                    "toolCallId": tool_call_id,
                    "toolName": "run_sandbox_command",
                    "status": status,
                    "errorCode": error_code,
                    "latencyMs": round(result.elapsed_seconds * 1_000),
                    "arguments": {"command": arguments.command},
                    "output": _public_event_value(output, max_chars=20_000),
                    "errorMessage": _public_event_value(
                        result.stderr if status == "failed" else "",
                        max_chars=1_000,
                    ),
                }
            )
            if status == "failed":
                reason = str(
                    _public_event_value(
                        result.stderr or result.stdout or f"退出码{result.exit_code}",
                        max_chars=1_000,
                    )
                    or f"退出码{result.exit_code}"
                )
                raise RuntimeError(f"Shell命令执行失败：{reason}")
            answer = str(
                _public_event_value(
                    result.stdout or result.stderr,
                    max_chars=20_000,
                )
                or ""
            )
            emit(
                {
                    "type": "done",
                    "runId": identifier,
                    "status": "cancelled" if result.cancelled else "completed",
                }
            )
            return AgentExecution(
                result={
                    "paused": False,
                    "cancelled": result.cancelled,
                    "runId": identifier,
                    "answer": answer,
                    "trace": [],
                    "messages": [],
                    "transcriptMessages": [],
                    "compaction": {},
                },
                events=events,
            )
        finally:
            with self._cancel_lock:
                current = self._cancel_events.get(identifier)
                if current is cancel_event:
                    self._cancel_events.pop(identifier, None)

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return the public tool catalog used by local interactive clients."""
        with self._mcp_pool() as pool:
            registry = self._registry(tools=True, mcp_pool=pool)
            return registry.schemas(engine_name="langgraph")

    def capability_status(self) -> dict[str, Any]:
        status = self.extensions.capability_status()
        try:
            schemas = self.tool_schemas()
        except Exception:
            schemas = []
        status["tools"] = {
            "count": len(schemas),
            "items": [
                {
                    "name": str((schema.get("function") or {}).get("name") or ""),
                    "description": str(
                        (schema.get("function") or {}).get("description") or ""
                    ),
                }
                for schema in schemas
                if str((schema.get("function") or {}).get("name") or "")
            ],
        }
        memory = dict(status.get("memory") or {})
        memory["items"] = []
        if memory.get("configured") and memory.get("enabled"):
            try:
                provider = self.extensions.memory_provider()
                if provider is not None:
                    memory["items"] = provider.list(
                        user_id=LOCAL_USER_ID,
                        limit=10,
                    )
            except Exception:
                memory["error"] = "memory_unavailable"
        status["memory"] = memory
        return status

    def context_status(
        self,
        messages: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return context_status(
            list(messages or []),
            max_tokens=self.max_context_tokens,
        )

    def compact_context(
        self,
        messages: list[dict[str, Any]],
        *,
        instructions: str = "",
        reason: str = "manual",
    ) -> dict[str, Any]:
        config = gateway_config(self.config_store.load())
        result = compact_context(
            list(messages or []),
            gateway=self.gateway,
            config=config,
            max_tokens=self.max_context_tokens,
            custom_instructions=instructions,
            reason=reason,
        )
        status = context_status(
            result.messages,
            max_tokens=self.max_context_tokens,
        )
        return {
            "messages": result.messages,
            "metadata": result.metadata,
            "compacted": result.compacted,
            "reason": result.reason,
            "status": status,
        }

    def save_context_state(
        self,
        run_id: str,
        *,
        messages: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> None:
        self.load_session(run_id)
        self.sessions.save(
            run_id,
            contextMessages=list(messages or []),
            compaction=dict(metadata or {}),
        )

    def _mcp_pool(self) -> McpRunSessionPool:
        return McpRunSessionPool(
            server_loader=lambda server_id: self.extensions.secret(
                LOCAL_USER_ID,
                server_id,
            ),
            allow_private=False,
            connect_timeout=10,
            request_timeout=30,
        )

    @staticmethod
    def _system_message(workspace: WorkspaceContext | Path) -> dict[str, str]:
        if isinstance(workspace, WorkspaceContext):
            project_root = workspace.project_root
            cwd = workspace.cwd
            allowed_roots = workspace.allowed_roots
        else:
            project_root = Path(workspace).expanduser().resolve()
            cwd = project_root
            allowed_roots = [project_root]
        allowed = ", ".join(str(path) for path in allowed_roots)
        return {
            "role": "system",
            "content": (
                "You are AgentLens, a local Linux coding agent. Work only "
                f"inside this workspace: {project_root}. The current "
                f"directory is {cwd}. Allowed working directories: {allowed}. Inspect before "
                "editing, use tools when needed, and report results concisely. "
                "Use web_fetch for a specific URL and web_search to discover "
                "URLs. Never turn a failed search or fetch into unsupported "
                "claims about availability, indexing, SEO, or page quality. "
                "When a consequential requirement is genuinely missing, use "
                "ask_user_question with 2 to 4 concise options instead of guessing."
            ),
        }

    def run(
        self,
        task: str,
        *,
        history: list[dict[str, Any]] | None = None,
        transcript: list[dict[str, Any]] | None = None,
        context_metadata: dict[str, Any] | None = None,
        tools: bool = True,
        reasoning_effort: str = "default",
        run_id: str | None = None,
        approval_decision: str | None = None,
        resume_value: Any = None,
        resume_from_checkpoint: bool = False,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        config = {
            **gateway_config(self.config_store.load()),
            "reasoning_effort": reasoning_effort,
        }
        identifier = run_id or f"run_{uuid4().hex[:12]}"
        messages = list(history or [])
        if not messages:
            messages.append(self._system_message(self.workspace))
        elif messages[0].get("role") == "system":
            messages[0] = self._system_message(self.workspace)
        transcript_messages = list(transcript if transcript is not None else messages)
        if not transcript_messages:
            transcript_messages.append(self._system_message(self.workspace))
        elif transcript_messages[0].get("role") == "system":
            transcript_messages[0] = self._system_message(self.workspace)
        workspace_references = extract_workspace_references(task) if task else ()
        workspace_reference_bundle = None
        if task:
            messages.append({"role": "user", "content": task})
            transcript_messages.append({"role": "user", "content": task})
        memory_task = task or next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        events: list[dict[str, Any]] = []
        normalize_event = AgentEventNormalizer(identifier)
        cancel_event = Event()
        with self._cancel_lock:
            self._cancel_events[identifier] = cancel_event
        self.workspace.begin_turn(identifier)
        title = memory_task.strip().splitlines()[0][:80] if memory_task.strip() else identifier
        self.sessions.save(
            identifier,
            title=title,
            status="running",
            **self._session_workspace_fields(),
            messages=transcript_messages,
            contextMessages=messages,
            compaction=dict(context_metadata or {}),
        )

        def emit(event: dict[str, Any]) -> None:
            event = normalize_event(event)
            if (
                event.get("type") == "tool_progress"
                and events
                and events[-1].get("type") == "tool_progress"
                and events[-1].get("toolCallId") == event.get("toolCallId")
            ):
                events[-1] = event
            else:
                events.append(event)
            if event_sink is not None:
                event_sink(event)

        def model_event(event: dict[str, Any]) -> None:
            emit({"type": "model_event", **event})

        trace = AgentTraceRecorder(
            emit=lambda event: emit({"type": "agent_step", **event}),
            run_id=identifier,
        )

        active_tool: dict[str, str] = {}

        def tool_lifecycle_event(event: dict[str, Any]) -> None:
            if (
                event.get("type") == "tool_started"
                and event.get("status") == "running"
            ):
                active_tool["call_id"] = str(event.get("toolCallId") or "")
                active_tool["name"] = str(event.get("toolName") or "")
            emit(
                {
                    **event,
                    "arguments": _public_event_value(
                        event.get("arguments"),
                        max_chars=500,
                    ),
                }
            )

        def tool_progress_event(progress: dict[str, Any]) -> None:
            public_progress = {
                "output": _public_event_value(
                    progress.get("output"),
                    max_chars=4_000,
                ),
                "stdout": _public_event_value(
                    progress.get("stdout"),
                    max_chars=2_000,
                ),
                "stderr": _public_event_value(
                    progress.get("stderr"),
                    max_chars=2_000,
                ),
                "elapsedSeconds": progress.get("elapsedSeconds"),
                "totalLines": progress.get("totalLines"),
                "totalBytes": progress.get("totalBytes"),
                "timeoutSeconds": progress.get("timeoutSeconds"),
            }
            emit(
                {
                    "type": "tool_progress",
                    "runId": identifier,
                    "toolCallId": active_tool.get("call_id") or "",
                    "toolName": active_tool.get("name") or "run_sandbox_command",
                    "status": "running",
                    **public_progress,
                }
            )

        def tool_event(execution: ToolExecution, _parent: str | None) -> None:
            output = execution.public_output()
            cancelled = bool(
                isinstance(output, dict) and output.get("cancelled")
            )
            timed_out = bool(
                isinstance(output, dict) and output.get("timed_out")
            )
            public_status = (
                "cancelled"
                if cancelled
                else "failed" if timed_out else execution.status
            )
            emit(
                {
                    "type": "tool_result",
                    "toolCallId": execution.call_id,
                    "toolName": execution.tool_name,
                    "status": public_status,
                    "errorCode": (
                        "tool_cancelled"
                        if cancelled
                        else "tool_timeout" if timed_out else execution.error_code
                    ),
                    "latencyMs": execution.latency_ms,
                    "arguments": _public_event_value(
                        execution.arguments,
                        max_chars=500,
                    ),
                    "output": _public_event_value(
                        output,
                        max_chars=4_000,
                    ),
                    "errorMessage": _public_event_value(
                        execution.error_message,
                        max_chars=500,
                    ),
                }
            )
            artifact = artifact_event_from_tool_execution(
                tool_name=execution.tool_name,
                status=execution.status,
                output=output,
                tool_call_id=execution.call_id,
            )
            if artifact is not None:
                emit(artifact)

        memory_provider = self.extensions.memory_provider()
        emit({
            "type": "run_started",
            "runId": identifier,
            "goalSummary": title,
        })
        if workspace_references:
            reference_step = trace.start_step(
                kind="workspace",
                name="workspace_references",
                title="正在读取工作区文件",
                input_summary={
                    "files": [
                        item.label
                        for item in workspace_references
                    ],
                },
            )
            workspace_reference_bundle = load_workspace_references(
                task,
                self._workspace(),
            )
            if workspace_reference_bundle.context_message:
                messages.insert(
                    max(1, len(messages) - 1),
                    {
                        "role": "user",
                        "content": workspace_reference_bundle.context_message,
                    },
                )
                self.sessions.save(
                    identifier,
                    **self._session_workspace_fields(),
                    messages=transcript_messages,
                    contextMessages=messages,
                    compaction=dict(context_metadata or {}),
                )
            trace.finish_step(
                reference_step,
                status="success",
                title=workspace_reference_trace_title(
                    workspace_reference_bundle
                ),
                output_summary=workspace_reference_bundle.public_summary(),
            )
        try:
            with self._mcp_pool() as mcp_pool:
                registry = self._registry(
                    tools=tools,
                    progress_callback=tool_progress_event,
                    cancel_check=cancel_event.is_set,
                    mcp_pool=mcp_pool,
                )
                available_skill_dependencies = set(registry.names())
                available_skill_dependencies.update(
                    str(server.get("slug") or "")
                    for server in self.extensions.list_mcp()
                    if server.get("enabled")
                    and server.get("status") == "connected"
                    and server.get("slug")
                )
                activation = SkillActivationSession(
                    store=self.extensions,
                    user_id=LOCAL_USER_ID,
                    available_tools=available_skill_dependencies,
                )
                catalog = activation.catalog() if tools else []
                if catalog:
                    activation.register_activation_tool(registry)
                    if approval_decision is None:
                        messages[0]["content"] += (
                            "\nAvailable Skills (activate at most one with activate_skill): "
                            + json.dumps(catalog, ensure_ascii=False)
                        )

                def restore_skill(snapshot: dict[str, Any]) -> None:
                    activation.restore(snapshot)
                    activation.register_read_resource(registry)
                    registry.unregister("activate_skill")

                result = self.engine.run(
                    user_id=LOCAL_USER_ID,
                    run_id=identifier,
                    messages=messages,
                    config=config,
                    registry=registry,
                    trace=trace,
                    execution_callback=tool_event,
                    model_event_callback=model_event,
                    tool_event_callback=tool_lifecycle_event,
                    cancel_check=cancel_event.is_set,
                    resume_from_checkpoint=(
                        resume_from_checkpoint
                        or approval_decision is not None
                        or resume_value is not None
                    ),
                    approval_decision=approval_decision,
                    resume_value=resume_value,
                    skill_restore=restore_skill,
                    memory_enabled=memory_provider is not None,
                    memory_recall=(
                        lambda: memory_provider.search(
                            user_id=LOCAL_USER_ID,
                            query=memory_task,
                            limit=5,
                        )
                        if memory_provider is not None
                        else None
                    ),
                )
        except AgentRunCancelledError:
            self.sessions.save(
                identifier,
                status="cancelled",
                **self._session_workspace_fields(),
                messages=transcript_messages,
                contextMessages=messages,
                compaction=dict(context_metadata or {}),
            )
            emit(
                {
                    "type": "done",
                    "runId": identifier,
                    "status": "cancelled",
                }
            )
            return AgentExecution(
                result={
                    "paused": False,
                    "cancelled": True,
                    "runId": identifier,
                    "answer": "",
                    "trace": [],
                    "messages": messages,
                    "transcriptMessages": transcript_messages,
                    "compaction": dict(context_metadata or {}),
                },
                events=events,
            )
        except Exception as exc:
            self.sessions.save(
                identifier,
                status="failed",
                errorCode=type(exc).__name__,
                **self._session_workspace_fields(),
                messages=transcript_messages,
                contextMessages=messages,
                compaction=dict(context_metadata or {}),
            )
            raise
        finally:
            with self._cancel_lock:
                current = self._cancel_events.get(identifier)
                if current is cancel_event:
                    self._cancel_events.pop(identifier, None)
        if result.paused:
            interrupt = result.interrupt or {}
            tool_call_id = str(
                interrupt.get("toolCallId") or uuid4().hex
            )
            if interrupt.get("type") == "user_question":
                question_event = {
                    "type": "user_question_required",
                    "questionId": str(
                        interrupt.get("questionId") or tool_call_id
                    ),
                    "toolCallId": tool_call_id,
                    "runId": identifier,
                    "header": interrupt.get("header") or "需要确认",
                    "question": interrupt.get("question") or "请选择下一步。",
                    "options": interrupt.get("options") or [],
                    "allowCustom": bool(interrupt.get("allowCustom", True)),
                }
                emit(question_event)
                self.sessions.save(
                    identifier,
                    status="waiting_input",
                    **self._session_workspace_fields(),
                    messages=transcript_messages,
                    contextMessages=messages,
                    compaction=dict(context_metadata or {}),
                    pendingQuestion=question_event,
                    pendingApproval=None,
                )
            else:
                emit(
                    {
                        "type": "approval_required",
                        "approvalId": tool_call_id,
                        "toolCallId": tool_call_id,
                        "runId": identifier,
                        "toolName": interrupt.get("toolName") or "工具调用",
                        "serverName": interrupt.get("serverName") or "本地工具",
                        "risk": interrupt.get("risk") or "unknown",
                        "readOnly": bool(interrupt.get("readOnly")),
                        "destructive": bool(interrupt.get("destructive")),
                        "inputSummary": interrupt.get("inputSummary"),
                    }
                )
                self.sessions.save(
                    identifier,
                    status="waiting_approval",
                    **self._session_workspace_fields(),
                    messages=transcript_messages,
                    contextMessages=messages,
                    compaction=dict(context_metadata or {}),
                    pendingApproval={
                        "approvalId": tool_call_id,
                        "toolName": interrupt.get("toolName") or "工具调用",
                        "risk": interrupt.get("risk") or "unknown",
                    },
                    pendingQuestion=None,
                )
        else:
            if memory_provider is not None and memory_task and result.answer:
                emit(
                    {
                        "type": "memory_started",
                        "runId": identifier,
                        "status": "running",
                    }
                )
                try:
                    remembered = memory_provider.remember(
                        user_id=LOCAL_USER_ID,
                        messages=[
                            {"role": "user", "content": memory_task},
                            {"role": "assistant", "content": result.answer},
                        ],
                        metadata={"session_id": identifier},
                    )
                except Exception as exc:
                    emit(
                        {
                            "type": "memory_result",
                            "runId": identifier,
                            "status": "failed",
                            "errorCode": type(exc).__name__,
                        }
                    )
                else:
                    emit(
                        {
                            "type": "memory_result",
                            "runId": identifier,
                            "status": "success",
                            "count": len(remembered),
                        }
                    )
            emit({"type": "done", "runId": identifier})
            stored_messages = list(messages)
            stored_transcript = list(transcript_messages)
            if result.answer:
                stored_messages.append({"role": "assistant", "content": result.answer})
                stored_transcript.append(
                    {"role": "assistant", "content": result.answer}
                )
            self.sessions.save(
                identifier,
                status="completed",
                answer=result.answer,
                messages=stored_transcript,
                contextMessages=stored_messages,
                compaction=dict(context_metadata or {}),
                pendingApproval=None,
                pendingQuestion=None,
                **self._session_workspace_fields(),
                changes=self.workspace.diff(run_id=identifier).get("files", []),
            )
        return AgentExecution(
            result={
                "paused": result.paused,
                "runId": identifier,
                "answer": result.answer,
                "trace": result.trace,
                "messages": messages,
                "transcriptMessages": transcript_messages,
                "compaction": dict(context_metadata or {}),
            },
            events=events,
        )

    def resume_session(
        self,
        run_id: str,
        *,
        approval_decision: str | None = None,
        resume_value: Any = None,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        session = self.load_session(run_id)
        status = str(session.get("status") or "")
        if status == "completed":
            return AgentExecution(
                result={
                    "paused": False,
                    "runId": run_id,
                    "answer": "",
                    "messages": list(
                        session.get("contextMessages")
                        or session.get("messages")
                        or []
                    ),
                    "transcriptMessages": list(
                        session.get("messages") or []
                    ),
                    "compaction": dict(session.get("compaction") or {}),
                    "restored": True,
                },
                events=[],
            )
        if status not in {
            "failed", "interrupted", "waiting_approval", "waiting_input",
            "cancelled", "running",
        }:
            raise ValueError("This local session cannot be resumed.")
        return self.run(
            "",
            history=list(
                session.get("contextMessages")
                or session.get("messages")
                or []
            ),
            transcript=list(session.get("messages") or []),
            context_metadata=dict(session.get("compaction") or {}),
            run_id=run_id,
            approval_decision=approval_decision,
            resume_value=resume_value,
            resume_from_checkpoint=True,
            event_sink=event_sink,
        )
