from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .agent_loop import ToolHandlerResult, ToolRegistry


_WINDOWS_DEVICE_NAMES = {"CON", "PRN", "AUX", "NUL"}


class WorkspaceRuntimeError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class WorkspacePathArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: str = Field(default="", max_length=500)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        if "\\" in value or "\x00" in value:
            raise ValueError("Workspace paths must use forward slashes.")
        return value


class ReadWorkspaceFileArguments(WorkspacePathArguments):
    path: str = Field(min_length=1, max_length=500)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=40_000, ge=1, le=100_000)


class WriteWorkspaceFileArguments(WorkspacePathArguments):
    path: str = Field(min_length=1, max_length=500)
    content: str = Field(max_length=1_000_000)
    overwrite: bool = False


class RunSandboxCommandArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    command: str = Field(min_length=1, max_length=4_000)
    timeout_seconds: int = Field(default=30, ge=1, le=120)


@dataclass(frozen=True)
class SandboxCommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class WorkspaceRuntime:
    def __init__(
        self,
        root: Path,
        *,
        user_id: int,
        max_file_bytes: int = 1_000_000,
    ) -> None:
        base = Path(root).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        namespace = hashlib.sha256(
            f"workspace\0{int(user_id)}".encode("utf-8")
        ).hexdigest()[:32]
        self.root = (base / namespace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_file_bytes = max(1_024, int(max_file_bytes))
        self._restrict_directory(base)
        self._restrict_directory(self.root)

    @staticmethod
    def _restrict_directory(path: Path) -> None:
        try:
            path.chmod(0o750)
        except OSError:
            pass

    @staticmethod
    def _restrict_file(path: Path) -> None:
        try:
            path.chmod(0o640)
        except OSError:
            pass

    @staticmethod
    def _components(value: str) -> tuple[str, ...]:
        if not value:
            return ()
        if (
            value.startswith("/")
            or value.endswith("/")
            or "//" in value
            or "\\" in value
            or "\x00" in value
            or ":" in value
        ):
            raise WorkspaceRuntimeError(
                "workspace_path_invalid",
                "Invalid workspace-relative path.",
            )
        parts = tuple(value.split("/"))
        if any(part in {"", ".", ".."} for part in parts):
            raise WorkspaceRuntimeError(
                "workspace_path_invalid",
                "Invalid workspace-relative path.",
            )
        for part in parts:
            stem = part.split(".", 1)[0].upper()
            if (
                part.endswith((" ", "."))
                or any(ord(character) < 32 for character in part)
                or stem in _WINDOWS_DEVICE_NAMES
                or stem.startswith("COM") and stem[3:].isdigit()
                or stem.startswith("LPT") and stem[3:].isdigit()
            ):
                raise WorkspaceRuntimeError(
                    "workspace_path_invalid",
                    "Invalid workspace-relative path.",
                )
        return parts

    @staticmethod
    def _is_sensitive(parts: tuple[str, ...]) -> bool:
        lowered = [part.lower() for part in parts]
        return any(
            part in {".git", ".ssh", "id_rsa", "id_ed25519"}
            or part == ".env"
            or part.startswith(".env.")
            for part in lowered
        )

    def _resolve(self, value: str, *, write: bool) -> Path:
        parts = self._components(value)
        if self._is_sensitive(parts):
            raise WorkspaceRuntimeError(
                "workspace_path_denied",
                "Sensitive workspace paths are not available to tools.",
            )
        candidate = self.root.joinpath(*parts)
        if write:
            current = self.root
            for part in parts:
                current = current / part
                if current.exists() and current.is_symlink():
                    raise WorkspaceRuntimeError(
                        "workspace_symlink_denied",
                        "Writing through workspace symlinks is not allowed.",
                    )
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceRuntimeError(
                "workspace_path_denied",
                "The path resolves outside the workspace.",
            ) from exc
        if self._is_sensitive(tuple(relative.parts)):
            raise WorkspaceRuntimeError(
                "workspace_path_denied",
                "Sensitive workspace paths are not available to tools.",
            )
        return resolved

    def list_entries(self, path: str = "") -> dict[str, Any]:
        directory = self._resolve(path, write=False)
        if not directory.is_dir():
            raise WorkspaceRuntimeError(
                "workspace_directory_missing",
                "Workspace directory was not found.",
            )
        entries = []
        for item in sorted(directory.iterdir(), key=lambda value: value.name.lower()):
            try:
                relative = item.relative_to(self.root).as_posix()
            except ValueError:
                continue
            if self._is_sensitive(tuple(relative.split("/"))):
                continue
            kind = "symlink" if item.is_symlink() else (
                "directory" if item.is_dir() else "file"
            )
            entries.append({"path": relative, "kind": kind})
            if len(entries) >= 200:
                break
        return {"path": path, "entries": entries}

    def read_text(
        self,
        path: str,
        *,
        offset: int = 0,
        limit: int = 40_000,
    ) -> dict[str, Any]:
        target = self._resolve(path, write=False)
        if not target.is_file():
            raise WorkspaceRuntimeError(
                "workspace_file_missing",
                "Workspace file was not found.",
            )
        size = target.stat().st_size
        if size > self.max_file_bytes:
            raise WorkspaceRuntimeError(
                "workspace_file_too_large",
                "Workspace file exceeds the configured size limit.",
            )
        raw = target.read_bytes()
        if b"\x00" in raw:
            raise WorkspaceRuntimeError(
                "workspace_file_binary",
                "Binary workspace files cannot be read as text.",
            )
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceRuntimeError(
                "workspace_file_encoding",
                "Workspace text files must use UTF-8.",
            ) from exc
        start = max(0, int(offset))
        page_size = max(1, min(100_000, int(limit)))
        end = min(len(content), start + page_size)
        return {
            "path": path,
            "content": content[start:end],
            "offset": start,
            "nextOffset": end if end < len(content) else None,
            "eof": end >= len(content),
        }

    def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool,
    ) -> ToolHandlerResult:
        encoded = str(content).encode("utf-8")
        if len(encoded) > self.max_file_bytes:
            raise WorkspaceRuntimeError(
                "workspace_file_too_large",
                "Workspace file exceeds the configured size limit.",
            )
        target = self._resolve(path, write=True)
        if target.exists() and not overwrite:
            raise WorkspaceRuntimeError(
                "workspace_file_exists",
                "Workspace file already exists; explicitly allow overwrite.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._restrict_directory(target.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".knowflow-write-",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            self._restrict_file(temporary)
            temporary.replace(target)
            self._restrict_file(target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return ToolHandlerResult(
            output={"path": path, "writtenBytes": len(encoded)},
            audit_output={"path": path, "writtenBytes": len(encoded)},
        )


class SrtSandboxRunner:
    def __init__(
        self,
        workspace: WorkspaceRuntime,
        *,
        command: str = "srt",
        shell: str = "pwsh",
        timeout_seconds: int = 60,
        max_output_bytes: int = 1_000_000,
        run_factory: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.workspace = workspace
        self.command = str(command or "srt")
        self.shell = str(shell or "pwsh")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_bytes = max(1_024, int(max_output_bytes))
        self._run_factory = run_factory

    def available(self) -> bool:
        return bool(shutil.which(self.command) or Path(self.command).is_file())

    @staticmethod
    def _safe_environment() -> dict[str, str]:
        allowed = {
            "PATH",
            "PATHEXT",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "LOCALAPPDATA",
        }
        return {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed
        }

    def run(self, command: str, *, timeout_seconds: int) -> SandboxCommandResult:
        if not self.available():
            raise WorkspaceRuntimeError(
                "sandbox_runtime_unavailable",
                "Anthropic Sandbox Runtime is not installed.",
            )
        settings = {
            "filesystem": {
                "denyRead": [str(Path.home())],
                "allowRead": [str(self.workspace.root)],
                "allowWrite": [str(self.workspace.root)],
                "denyWrite": [
                    str(self.workspace.root / ".git"),
                    str(self.workspace.root / ".env"),
                ],
            },
            "network": {
                "allowedDomains": [],
                "deniedDomains": [],
            },
        }
        settings_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                delete=False,
            ) as handle:
                json.dump(settings, handle, ensure_ascii=False)
                settings_path = handle.name
            timeout = min(self.timeout_seconds, max(1, int(timeout_seconds)))
            completed = self._run_factory(
                [
                    self.command,
                    "--settings",
                    settings_path,
                    self.shell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    str(command),
                ],
                cwd=self.workspace.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._safe_environment(),
                timeout=timeout,
                check=False,
            )
            stdout = str(completed.stdout or "")
            stderr = str(completed.stderr or "")
            return SandboxCommandResult(
                exit_code=int(completed.returncode),
                stdout=stdout[: self.max_output_bytes],
                stderr=stderr[: self.max_output_bytes],
                timed_out=False,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxCommandResult(
                exit_code=124,
                stdout=str(exc.stdout or "")[: self.max_output_bytes],
                stderr=str(exc.stderr or "")[: self.max_output_bytes],
                timed_out=True,
            )
        finally:
            if settings_path:
                try:
                    Path(settings_path).unlink()
                except OSError:
                    pass


def register_workspace_tools(
    registry: ToolRegistry,
    workspace: WorkspaceRuntime,
    *,
    sandbox: SrtSandboxRunner | None = None,
) -> tuple[str, ...]:
    registered = []
    registry.register(
        name="list_workspace",
        description="List files and directories in the isolated user workspace.",
        arguments_model=WorkspacePathArguments,
        handler=lambda args: workspace.list_entries(args.path),
        read_only=True,
        concurrency_safe=True,
        interrupt_behavior="cancel",
        engine_names={"langgraph"},
        trace_kind="workspace",
        search_hint="inspect project files and directories",
    )
    registered.append("list_workspace")
    registry.register(
        name="read_workspace_file",
        description="Read bounded UTF-8 text from the isolated user workspace.",
        arguments_model=ReadWorkspaceFileArguments,
        handler=lambda args: workspace.read_text(
            args.path,
            offset=args.offset,
            limit=args.limit,
        ),
        read_only=True,
        concurrency_safe=True,
        interrupt_behavior="cancel",
        engine_names={"langgraph"},
        trace_kind="workspace",
        search_hint="read local project source and text files",
    )
    registered.append("read_workspace_file")
    registry.register(
        name="write_workspace_file",
        description="Create or replace a UTF-8 file in the isolated user workspace.",
        arguments_model=WriteWorkspaceFileArguments,
        handler=lambda args: workspace.write_text(
            args.path,
            args.content,
            overwrite=args.overwrite,
        ),
        read_only=False,
        destructive=True,
        concurrency_safe=False,
        interrupt_behavior="block",
        engine_names={"langgraph"},
        trace_kind="workspace",
        search_hint="write or update local project files",
    )
    registered.append("write_workspace_file")
    if sandbox is not None and sandbox.available():
        registry.register(
            name="run_sandbox_command",
            description=(
                "Run a PowerShell command inside Anthropic Sandbox Runtime "
                "with workspace-only writes and no network access."
            ),
            arguments_model=RunSandboxCommandArguments,
            handler=lambda args: sandbox.run(
                args.command,
                timeout_seconds=args.timeout_seconds,
            ).__dict__,
            read_only=False,
            destructive=True,
            concurrency_safe=False,
            interrupt_behavior="block",
            engine_names={"langgraph"},
            trace_kind="sandbox",
            search_hint="run tests builds and PowerShell commands safely",
        )
        registered.append("run_sandbox_command")
    return tuple(registered)
