from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event, Lock
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

import requests

from .agent_execution import AgentExecution, AgentEventSink
from .agent_loop import ToolExecution, ToolRegistry
from .agent_tooling import register_mcp_tools, register_web_search_tool
from .agent_trace import sanitize_trace_value
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
from .web_search import TavilyWebSearch
from .workspace_runtime import (
    SrtSandboxRunner,
    WorkspaceRuntime,
    register_workspace_tools,
)


LOCAL_USER_ID = 1
DEFAULT_MAX_FILE_BYTES = 2_000_000
DEFAULT_LOCAL_MAX_TOOL_ROUNDS = 50


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
        self.extensions = LocalExtensionStore(
            self.config_store,
            self.data_root,
        )
        self.engine = LangGraphAgentEngine(
            gateway=self.gateway,
            max_tool_rounds=local_cli_max_tool_rounds(),
            checkpoint_db_path=(
                self.data_root / "langgraph" / "checkpoints.sqlite3"
            ),
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
        )

    def _registry(
        self,
        *,
        tools: bool,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        mcp_pool: McpRunSessionPool | None = None,
    ) -> ToolRegistry:
        registry = ToolRegistry()
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
        return SrtSandboxRunner(self._workspace()).diagnostics(smoke=smoke)

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return the public tool catalog used by local interactive clients."""
        with self._mcp_pool() as pool:
            registry = self._registry(tools=True, mcp_pool=pool)
            return registry.schemas(engine_name="langgraph")

    def capability_status(self) -> dict[str, Any]:
        return self.extensions.capability_status()

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
    def _system_message(workspace_root: Path) -> dict[str, str]:
        return {
            "role": "system",
            "content": (
                "You are KnowFlow, a local Linux coding agent. Work only "
                f"inside this workspace: {workspace_root}. Inspect before "
                "editing, use tools when needed, and report results concisely."
            ),
        }

    def run(
        self,
        task: str,
        *,
        history: list[dict[str, Any]] | None = None,
        tools: bool = True,
        run_id: str | None = None,
        approval_decision: str | None = None,
        event_sink: AgentEventSink | None = None,
    ) -> AgentExecution:
        config = gateway_config(self.config_store.load())
        identifier = run_id or f"run_{uuid4().hex[:12]}"
        messages = list(history or [])
        if not messages:
            messages.append(self._system_message(self.workspace_root))
        if task:
            messages.append({"role": "user", "content": task})
        memory_task = task or next(
            (
                str(message.get("content") or "")
                for message in reversed(messages)
                if message.get("role") == "user"
            ),
            "",
        )
        events: list[dict[str, Any]] = []
        cancel_event = Event()
        with self._cancel_lock:
            self._cancel_events[identifier] = cancel_event

        def emit(event: dict[str, Any]) -> None:
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

        memory_provider = self.extensions.memory_provider()
        emit({"type": "run_started", "runId": identifier})
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
                    execution_callback=tool_event,
                    model_event_callback=model_event,
                    tool_event_callback=tool_lifecycle_event,
                    cancel_check=cancel_event.is_set,
                    resume_from_checkpoint=approval_decision is not None,
                    approval_decision=approval_decision,
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
                },
                events=events,
            )
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
        return AgentExecution(
            result={
                "paused": result.paused,
                "runId": identifier,
                "answer": result.answer,
                "trace": result.trace,
                "messages": messages,
            },
            events=events,
        )
