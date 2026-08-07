from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

import requests

from .agent_execution import AgentExecution, AgentEventSink
from .agent_loop import ToolExecution, ToolRegistry
from .agent_trace import sanitize_trace_value
from .langgraph_agent_engine import LangGraphAgentEngine
from .model_gateway import ModelGateway
from .workspace_runtime import (
    SrtSandboxRunner,
    WorkspaceRuntime,
    register_workspace_tools,
)


LOCAL_USER_ID = 1
DEFAULT_MAX_FILE_BYTES = 2_000_000


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
        self._write_json(
            self.config_path,
            {
                "provider": config["provider"],
                "base_url": config["base_url"],
                "model_name": config["model_name"],
                "api_mode": config["api_mode"],
            },
        )
        self._write_json(
            self.credentials_path,
            {"api_key": config["api_key"]},
        )


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
    return requests.post(url, headers=headers, json=payload, timeout=120)


def _stream_json(url: str, headers: dict[str, str], payload: dict[str, Any]):
    return requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
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
        self.engine = LangGraphAgentEngine(
            gateway=self.gateway,
            checkpoint_db_path=(
                self.data_root / "langgraph" / "checkpoints.sqlite3"
            ),
        )

    def _registry(self, *, tools: bool) -> ToolRegistry:
        registry = ToolRegistry()
        if not tools:
            return registry
        workspace = WorkspaceRuntime(
            self.workspace_root,
            user_id=LOCAL_USER_ID,
            max_file_bytes=DEFAULT_MAX_FILE_BYTES,
            isolated_namespace=False,
            manage_root_permissions=False,
        )
        sandbox = SrtSandboxRunner(workspace)
        register_workspace_tools(registry, workspace, sandbox=sandbox)
        return registry

    def tool_schemas(self) -> list[dict[str, Any]]:
        """Return the public tool catalog used by local interactive clients."""
        return self._registry(tools=True).schemas(engine_name="langgraph")

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
        events: list[dict[str, Any]] = []

        def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event_sink is not None:
                event_sink(event)

        def model_event(event: dict[str, Any]) -> None:
            emit({"type": "model_event", **event})

        def tool_event(execution: ToolExecution, _parent: str | None) -> None:
            emit(
                {
                    "type": "tool_result",
                    "toolCallId": execution.call_id,
                    "toolName": execution.tool_name,
                    "status": execution.status,
                    "latencyMs": execution.latency_ms,
                    "arguments": sanitize_trace_value(
                        execution.arguments,
                        max_chars=500,
                    ),
                    "output": sanitize_trace_value(
                        execution.public_output(),
                        max_chars=1000,
                    ),
                    "errorMessage": sanitize_trace_value(
                        execution.error_message,
                        max_chars=500,
                    ),
                }
            )

        result = self.engine.run(
            user_id=LOCAL_USER_ID,
            run_id=identifier,
            messages=messages,
            config=config,
            registry=self._registry(tools=tools),
            execution_callback=tool_event,
            model_event_callback=model_event,
            resume_from_checkpoint=approval_decision is not None,
            approval_decision=approval_decision,
        )
        if result.paused:
            interrupt = result.interrupt or {}
            emit(
                {
                    "type": "approval_required",
                    "approvalId": str(
                        interrupt.get("toolCallId") or uuid4().hex
                    ),
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
