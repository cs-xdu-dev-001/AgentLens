from __future__ import annotations

from contextlib import contextmanager, nullcontext
from importlib.metadata import PackageNotFoundError, version
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any, Iterator
import webbrowser

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
import typer

from .services.agent_execution import AgentExecution
from .services.remote_agent import (
    RemoteAgentClient,
    RemoteAgentError,
    RemoteProfileStore,
    normalize_server_url,
)

if TYPE_CHECKING:
    from .services.agent_application import AgentApplicationService


app = typer.Typer(
    name="knowflow",
    help="KnowFlow AI Linux Agent CLI",
    no_args_is_help=True,
)
tools_app = typer.Typer(help="Inspect Agent tools.")
skills_app = typer.Typer(help="Inspect installed Skills.")
mcp_app = typer.Typer(help="Inspect MCP servers.")
memory_app = typer.Typer(help="Inspect long-term memory.")
auth_app = typer.Typer(help="Manage remote CLI authentication.")
models_app = typer.Typer(help="Inspect configured chat models.")
app.add_typer(tools_app, name="tools")
app.add_typer(skills_app, name="skills")
app.add_typer(mcp_app, name="mcp")
app.add_typer(memory_app, name="memory")
app.add_typer(auth_app, name="auth")
app.add_typer(models_app, name="models")

console = Console()
error_console = Console(stderr=True)
profile_store = RemoteProfileStore()

DEFAULT_CLI_PACKAGE_SPEC = (
    "git+https://github.com/cs-xdu-dev-001/KnowFlow-AI.git#subdirectory=backend"
)


def _version_callback(value: bool) -> None:
    if not value:
        return
    try:
        package_version = version("knowflow-ai")
    except PackageNotFoundError:
        package_version = "development"
    typer.echo(package_version)
    raise typer.Exit()


def _installed_cli_version() -> str:
    try:
        return version("knowflow-ai")
    except PackageNotFoundError:
        return "development"


def _pipx_command() -> list[str] | None:
    executable = shutil.which("pipx")
    if executable:
        return [executable]
    data_home = Path(
        os.getenv("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    )
    bundled = data_home / "knowflow-ai" / "pipx" / "bin" / "pipx"
    if bundled.is_file():
        return [str(bundled)]
    return None


def _cli_update_command() -> list[str]:
    pipx = _pipx_command()
    if pipx is None:
        raise RuntimeError(
            "未找到pipx。请重新运行官网安装命令完成升级。"
        )
    package_spec = (
        os.getenv("KNOWFLOW_CLI_SPEC", "").strip()
        or DEFAULT_CLI_PACKAGE_SPEC
    )
    return [*pipx, "install", "--force", package_spec]


@app.callback()
def root_options(
    show_version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed KnowFlow CLI version.",
    ),
) -> None:
    """KnowFlow AI Linux Agent CLI."""


def _remote_client(
    server: str | None,
    *,
    local: bool,
    remote: bool | None = None,
) -> RemoteAgentClient | None:
    if local:
        if server or remote:
            raise typer.BadParameter(
                "--local不能与--remote或--server同时使用。"
            )
        return None
    if remote is False and not server:
        return None
    profile = profile_store.load()
    requested = server or os.getenv("KNOWFLOW_CLI_SERVER", "").strip()
    if requested:
        requested = normalize_server_url(requested)
        if not profile or profile.get("server") != requested:
            raise typer.BadParameter(
                "该服务器尚未登录，请先执行knowflow auth login。"
            )
    elif profile:
        requested = str(profile["server"])
    if not requested:
        raise typer.BadParameter(
            "尚未登录远程服务器，请先执行knowflow auth login <服务器地址>；"
            "本地直连请显式使用--local。"
        )
    if not profile or not profile.get("token"):
        raise typer.BadParameter("远程登录已失效，请重新登录。")
    return RemoteAgentClient(
        requested,
        token=str(profile["token"]),
    )


def _local_agent():
    from .services.local_cli_runtime import LocalAgentRuntime

    return LocalAgentRuntime()


def _local_approval_loop(
    execution: AgentExecution,
    *,
    agent,
    renderer: "EventRenderer",
    assume_yes: bool,
) -> AgentExecution:
    current = execution
    while current.paused:
        run_id = str(current.result.get("runId") or "")
        if not run_id:
            raise RuntimeError("Agent暂停，但运行信息不完整。")
        allowed = assume_yes or typer.confirm("允许本次工具调用？")
        current = agent.run(
            "",
            history=list(current.result.get("messages") or []),
            run_id=run_id,
            approval_decision="allow_once" if allowed else "deny",
            event_sink=renderer,
        )
    return current


def _remote_payload(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _remote_approval_loop(
    execution: AgentExecution,
    *,
    client: RemoteAgentClient,
    renderer: "EventRenderer",
    assume_yes: bool,
) -> AgentExecution:
    current = execution
    while current.paused:
        approval_id = current.approval_id
        run_id = str(current.result.get("runId") or "")
        if not approval_id or not run_id:
            raise RemoteAgentError(
                "approval_unavailable",
                "Agent等待审批，但审批信息不可用。",
            )
        allowed = assume_yes or typer.confirm("允许本次工具调用？")
        current = client.resolve_approval(
            run_id,
            approval_id,
            "allow_once" if allowed else "deny",
            renderer,
        )
    return current


def _runtime():
    from . import runtime

    return runtime


def _application() -> AgentApplicationService:
    from .services.agent_application import AgentApplicationService
    from .routers.extensions import (
        execute_agent_chat,
        execute_persisted_agent_run,
    )

    runtime = _runtime()
    return AgentApplicationService(
        execute_agent=execute_agent_chat,
        execute_persisted=execute_persisted_agent_run,
        approval_store=runtime.agent_tool_operations,
        run_store=runtime.agent_runs,
    )


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, default=str))


