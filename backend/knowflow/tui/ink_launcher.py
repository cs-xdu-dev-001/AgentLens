from __future__ import annotations

from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any


class InkTuiUnavailable(RuntimeError):
    pass


def _node_major(node: str) -> int:
    try:
        result = subprocess.run(
            [node, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
        value = result.stdout.strip().lstrip("v").split(".", 1)[0]
        return int(value) if result.returncode == 0 else 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def _entry_path() -> Path | None:
    configured = os.getenv("KNOWFLOW_INK_TUI_ENTRY", "").strip()
    if configured:
        candidate = Path(configured).expanduser().resolve()
        return candidate if candidate.is_file() else None
    candidate = resources.files("knowflow.ink_tui").joinpath("index.mjs")
    try:
        path = Path(str(candidate)).resolve()
    except (OSError, TypeError, ValueError):
        return None
    return path if path.is_file() else None


def run_ink_tui(
    backend: Any,
    *,
    assume_yes: bool = False,
    startup_action: str = "",
) -> bool:
    """Run the bundled React/Ink UI, returning False when it is unavailable."""

    if not sys.platform.startswith("linux") and not os.getenv(
        "KNOWFLOW_INK_TUI_ALLOW_UNSUPPORTED"
    ):
        return False
    node = shutil.which("node")
    entry = _entry_path()
    if not node or entry is None or _node_major(node) < 22:
        return False
    remote = getattr(backend, "remote_client", None)
    local_agent = getattr(backend, "local_agent", None)
    workspace_root = getattr(local_agent, "workspace_root", None)
    payload = {
        "mode": "remote" if remote is not None else "local",
        "server": str(getattr(remote, "server", "") or ""),
        "tools": bool(getattr(backend, "tools", True)),
        "modelId": getattr(backend, "model_id", None),
        "skillId": getattr(backend, "skill_id", None),
        "assumeYes": bool(assume_yes),
        "workspaceRoot": str(workspace_root) if workspace_root is not None else "",
        "startupAction": (
            startup_action if startup_action in {"resume", "continue"} else ""
        ),
    }
    environment = dict(os.environ)
    environment.update(
        {
            "KNOWFLOW_RUNTIME_PYTHON": sys.executable,
            "KNOWFLOW_RUNTIME_CONFIG": json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "KNOWFLOW_CLI_VERSION": _installed_version(),
        }
    )
    try:
        completed = subprocess.run(
            [node, str(entry)],
            check=False,
            env=environment,
        )
    except OSError as exc:
        raise InkTuiUnavailable("无法启动Ink终端界面。") from exc
    if completed.returncode not in {0, 130}:
        raise RuntimeError(f"Ink终端界面异常退出（{completed.returncode}）。")
    return True


def ink_diagnostics(*, smoke: bool = True) -> list[dict[str, Any]]:
    node = shutil.which("node")
    major = _node_major(node) if node else 0
    entry = _entry_path()
    checks: list[dict[str, Any]] = [
        {
            "name": "ink_platform",
            "ready": sys.platform.startswith("linux"),
            "detail": sys.platform,
        },
        {
            "name": "node",
            "ready": bool(node and major >= 22),
            "detail": f"{node or '未找到'} · major {major or 'unknown'}",
        },
        {
            "name": "ink_bundle",
            "ready": entry is not None,
            "detail": str(entry or "未找到内置Ink bundle"),
        },
    ]
    if not smoke or not all(bool(item["ready"]) for item in checks):
        return checks
    try:
        result = subprocess.run(
            [str(node), str(entry), "--self-test"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        ready = result.returncode == 0 and result.stdout.strip() == "knowflow-ink-ok"
        detail = "Ink界面bundle可启动" if ready else f"退出码{result.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        ready = False
        detail = type(exc).__name__
    checks.append({"name": "ink_smoke", "ready": ready, "detail": detail})
    return checks


def _installed_version() -> str:
    try:
        from importlib.metadata import version

        return version("knowflow-ai")
    except Exception:
        return "development"