def _failure_payload(exc: Exception) -> dict[str, str]:
    if isinstance(exc, RemoteAgentError):
        return {"error": exc.code, "message": str(exc)}
    if type(exc).__name__ == "LocalCliConfigError":
        return {
            "error": "local_cli_configuration_invalid",
            "message": str(exc),
        }
    from .services.agent_failure import classify_agent_failure

    failure = classify_agent_failure(exc)
    return {
        "error": str(failure["code"]),
        "message": str(failure["summary"]),
    }


class EventRenderer:
    def __init__(self, *, json_events: bool):
        self.json_events = json_events
        self.streamed_text = False

    def __call__(self, event: dict[str, Any]) -> None:
        if self.json_events:
            _emit_json(event)
            return
        if event.get("type") == "text_delta":
            text_value = str(event.get("text") or "")
            if text_value:
                console.print(text_value, end="", markup=False)
                self.streamed_text = True
        elif event.get("type") == "approval_required":
            console.print(
                "[yellow]需要确认：[/yellow]"
                f"{event.get('toolName') or '工具调用'}"
            )
        elif event.get("type") == "agent_step":
            step = event.get("step") or event
            status = str(step.get("status") or "")
            if status in {"success", "failed", "waiting"}:
                title = step.get("title") or step.get("name") or "Agent步骤"
                console.print(f"[dim]{title} · {status}[/dim]")


def _resolve_user_id(explicit: int | None) -> int:
    runtime = _runtime()
    configured = explicit
    if configured is None:
        raw = os.getenv("KNOWFLOW_CLI_USER_ID", "").strip()
        if raw:
            try:
                configured = int(raw)
            except ValueError as exc:
                raise typer.BadParameter(
                    "KNOWFLOW_CLI_USER_ID必须是整数。"
                ) from exc
    if configured is not None:
        row = runtime.fetch_one(
            "SELECT id FROM app_user WHERE id=:id",
            {"id": configured},
        )
        if row:
            return int(row["id"])
        raise typer.BadParameter("指定用户不存在。")
    rows = runtime.fetch_all("SELECT id FROM app_user ORDER BY id LIMIT 2")
    if len(rows) == 1:
        return int(rows[0]["id"])
    if not rows:
        raise typer.BadParameter("尚无用户，请先通过网页创建账户。")
    raise typer.BadParameter(
        "存在多个用户，请传入--user-id或配置KNOWFLOW_CLI_USER_ID。"
    )


def _request(
    question: str,
    *,
    session_id: str | None,
    model_id: int | None,
    tools: bool,
    skill_id: int | None,
) -> Any:
    return {
        "question": question,
        "sessionId": session_id,
        "chatModelConfigId": model_id,
        "autoAgent": True,
        "enableTools": tools,
        "skillId": skill_id,
    }


@contextmanager
def _background_runtime() -> Iterator[None]:
    runtime = _runtime()
    runtime.memory_operation_runner.start()
    try:
        yield
    finally:
        runtime.memory_operation_runner.stop()
        runtime.memory_operation_runner.run_once()


def _approval_loop(
    execution: AgentExecution,
    *,
    service: AgentApplicationService,
    user_id: int,
    renderer: EventRenderer,
    assume_yes: bool,
) -> AgentExecution:
    current = execution
    while current.paused:
        approval_id = current.approval_id
        run_id = str(current.result.get("runId") or "")
        if not approval_id or not run_id:
            raise RuntimeError("Agent暂停，但审批信息不完整。")
        allowed = assume_yes or typer.confirm("允许本次工具调用？")
        current = service.resolve_approval(
            user_id=user_id,
            run_id=run_id,
            approval_id=approval_id,
            decision="allow_once" if allowed else "deny",
            event_sink=renderer,
        )
    return current


def _print_answer(
    execution: AgentExecution,
    *,
    json_events: bool,
    renderer: EventRenderer | None = None,
) -> None:
    if json_events:
        return
    if renderer is not None and renderer.streamed_text:
        console.print()
        return
    answer = str(execution.result.get("answer") or "").strip()
    if answer:
        console.print()
        console.print(Markdown(answer))


@app.command()
def configure(
    base_url: str | None = typer.Option(None, "--base-url"),
    model: str | None = typer.Option(None, "--model"),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Provider identifier. Most OpenAI-compatible APIs use custom.",
    ),
    api_mode: str | None = typer.Option(None, "--api-mode"),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        help="API key. Omit this option to enter it securely.",
    ),
    skip_test: bool = typer.Option(False, "--skip-test"),
) -> None:
    """Configure the default local BYOK model."""
    from .services.local_cli_runtime import (
        LocalCliConfigError,
        LocalCliConfigStore,
        test_local_connection,
        validate_local_config,
    )

    store = LocalCliConfigStore()
    current = store.load()
    resolved_base = base_url or typer.prompt(
        "API地址",
        default=current.get("base_url") or "https://api.openai.com/v1",
    )
    resolved_model = model or typer.prompt(
        "模型名称",
        default=current.get("model_name") or "gpt-5-mini",
    )
    resolved_provider = (
        provider or current.get("provider") or "custom"
    )
    resolved_mode = api_mode or typer.prompt(
        "接口协议",
        default=current.get("api_mode") or "responses",
    )
    resolved_key = api_key or typer.prompt(
        "API Key",
        hide_input=True,
        confirmation_prompt=False,
    )
    candidate = {
        "base_url": resolved_base,
        "model_name": resolved_model,
        "provider": resolved_provider,
        "api_mode": resolved_mode,
        "api_key": resolved_key,
    }
    try:
        validated = validate_local_config(candidate)
        if not skip_test:
            with console.status("正在检查模型连接..."):
                detail = test_local_connection(validated)
            console.print(f"[green]{detail}[/green]")
        store.save(**validated)
    except LocalCliConfigError as exc:
        error_console.print(f"[red]配置失败：{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(
        f"配置已保存：[bold]{validated['model_name']}[/bold] · "
        f"{validated['api_mode']}"
    )


@app.command()
def update() -> None:
    """更新KnowFlow CLI到最新版。"""
    current = _installed_cli_version()
    console.print(f"当前版本：[bold]{current}[/bold]")
    try:
        command = _cli_update_command()
        with console.status("正在更新KnowFlow CLI..."):
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
    except (OSError, RuntimeError) as exc:
        error_console.print(f"[red]更新失败：{exc}[/red]")
        raise typer.Exit(1) from exc
    if result.returncode != 0:
        error_console.print(
            "[red]更新失败：pipx未能完成安装。"
            "请重新运行官网安装命令。[/red]"
        )
        raise typer.Exit(result.returncode or 1)
    console.print("[green]更新完成。[/green]请重新运行knowflow。")


@auth_app.command("login")
def auth_login(
    server: str = typer.Argument(..., help="KnowFlow server URL."),
    account: str | None = typer.Option(None, "--account"),
) -> None:
    """Sign in through a browser, or use --account as a password fallback."""
    try:
        client = RemoteAgentClient(server)
        if account:
            resolved_password = typer.prompt("密码", hide_input=True)
            result = client.login(account, resolved_password)
        else:
            authorization = client.start_device_authorization()
            verification_uri = str(authorization.get("verificationUri") or "")
            user_code = str(authorization.get("userCode") or "")
            device_code = str(authorization.get("deviceCode") or "")
            interval = max(1, int(authorization.get("interval") or 3))
            expires_in = max(interval, int(authorization.get("expiresIn") or 600))
            console.print("请在浏览器中确认本次CLI登录：")
            console.print(f"[bold]{verification_uri}[/bold]")
            console.print(f"验证码：[bold cyan]{user_code}[/bold cyan]")
            opened = False
            try:
                opened = bool(webbrowser.open(verification_uri, new=2))
            except Exception:
                opened = False
            if not opened:
                console.print("未能自动打开浏览器，请手动访问上方地址。")
            deadline = time.monotonic() + expires_in
            result = {}
            with console.status("等待浏览器确认..."):
                while time.monotonic() < deadline:
                    state = client.poll_device_authorization(device_code)
                    status = str(state.get("status") or "")
                    if status == "authorized":
                        result = state
                        break
                    if status in {"denied", "expired", "consumed"}:
                        messages = {
                            "denied": "浏览器已拒绝本次登录。",
                            "expired": "浏览器登录请求已过期。",
                            "consumed": "本次登录请求已经使用。",
                        }
                        raise RemoteAgentError(status, messages[status])
                    time.sleep(interval)
            if not client.token:
                raise RemoteAgentError("expired", "浏览器登录请求已过期。")
        user = result.get("user") if isinstance(result, dict) else {}
        profile_store.save(
            {
                "server": client.server,
                "token": client.token,
                "user": {
                    "username": str((user or {}).get("username") or ""),
                    "displayName": str(
                        (user or {}).get("displayName") or ""
                    ),
                },
            }
        )
        console.print(f"[green]已登录[/green] {client.server}")
    except (ValueError, RemoteAgentError) as exc:
        error_console.print(f"[red]登录失败：{exc}[/red]")
        raise typer.Exit(1) from exc


@auth_app.command("status")
def auth_status(json_output: bool = typer.Option(False, "--json")) -> None:
    """Show the active remote CLI profile."""
    profile = profile_store.load()
    if not profile:
        payload = {"authenticated": False}
    else:
        try:
            client = RemoteAgentClient(
                str(profile["server"]),
                token=str(profile["token"]),
            )
            current = client.request("GET", "/api/auth/me")
            payload = {
                "authenticated": bool(
                    isinstance(current, dict)
                    and current.get("authenticated")
                ),
                "server": client.server,
                "user": (
                    current.get("user")
                    if isinstance(current, dict)
                    else None
                ),
            }
        except (ValueError, RemoteAgentError):
            payload = {
                "authenticated": False,
                "server": str(profile.get("server") or ""),
            }
    if json_output:
        _emit_json(payload)
    elif payload["authenticated"]:
        user = payload.get("user") or {}
        console.print(
            f"[green]已登录[/green] {payload['server']} · "
            f"{user.get('displayName') or user.get('username') or '用户'}"
        )
    else:
        console.print("[yellow]未登录远程服务器[/yellow]")
        raise typer.Exit(1)


@auth_app.command("logout")
def auth_logout() -> None:
    """Revoke and remove the active remote session."""
    profile = profile_store.load()
    if profile:
        try:
            RemoteAgentClient(
                str(profile["server"]),
                token=str(profile["token"]),
            ).logout()
        except (ValueError, RemoteAgentError):
            pass
    profile_store.clear()
    console.print("已退出远程登录。")


@app.command()
def doctor(
    user_id: int | None = typer.Option(None, "--user-id"),
    cli_only: bool = typer.Option(
        False,
        "--cli",
        help="Check the standalone CLI and Anthropic SRT sandbox only.",
    ),
    prepare: bool = typer.Option(
        False,
        "--prepare",
        help="Create missing runtime paths with safe permissions.",
    ),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Check whether the local Linux Agent runtime is ready."""
    if cli_only:
        from .tui.ink_launcher import ink_diagnostics

        checks = [
            *ink_diagnostics(smoke=True),
            *_local_agent().sandbox_diagnostics(smoke=True),
        ]
        ready = bool(checks) and all(bool(item["ready"]) for item in checks)
        if json_output:
            _emit_json({"ready": ready, "checks": checks})
        else:
            table = Table(title="KnowFlow CLI诊断")
            table.add_column("检查")
            table.add_column("状态")
            table.add_column("详情")
            for item in checks:
                table.add_row(
                    str(item["name"]),
                    "[green]通过[/green]" if item["ready"] else "[red]失败[/red]",
                    str(item.get("detail") or ""),
                )
            console.print(table)
        if not ready:
            raise typer.Exit(1)
        return
    from .services.runtime_preflight import inspect_runtime_paths

    runtime = _runtime()
    config = runtime
    directories = [
        ("data", config.DATA_DIR),
        ("uploads", config.UPLOAD_DIR),
        ("skills", config.SKILL_DIR),
        ("skill_imports", config.SKILL_IMPORT_DIR),
        ("tool_results", config.TOOL_RESULT_DIR),
    ]
    if config.WORKSPACE_ENABLED:
        directories.append(("workspaces", config.WORKSPACE_DIR))
    statuses = inspect_runtime_paths(
        directories=directories,
        files=(("langgraph_checkpoint", config.LANGGRAPH_CHECKPOINT_DB),),
        prepare=prepare,
    )
    checks: list[dict[str, Any]] = [
        {
            "name": "platform",
            "ready": platform.system() == "Linux",
            "detail": platform.system(),
        },
        {
            "name": "database",
            "ready": True,
            "detail": runtime.db.dialect,
        },
    ]
    checks.extend(
        {
            "name": item.name,
            "ready": item.ready,
            "detail": item.path if item.ready else item.error,
        }
        for item in statuses
    )
    try:
        resolved_user = _resolve_user_id(user_id)
        model = runtime.get_model_config(None, "chat", resolved_user)
        checks.append(
            {
                "name": "chat_model",
                "ready": model is not None,
                "detail": (
                    str(model.get("model_name"))
                    if model
                    else "default model is missing"
                ),
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "user",
                "ready": False,
                "detail": str(exc),
            }
        )
    if config.SANDBOX_ENABLED:
        for name, command in (
            ("sandbox", config.SANDBOX_COMMAND),
            ("shell", config.SANDBOX_SHELL),
            ("limiter", config.SANDBOX_LIMIT_COMMAND),
        ):
            checks.append(
                {
                    "name": name,
                    "ready": bool(
                        shutil.which(command) or Path(command).is_file()
                    ),
                    "detail": command,
                }
            )
    ready = all(bool(item["ready"]) for item in checks)
    if json_output:
        _emit_json({"ready": ready, "checks": checks})
    else:
        table = Table(title="KnowFlow运行诊断")
        table.add_column("检查")
        table.add_column("状态")
        table.add_column("详情")
        for item in checks:
            table.add_row(
                str(item["name"]),
                "[green]通过[/green]" if item["ready"] else "[red]失败[/red]",
                str(item.get("detail") or ""),
            )
        console.print(table)
    if not ready:
        raise typer.Exit(1)


@app.command("run")
def run_task(
    task: str = typer.Argument(..., help="Task to execute."),
    user_id: int | None = typer.Option(None, "--user-id"),
    model_id: int | None = typer.Option(None, "--model-id"),
    skill_id: int | None = typer.Option(None, "--skill-id"),
    tools: bool = typer.Option(True, "--tools/--no-tools"),
    json_events: bool = typer.Option(False, "--events", "--json"),
    assume_yes: bool = typer.Option(False, "--yes"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
    remote_mode: bool = typer.Option(False, "--remote"),
) -> None:
    """Execute one Agent task."""
    renderer = EventRenderer(json_events=json_events)
    try:
        remote = _remote_client(
            server,
            local=local,
            remote=remote_mode,
        )
        if remote is not None:
            if user_id is not None:
                raise typer.BadParameter(
                    "远程模式使用登录用户，不能传入--user-id。"
                )
            request_payload = _request(
                task,
                session_id=None,
                model_id=model_id,
                tools=tools,
                skill_id=skill_id,
            )
            execution = remote.run(
                _remote_payload(request_payload),
                renderer,
            )
            execution = _remote_approval_loop(
                execution,
                client=remote,
                renderer=renderer,
                assume_yes=assume_yes,
            )
            _print_answer(execution, json_events=json_events)
            return
        if any(value is not None for value in (user_id, model_id, skill_id)):
            raise typer.BadParameter(
                "--user-id、--model-id和--skill-id仅适用于--remote模式。"
            )
        agent = _local_agent()
        execution = agent.run(task, tools=tools, event_sink=renderer)
        execution = _local_approval_loop(
            execution,
            agent=agent,
            renderer=renderer,
            assume_yes=assume_yes,
        )
        _print_answer(
            execution,
            json_events=json_events,
            renderer=renderer,
        )
    except (KeyboardInterrupt, EOFError):
        raise typer.Exit(130) from None
    except Exception as exc:
        failure = _failure_payload(exc)
        if json_events:
            _emit_json(
                {
                    "type": "error",
                    **failure,
                }
            )
        else:
            error_console.print(
                f"[red]执行失败：{failure['message']}[/red]"
            )
        raise typer.Exit(1) from exc


@app.command()
def resume(
    run_id: str = typer.Argument(..., help="Interrupted run ID."),
    user_id: int | None = typer.Option(None, "--user-id"),
    json_events: bool = typer.Option(False, "--events", "--json"),
    assume_yes: bool = typer.Option(False, "--yes"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    """Resume an interrupted or approval-paused Agent run."""
    renderer = EventRenderer(json_events=json_events)
    try:
        remote = _remote_client(server, local=local)
        if remote is not None:
            if user_id is not None:
                raise typer.BadParameter(
                    "远程模式使用登录用户，不能传入--user-id。"
                )
            snapshot = remote.request(
                "GET", f"/api/agent/runs/{run_id}"
            )
            if not isinstance(snapshot, dict):
                raise RemoteAgentError(
                    "agent_run_not_found", "Agent运行不存在。"
                )
            status = str(snapshot.get("status") or "")
            if status == "waiting_approval":
                trace = snapshot.get("trace") or []
                waiting = next(
                    (
                        item
                        for item in reversed(trace)
                        if isinstance(item, dict)
                        and item.get("type") == "approval_required"
                        and item.get("approvalId")
                    ),
                    None,
                )
                if waiting is None:
                    raise RemoteAgentError(
                        "approval_unavailable",
                        "等待中的审批信息不可用。",
                    )
                allowed = assume_yes or typer.confirm(
                    "允许等待中的工具调用？"
                )
                execution = remote.resolve_approval(
                    run_id,
                    str(waiting["approvalId"]),
                    "allow_once" if allowed else "deny",
                    renderer,
                )
            elif status in {"failed", "interrupted"}:
                execution = remote.resume(run_id, renderer)
            else:
                raise typer.BadParameter(
                    "只有失败、中断或等待审批的Agent运行可以恢复。"
                )
            execution = _remote_approval_loop(
                execution,
                client=remote,
                renderer=renderer,
                assume_yes=assume_yes,
            )
            _print_answer(execution, json_events=json_events)
            return
        runtime = _runtime()
        resolved_user = _resolve_user_id(user_id)
        snapshot = runtime.agent_runs.get_snapshot(resolved_user, run_id)
        if snapshot is None:
            raise typer.BadParameter("Agent运行不存在。")
        if snapshot.get("status") not in {
            "failed",
            "interrupted",
            "waiting_approval",
        }:
            raise typer.BadParameter(
                "只有失败、中断或等待审批的Agent运行可以恢复。"
            )
        service = _application()
        with _background_runtime():
            if snapshot.get("status") == "waiting_approval":
                operations = runtime.agent_tool_operations.get_for_run(
                    resolved_user,
                    run_id,
                )
                waiting = next(
                    (
                        item
                        for item in reversed(operations)
                        if item.get("status") == "waiting"
                    ),
                    None,
                )
                if waiting is None:
                    execution = service.resume(
                        user_id=resolved_user,
                        run_id=run_id,
                        event_sink=renderer,
                    )
                else:
                    allowed = assume_yes or typer.confirm(
                        "允许等待中的工具调用？"
                    )
                    execution = service.resolve_approval(
                        user_id=resolved_user,
                        run_id=run_id,
                        approval_id=str(waiting["approvalId"]),
                        decision=("allow_once" if allowed else "deny"),
                        event_sink=renderer,
                    )
            else:
                execution = service.resume(
                    user_id=resolved_user,
                    run_id=run_id,
                    event_sink=renderer,
                )
            execution = _approval_loop(
                execution,
                service=service,
                user_id=resolved_user,
                renderer=renderer,
                assume_yes=assume_yes,
            )
        _print_answer(execution, json_events=json_events)
    except Exception as exc:
        failure = _failure_payload(exc)
        if json_events:
            _emit_json(
                {
                    "type": "error",
                    **failure,
                }
            )
        else:
            error_console.print(
                f"[red]恢复失败：{failure['message']}[/red]"
            )
        raise typer.Exit(1) from exc


@app.command()
def chat(
    user_id: int | None = typer.Option(None, "--user-id"),
    model_id: int | None = typer.Option(None, "--model-id"),
    skill_id: int | None = typer.Option(None, "--skill-id"),
    tools: bool = typer.Option(True, "--tools/--no-tools"),
    assume_yes: bool = typer.Option(False, "--yes"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
    remote_mode: bool = typer.Option(False, "--remote"),
    plain: bool = typer.Option(
        False,
        "--plain",
        help="Use the legacy line-oriented REPL instead of the full-screen TUI.",
    ),
) -> None:
    """Start an interactive Agent conversation."""
    remote = _remote_client(
        server,
        local=local,
        remote=remote_mode,
    )
    if remote is not None and user_id is not None:
        raise typer.BadParameter(
            "远程模式使用登录用户，不能传入--user-id。"
        )
    if remote is None and any(
        value is not None for value in (user_id, model_id, skill_id)
    ):
        raise typer.BadParameter(
            "--user-id、--model-id和--skill-id仅适用于--remote模式。"
        )
    agent = None if remote is not None else _local_agent()
    if not plain and sys.stdin.isatty() and sys.stdout.isatty():
        from .tui import run_tui
        from .tui.backend import TuiBackend

        run_tui(
            TuiBackend(
                local_agent=agent,
                remote_client=remote,
                tools=tools,
                model_id=model_id,
                skill_id=skill_id,
            ),
            assume_yes=assume_yes,
        )
        return
    history_path = Path.home() / ".knowflow" / "cli-history"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.touch(exist_ok=True)
    if os.name != "nt":
        history_path.parent.chmod(0o700)
        history_path.chmod(0o600)
    session = PromptSession(history=FileHistory(str(history_path)))
    renderer = EventRenderer(json_events=False)
    session_id: str | None = None
    current_model_id = model_id
    conversation: list[dict[str, Any]] = []
    console.print(
        "[dim]输入/exit退出，/new开始新会话。模型配置使用knowflow configure。[/dim]"
    )
    with nullcontext():
        while True:
            try:
                question = session.prompt("knowflow> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not question:
                continue
            if question in {"/exit", "/quit"}:
                break
            if question == "/new":
                session_id = None
                conversation = []
                console.print("[dim]已开始新会话。[/dim]")
                continue
            if question.startswith("/model"):
                if remote is None:
                    console.print(
                        "[dim]本地模型由knowflow configure管理。[/dim]"
                    )
                    continue
                parts = question.split(maxsplit=1)
                if len(parts) == 1:
                    console.print(
                        f"[dim]当前模型ID：{current_model_id or '默认'}[/dim]"
                    )
                    continue
                try:
                    current_model_id = int(parts[1])
                except ValueError:
                    error_console.print("[red]模型ID必须是整数。[/red]")
                    continue
                session_id = None
                console.print(
                    f"[dim]已切换到模型ID {current_model_id}，并开始新会话。[/dim]"
                )
                continue
            renderer.streamed_text = False
            try:
                if remote is not None:
                    request_payload = _request(
                        question,
                        session_id=session_id,
                        model_id=current_model_id,
                        tools=tools,
                        skill_id=skill_id,
                    )
                    execution = remote.run(
                        _remote_payload(request_payload),
                        renderer,
                    )
                    execution = _remote_approval_loop(
                        execution,
                        client=remote,
                        renderer=renderer,
                        assume_yes=assume_yes,
                    )
                else:
                    assert agent is not None
                    execution = agent.run(
                        question,
                        history=conversation,
                        tools=tools,
                        event_sink=renderer,
                    )
                    execution = _local_approval_loop(
                        execution,
                        agent=agent,
                        renderer=renderer,
                        assume_yes=assume_yes,
                    )
                    conversation = list(
                        execution.result.get("messages") or conversation
                    )
                    answer = str(execution.result.get("answer") or "")
                    if answer:
                        conversation.append(
                            {"role": "assistant", "content": answer}
                        )
                session_id = str(
                    execution.result.get("sessionId") or session_id or ""
                ) or None
                _print_answer(
                    execution,
                    json_events=False,
                    renderer=renderer,
                )
            except Exception as exc:
                failure = _failure_payload(exc)
                error_console.print(
                    f"[red]执行失败：{failure['message']}[/red]"
                )


@app.command()
def runs(
    user_id: int | None = typer.Option(None, "--user-id"),
    limit: int = typer.Option(20, min=1, max=100),
    json_output: bool = typer.Option(False, "--json"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    """List recent Agent runs."""
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request(
            "GET",
            "/api/agent/runs",
            params={"limit": limit},
        )
        rows = data if isinstance(data, list) else []
    else:
        runtime = _runtime()
        resolved_user = _resolve_user_id(user_id)
        rows = runtime.agent_runs.list_recent(
            resolved_user,
            limit=limit,
        )
    if json_output:
        _emit_json({"runs": rows})
        return
    table = Table(title="最近运行")
    for title in ("Run", "状态", "任务", "更新时间"):
        table.add_column(title)
    for row in rows:
        table.add_row(
            str(row["id"]),
            str(row["status"]),
            str(row.get("goalSummary") or row.get("goal_summary") or ""),
            str(row.get("updatedAt") or row.get("updated_at") or ""),
        )
    console.print(table)


@tools_app.command("list")
def list_tools(
    user_id: int | None = typer.Option(None, "--user-id"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request("GET", "/api/agent/tools")
        names = (
            [str(name) for name in data.get("tools", [])]
            if isinstance(data, dict)
            else []
        )
    else:
        from .routers.extensions import build_tool_registry

        resolved_user = _resolve_user_id(user_id)
        registry = build_tool_registry(resolved_user, True)
        names = list(registry.names())
    table = Table(title="可用工具")
    table.add_column("名称")
    for name in names:
        table.add_row(str(name))
    console.print(table)


@models_app.command("list")
def list_models(
    user_id: int | None = typer.Option(None, "--user-id"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request(
            "GET", "/api/model-configs", params={"modelType": "chat"}
        )
        rows = data if isinstance(data, list) else []
    else:
        runtime = _runtime()
        rows = runtime.fetch_all(
            """
            SELECT id, name, model_name, api_mode
            FROM model_config
            WHERE user_id=:user_id AND model_type='chat'
            ORDER BY id DESC
            """,
            {"user_id": _resolve_user_id(user_id)},
        )
    table = Table(title="聊天模型")
    table.add_column("ID")
    table.add_column("名称")
    table.add_column("模型")
    table.add_column("协议")
    for row in rows:
        table.add_row(
            str(row.get("id") or ""),
            str(row.get("name") or row.get("configName") or ""),
            str(
                row.get("model")
                or row.get("modelName")
                or row.get("model_name")
                or ""
            ),
            str(
                row.get("protocol")
                or row.get("apiMode")
                or row.get("api_mode")
                or ""
            ),
        )
    console.print(table)


@skills_app.command("list")
def list_skills(
    user_id: int | None = typer.Option(None, "--user-id"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request("GET", "/api/skills/")
        rows = data if isinstance(data, list) else []
    else:
        runtime = _runtime()
        rows = runtime.skills.list_for_user(_resolve_user_id(user_id))
    table = Table(title="Skills")
    table.add_column("名称")
    table.add_column("版本")
    table.add_column("状态")
    for row in rows:
        table.add_row(
            str(row.get("name") or row.get("slug") or ""),
            str(row.get("version") or ""),
            "启用" if row.get("enabled") else "停用",
        )
    console.print(table)


@mcp_app.command("list")
def list_mcp(
    user_id: int | None = typer.Option(None, "--user-id"),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request("GET", "/api/mcp/servers")
        rows = data if isinstance(data, list) else []
    else:
        runtime = _runtime()
        rows = runtime.mcp_configs.list_for_user(_resolve_user_id(user_id))
    table = Table(title="MCP服务器")
    table.add_column("名称")
    table.add_column("连接")
    table.add_column("状态")
    for row in rows:
        table.add_row(
            str(row.get("name") or row.get("slug") or ""),
            str(row.get("authType") or row.get("auth_type") or ""),
            str(row.get("status") or ""),
        )
    console.print(table)


@memory_app.command("list")
def list_memory(
    user_id: int | None = typer.Option(None, "--user-id"),
    limit: int = typer.Option(20, min=1, max=100),
    server: str | None = typer.Option(None, "--server"),
    local: bool = typer.Option(False, "--local"),
) -> None:
    remote = _remote_client(server, local=local)
    if remote is not None:
        if user_id is not None:
            raise typer.BadParameter(
                "远程模式使用登录用户，不能传入--user-id。"
            )
        data = remote.request(
            "GET", "/api/memories", params={"limit": limit}
        )
        rows = data if isinstance(data, list) else []
    else:
        runtime = _runtime()
        rows = runtime.memory_manager.list(_resolve_user_id(user_id), limit)
    table = Table(title="长期记忆")
    table.add_column("内容")
    table.add_column("更新时间")
    for row in rows:
        table.add_row(
            str(row.get("memory") or row.get("content") or ""),
            str(row.get("updatedAt") or row.get("createdAt") or ""),
        )
    console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
