from __future__ import annotations

from dataclasses import dataclass
import difflib
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import signal
import shutil
import subprocess
import sys
import tempfile
from threading import Thread
import time
from typing import Any, Callable
from uuid import uuid4

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


class EditWorkspaceFileArguments(WorkspacePathArguments):
    path: str = Field(min_length=1, max_length=500)
    old_text: str = Field(min_length=1, max_length=500_000)
    new_text: str = Field(max_length=500_000)
    replace_all: bool = False


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
    cancelled: bool = False
    elapsed_seconds: float = 0.0
    total_lines: int = 0
    total_bytes: int = 0


class WorkspaceContext:
    """Single source of truth for a local agent's project boundary and edits."""

    def __init__(self, project_root: Path, *, state_root: Path | None = None) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        self.project_root.mkdir(parents=True, exist_ok=True)
        self.original_cwd = self.project_root
        self.cwd = self.project_root
        self.allowed_roots: list[Path] = [self.project_root]
        self.current_run_id: str | None = None
        self.state_root = Path(state_root).expanduser().resolve() if state_root else None
        if self.state_root is not None:
            self.state_root.mkdir(parents=True, exist_ok=True)
            self._chmod(self.state_root, 0o700)
        self._journal_path = (
            self.state_root / "changes.jsonl" if self.state_root is not None else None
        )
        self._snapshot_root = (
            self.state_root / "snapshots" if self.state_root is not None else None
        )
        if self._snapshot_root is not None:
            self._snapshot_root.mkdir(parents=True, exist_ok=True)
            self._chmod(self._snapshot_root, 0o700)

    @staticmethod
    def _chmod(path: Path, mode: int) -> None:
        if os.name == "nt":
            return
        try:
            path.chmod(mode)
        except OSError:
            pass

    @staticmethod
    def _inside(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    def contains(self, path: Path) -> bool:
        resolved = Path(path).resolve(strict=False)
        return any(self._inside(resolved, root) for root in self.allowed_roots)

    def add_directory(self, value: str) -> dict[str, Any]:
        raw = str(value or "").strip()
        if not raw:
            raise WorkspaceRuntimeError(
                "workspace_directory_required",
                "Please provide a directory path.",
            )
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.cwd / candidate
        resolved = candidate.resolve()
        if not resolved.is_dir():
            raise WorkspaceRuntimeError(
                "workspace_directory_missing",
                "Workspace directory was not found.",
            )
        for root in self.allowed_roots:
            if self._inside(resolved, root):
                return self.status(message=f"{resolved} is already accessible.")
        self.allowed_roots.append(resolved)
        return self.status(message=f"Added {resolved} for this session.")

    def change_directory(self, value: str) -> dict[str, Any]:
        raw = str(value or "").strip() or str(self.project_root)
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = self.cwd / candidate
        resolved = candidate.resolve()
        if not resolved.is_dir() or not self.contains(resolved):
            raise WorkspaceRuntimeError(
                "workspace_directory_denied",
                "The directory must exist inside an allowed working directory.",
            )
        self.cwd = resolved
        return self.status(message=f"Current directory: {resolved}")

    def begin_turn(self, run_id: str) -> None:
        self.current_run_id = str(run_id)

    def _git(self, *arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "-C", str(self.project_root), *arguments],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return completed.stdout.strip() if completed.returncode == 0 else ""

    def status(self, *, message: str | None = None) -> dict[str, Any]:
        branch = self._git("branch", "--show-current")
        porcelain = self._git("status", "--porcelain=v1")
        changed = len([line for line in porcelain.splitlines() if line.strip()])
        home = Path.home().resolve()
        is_home = self.project_root == home
        project_markers = (
            ".git",
            "pyproject.toml",
            "package.json",
            "pnpm-workspace.yaml",
            "Cargo.toml",
            "go.mod",
            "README.md",
        )
        has_project_marker = any(
            (self.project_root / marker).exists() for marker in project_markers
        )
        warnings: list[str] = []
        if is_home:
            warnings.append(
                "当前工作区是HOME目录。建议用knowflow chat --workspace <项目目录>进入真实项目，避免Agent只看到用户配置文件。"
            )
        elif not has_project_marker:
            warnings.append(
                "当前目录缺少常见项目标记。若这是测试目录可忽略；否则请用/workspace确认边界或用--workspace指定项目根目录。"
            )
        payload: dict[str, Any] = {
            "projectRoot": str(self.project_root),
            "cwd": str(self.cwd),
            "allowedDirectories": [str(path) for path in self.allowed_roots],
            "protectedPatterns": [".git", ".env*", ".ssh", ".tmp"],
            "branch": branch or None,
            "dirty": changed > 0,
            "changedFiles": changed,
            "runId": self.current_run_id,
            "workspaceKind": "home" if is_home else ("project" if has_project_marker else "directory"),
            "warnings": warnings,
        }
        if message:
            payload["message"] = message
        return payload

    @staticmethod
    def _digest(payload: bytes | None) -> str | None:
        return hashlib.sha256(payload).hexdigest() if payload is not None else None

    def _append_record(self, record: dict[str, Any]) -> None:
        if self._journal_path is None:
            return
        with self._journal_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._chmod(self._journal_path, 0o600)

    def _records(self) -> list[dict[str, Any]]:
        if self._journal_path is None or not self._journal_path.is_file():
            return []
        records: list[dict[str, Any]] = []
        try:
            lines = self._journal_path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            return []
        for line in lines[-1000:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    def _active_records(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for record in self._records():
            identifier = str(record.get("id") or "")
            if not identifier:
                continue
            if identifier not in latest:
                order.append(identifier)
            latest[identifier] = record
        return [latest[identifier] for identifier in order if not latest[identifier].get("undone")]

    def record_change(
        self,
        target: Path,
        *,
        before: bytes | None,
        after: bytes,
        operation: str,
    ) -> dict[str, Any]:
        operation_id = f"edit_{uuid4().hex[:16]}"
        snapshot_name = None
        if before is not None and self._snapshot_root is not None:
            snapshot_name = f"{operation_id}.before"
            snapshot = self._snapshot_root / snapshot_name
            snapshot.write_bytes(before)
            self._chmod(snapshot, 0o600)
        record = {
            "id": operation_id,
            "runId": self.current_run_id,
            "path": str(target),
            "displayPath": self.display_path(target),
            "operation": operation,
            "beforeHash": self._digest(before),
            "afterHash": self._digest(after),
            "beforeSnapshot": snapshot_name,
            "created": before is None,
            "undone": False,
            "createdAt": time.time(),
        }
        self._append_record(record)
        return record

    def display_path(self, target: Path) -> str:
        resolved = target.resolve(strict=False)
        for root in self.allowed_roots:
            if self._inside(resolved, root):
                relative = resolved.relative_to(root).as_posix()
                return relative or "."
        return resolved.name

    def changes(self, run_id: str | None = None) -> list[dict[str, Any]]:
        selected = run_id or self.current_run_id
        records = self._active_records()
        if selected:
            records = [item for item in records if item.get("runId") == selected]
        return records

    def diff(self, path: str | None = None, *, run_id: str | None = None) -> dict[str, Any]:
        records = self.changes(run_id)
        if path:
            records = [item for item in records if item.get("displayPath") == path]
        latest: dict[str, dict[str, Any]] = {}
        first: dict[str, dict[str, Any]] = {}
        for record in records:
            key = str(record.get("path") or "")
            first.setdefault(key, record)
            latest[key] = record
        chunks: list[str] = []
        files: list[dict[str, Any]] = []
        for key, record in latest.items():
            target = Path(key)
            initial = first[key]
            before = b""
            snapshot_name = initial.get("beforeSnapshot")
            if snapshot_name and self._snapshot_root is not None:
                snapshot = self._snapshot_root / str(snapshot_name)
                if snapshot.is_file():
                    before = snapshot.read_bytes()
            after = target.read_bytes() if target.is_file() else b""
            try:
                before_text = before.decode("utf-8").splitlines(keepends=True)
                after_text = after.decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                continue
            display = str(record.get("displayPath") or target.name)
            patch = "".join(
                difflib.unified_diff(
                    before_text,
                    after_text,
                    fromfile=f"a/{display}",
                    tofile=f"b/{display}",
                )
            )
            added = sum(1 for line in patch.splitlines() if line.startswith("+") and not line.startswith("+++"))
            removed = sum(1 for line in patch.splitlines() if line.startswith("-") and not line.startswith("---"))
            files.append({"path": display, "added": added, "removed": removed})
            if patch:
                chunks.append(patch)
        return {
            "runId": run_id or self.current_run_id,
            "files": files,
            "patch": "\n".join(chunks)[:100_000],
        }

    def undo_last(self) -> dict[str, Any]:
        records = self._active_records()
        record = records[-1] if records else None
        if record is None:
            raise WorkspaceRuntimeError("workspace_undo_empty", "There is no file change to undo.")
        target = Path(str(record.get("path") or ""))
        resolved = target.resolve(strict=False)
        if target.is_symlink() or not self.contains(resolved):
            raise WorkspaceRuntimeError(
                "workspace_undo_denied",
                "The changed path no longer resolves safely inside the workspace.",
            )
        current = target.read_bytes() if target.is_file() else None
        if self._digest(current) != record.get("afterHash"):
            raise WorkspaceRuntimeError(
                "workspace_undo_conflict",
                "The file changed after this operation; undo was not applied.",
            )
        snapshot_name = record.get("beforeSnapshot")
        if record.get("created"):
            target.unlink(missing_ok=True)
        elif snapshot_name and self._snapshot_root is not None:
            before = (self._snapshot_root / str(snapshot_name)).read_bytes()
            target.write_bytes(before)
        else:
            raise WorkspaceRuntimeError("workspace_undo_unavailable", "The snapshot is unavailable.")
        self._append_record({**record, "undone": True, "undoneAt": time.time()})
        return {"path": record.get("displayPath"), "operationId": record.get("id")}


class WorkspaceRuntime:
    def __init__(
        self,
        root: Path,
        *,
        user_id: int,
        max_file_bytes: int = 1_000_000,
        isolated_namespace: bool = True,
        manage_root_permissions: bool = True,
        context: WorkspaceContext | None = None,
    ) -> None:
        base = Path(root).expanduser().resolve()
        base.mkdir(parents=True, exist_ok=True)
        namespace = hashlib.sha256(
            f"workspace\0{int(user_id)}".encode("utf-8")
        ).hexdigest()[:32]
        self._root = (
            (base / namespace).resolve()
            if isolated_namespace
            else base
        )
        self._root.mkdir(parents=True, exist_ok=True)
        self.context = context
        self.max_file_bytes = max(1_024, int(max_file_bytes))
        if manage_root_permissions:
            self._restrict_directory(base)
            self._restrict_directory(self.root)

    @property
    def root(self) -> Path:
        return self.context.cwd if self.context is not None else self._root

    @property
    def allowed_roots(self) -> tuple[Path, ...]:
        return tuple(self.context.allowed_roots) if self.context is not None else (self._root,)

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
            part in {".git", ".ssh", ".tmp", "id_rsa", "id_ed25519"}
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
        matching_root = next(
            (
                root
                for root in self.allowed_roots
                if WorkspaceContext._inside(resolved, root)
            ),
            None,
        )
        allowed = matching_root is not None
        try:
            relative = resolved.relative_to(self.root)
            allowed = True
        except ValueError as exc:
            if self.context is not None and matching_root is not None:
                relative = resolved.relative_to(matching_root)
            else:
                raise WorkspaceRuntimeError(
                    "workspace_path_denied",
                    "The path resolves outside the workspace.",
                ) from exc
        if not allowed:
            raise WorkspaceRuntimeError(
                "workspace_path_denied",
                "The path resolves outside the workspace.",
            )
        if self._is_sensitive(tuple(relative.parts)):
            raise WorkspaceRuntimeError(
                "workspace_path_denied",
                "Sensitive workspace paths are not available to tools.",
            )
        return resolved

    def _before_write(self, target: Path) -> bytes | None:
        if not target.is_file():
            return None
        if target.stat().st_size > self.max_file_bytes:
            raise WorkspaceRuntimeError(
                "workspace_file_too_large",
                "Existing workspace file exceeds the configured size limit.",
            )
        return target.read_bytes()

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

    def file_path(self, path: str) -> Path:
        target = self._resolve(path, write=False)
        if not target.is_file():
            raise WorkspaceRuntimeError(
                "workspace_file_missing",
                "Workspace file was not found.",
            )
        return target

    def write_bytes(
        self,
        path: str,
        content: bytes,
        *,
        overwrite: bool,
    ) -> dict[str, Any]:
        payload = bytes(content)
        if len(payload) > self.max_file_bytes:
            raise WorkspaceRuntimeError(
                "workspace_file_too_large",
                "Workspace file exceeds the configured size limit.",
            )
        target = self._resolve(path, write=True)
        before = self._before_write(target)
        if target.exists() and not overwrite:
            raise WorkspaceRuntimeError(
                "workspace_file_exists",
                "Workspace file already exists; explicitly allow overwrite.",
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        self._restrict_directory(target.parent)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".knowflow-upload-",
            dir=target.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            self._restrict_file(temporary)
            temporary.replace(target)
            self._restrict_file(target)
        finally:
            temporary.unlink(missing_ok=True)
        if self.context is not None:
            self.context.record_change(
                target,
                before=before,
                after=payload,
                operation="write",
            )
        return {"path": path, "writtenBytes": len(payload)}

    def delete_file(self, path: str) -> None:
        target = self.file_path(path)
        target.unlink()

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
        before = self._before_write(target)
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
        change = None
        if self.context is not None:
            change = self.context.record_change(
                target,
                before=before,
                after=encoded,
                operation="write",
            )
        diff = self.context.diff(path) if self.context is not None else {"files": []}
        file_summary = next((item for item in diff.get("files", []) if item.get("path") == path), None)
        output = {
            "path": path,
            "writtenBytes": len(encoded),
            "operationId": change.get("id") if change else None,
            "addedLines": (file_summary or {}).get("added", 0),
            "removedLines": (file_summary or {}).get("removed", 0),
        }
        return ToolHandlerResult(
            output=output,
            audit_output=output,
        )

    def edit_text(
        self,
        path: str,
        old_text: str,
        new_text: str,
        *,
        replace_all: bool,
    ) -> ToolHandlerResult:
        target = self._resolve(path, write=True)
        if not target.is_file():
            raise WorkspaceRuntimeError("workspace_file_missing", "Workspace file was not found.")
        before = target.read_bytes()
        if len(before) > self.max_file_bytes or b"\x00" in before:
            raise WorkspaceRuntimeError("workspace_file_binary", "The workspace file is not editable text.")
        try:
            content = before.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceRuntimeError("workspace_file_encoding", "Workspace text files must use UTF-8.") from exc
        occurrences = content.count(old_text)
        if occurrences == 0:
            raise WorkspaceRuntimeError("workspace_edit_not_found", "The requested text was not found.")
        if occurrences > 1 and not replace_all:
            raise WorkspaceRuntimeError(
                "workspace_edit_ambiguous",
                "The requested text occurs more than once; provide more context or enable replace_all.",
            )
        updated = content.replace(old_text, new_text, -1 if replace_all else 1)
        return self.write_text(path, updated, overwrite=True)


class SrtSandboxRunner:
    def __init__(
        self,
        workspace: WorkspaceRuntime,
        *,
        command: str = "srt",
        shell: str = "bash",
        limit_command: str = "prlimit",
        timeout_seconds: int = 60,
        max_output_bytes: int = 1_000_000,
        memory_mb: int = 1024,
        max_processes: int = 128,
        max_file_bytes: int = 100 * 1024 * 1024,
        platform: str = sys.platform,
        process_factory: Callable[..., Any] = subprocess.Popen,
        progress_interval_seconds: float = 0.1,
    ) -> None:
        self.workspace = workspace
        self.command = str(command or "srt")
        self.shell = str(shell or "bash")
        self.limit_command = str(limit_command or "prlimit")
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_output_bytes = max(1_024, int(max_output_bytes))
        self.memory_bytes = max(128, int(memory_mb)) * 1024 * 1024
        self.max_processes = max(16, int(max_processes))
        self.max_file_bytes = max(1024 * 1024, int(max_file_bytes))
        self.platform = str(platform)
        self._process_factory = process_factory
        self.progress_interval_seconds = max(
            0.05,
            float(progress_interval_seconds),
        )

    def available(self) -> bool:
        return self.platform.startswith("linux") and bool(
            shutil.which(self.command) or Path(self.command).is_file()
        )

    def diagnostics(self, *, smoke: bool = True) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = [
            {
                "name": "platform",
                "ready": self.platform.startswith("linux"),
                "detail": self.platform,
            }
        ]
        commands = (
            ("srt", self.command),
            ("shell", self.shell),
            ("limiter", self.limit_command),
            ("bubblewrap", "bwrap"),
            ("ripgrep", "rg"),
            ("socat", "socat"),
        )
        for name, command in commands:
            resolved = shutil.which(command) or (
                str(Path(command)) if Path(command).is_file() else ""
            )
            checks.append(
                {
                    "name": name,
                    "ready": bool(resolved),
                    "detail": resolved or f"未找到{command}",
                }
            )
        if not smoke or not all(bool(item["ready"]) for item in checks):
            return checks
        try:
            result = self.run(
                "printf knowflow-sandbox-ok",
                timeout_seconds=10,
            )
            ready = (
                result.exit_code == 0
                and result.stdout == "knowflow-sandbox-ok"
            )
            detail = "SRT隔离执行成功" if ready else (
                self._tail(result.stderr or result.stdout, lines=2, limit=200)
                or f"退出码{result.exit_code}"
            )
        except Exception as exc:
            ready = False
            detail = str(exc).splitlines()[0][:200] or type(exc).__name__
        checks.append(
            {
                "name": "sandbox_smoke",
                "ready": ready,
                "detail": detail,
            }
        )
        return checks

    def _safe_environment(self) -> dict[str, str]:
        allowed = {
            "PATH",
            "LANG",
            "LC_ALL",
            "LC_CTYPE",
            "TEMP",
            "TMP",
            "TMPDIR",
        }
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in allowed
        }
        temporary = self.workspace.root / ".tmp"
        temporary.mkdir(parents=True, exist_ok=True)
        self.workspace._restrict_directory(temporary)
        environment["HOME"] = str(self.workspace.root)
        environment["TMPDIR"] = str(temporary)
        environment["TMP"] = str(temporary)
        environment["TEMP"] = str(temporary)
        return environment

    @staticmethod
    def _tail(value: str, *, lines: int = 5, limit: int = 4_000) -> str:
        selected = value.splitlines()[-max(1, int(lines)) :]
        text = "\n".join(selected)
        return text if len(text) <= limit else text[-limit:]

    @staticmethod
    def _append_bounded(current: str, chunk: str, limit: int) -> str:
        value = current + chunk
        return value if len(value) <= limit else value[-limit:]

    def _terminate_process(self, process: Any) -> None:
        if process.poll() is not None:
            return
        used_group = False
        if os.name != "nt" and self.platform.startswith("linux"):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                used_group = True
            except (AttributeError, OSError, ProcessLookupError):
                pass
        if not used_group:
            try:
                process.terminate()
            except (AttributeError, OSError):
                pass
        try:
            process.wait(timeout=0.75)
            return
        except (subprocess.TimeoutExpired, AttributeError):
            pass
        if os.name != "nt" and self.platform.startswith("linux"):
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                return
            except (AttributeError, OSError, ProcessLookupError):
                pass
        try:
            process.kill()
        except (AttributeError, OSError):
            pass

    def _progress_payload(
        self,
        *,
        stdout: str,
        stderr: str,
        elapsed_seconds: float,
        total_lines: int,
        total_bytes: int,
        timeout_seconds: int,
    ) -> dict[str, Any]:
        combined = "\n".join(
            part for part in (stdout.rstrip(), stderr.rstrip()) if part
        )
        return {
            "output": self._tail(combined),
            "stdout": self._tail(stdout),
            "stderr": self._tail(stderr),
            "elapsedSeconds": round(max(0.0, elapsed_seconds), 1),
            "totalLines": max(0, int(total_lines)),
            "totalBytes": max(0, int(total_bytes)),
            "timeoutSeconds": max(1, int(timeout_seconds)),
        }

    def run(
        self,
        command: str,
        *,
        timeout_seconds: int,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> SandboxCommandResult:
        if not self.available():
            raise WorkspaceRuntimeError(
                "sandbox_runtime_unavailable",
                "Linux Anthropic Sandbox Runtime is not available.",
            )
        workspace_root = self.workspace.root.resolve()
        allowed_roots = [path.resolve() for path in self.workspace.allowed_roots]
        denied_read = [
            str(path)
            for path in (Path.home().resolve(), Path.cwd().resolve())
            if path != workspace_root
            and not any(
                WorkspaceContext._inside(allowed, path)
                for allowed in allowed_roots
            )
        ]
        denied_read.extend(["/etc/knowflow-ai", "/proc"])
        settings = {
            "filesystem": {
                "denyRead": [
                    str(path) for path in denied_read
                ],
                "allowRead": [str(path) for path in allowed_roots],
                "allowWrite": [str(path) for path in allowed_roots],
                "denyWrite": [
                    denied
                    for path in allowed_roots
                    for denied in (str(path / ".git"), str(path / ".env"))
                ],
            },
            "network": {
                "allowedDomains": [],
                "deniedDomains": [],
            },
        }
        settings_path = None
        process = None
        try:
            temporary_root = self.workspace.root / ".tmp"
            temporary_root.mkdir(parents=True, exist_ok=True)
            self.workspace._restrict_directory(temporary_root)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                suffix=".json",
                delete=False,
                dir=temporary_root,
            ) as handle:
                json.dump(settings, handle, ensure_ascii=False)
                settings_path = handle.name
            try:
                Path(settings_path).chmod(0o600)
            except OSError:
                pass
            timeout = min(self.timeout_seconds, max(1, int(timeout_seconds)))
            argv = [
                self.command,
                "--settings",
                settings_path,
                self.limit_command,
                f"--cpu={timeout}",
                f"--as={self.memory_bytes}",
                f"--nproc={self.max_processes}",
                f"--fsize={self.max_file_bytes}",
                "--",
                self.shell,
                "--noprofile",
                "--norc",
                "-c",
                str(command),
            ]
            process = self._process_factory(
                argv,
                cwd=self.workspace.root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._safe_environment(),
                bufsize=1,
                start_new_session=(
                    os.name != "nt" and self.platform.startswith("linux")
                ),
            )
            output_queue: Queue[tuple[str, str | None]] = Queue()

            def read_stream(name: str, stream: Any) -> None:
                try:
                    while True:
                        chunk = stream.readline(4_096)
                        if not chunk:
                            break
                        output_queue.put((name, str(chunk)))
                finally:
                    output_queue.put((name, None))
                    try:
                        stream.close()
                    except (AttributeError, OSError):
                        pass

            readers = [
                Thread(
                    target=read_stream,
                    args=(name, stream),
                    daemon=True,
                    name=f"knowflow-srt-{name}",
                )
                for name, stream in (
                    ("stdout", process.stdout),
                    ("stderr", process.stderr),
                )
            ]
            for reader in readers:
                reader.start()

            started = time.monotonic()
            last_progress = 0.0
            stdout = ""
            stderr = ""
            total_lines = 0
            total_bytes = 0
            closed_streams = 0
            cancelled = False
            timed_out = False
            changed = False
            while closed_streams < 2 or process.poll() is None:
                try:
                    name, chunk = output_queue.get(timeout=0.05)
                except Empty:
                    name, chunk = "", ""
                if chunk is None:
                    closed_streams += 1
                elif chunk:
                    total_lines += chunk.count("\n")
                    total_bytes += len(chunk.encode("utf-8", errors="replace"))
                    if name == "stdout":
                        stdout = self._append_bounded(
                            stdout,
                            chunk,
                            self.max_output_bytes,
                        )
                    else:
                        stderr = self._append_bounded(
                            stderr,
                            chunk,
                            self.max_output_bytes,
                        )
                    changed = True
                elapsed = time.monotonic() - started
                if cancel_check is not None and cancel_check():
                    cancelled = True
                    self._terminate_process(process)
                elif elapsed >= timeout:
                    timed_out = True
                    self._terminate_process(process)
                now = time.monotonic()
                if progress_callback is not None and (
                    changed
                    and now - last_progress >= self.progress_interval_seconds
                ):
                    progress_callback(
                        self._progress_payload(
                            stdout=stdout,
                            stderr=stderr,
                            elapsed_seconds=elapsed,
                            total_lines=(
                                total_lines
                                + int(bool(stdout) and not stdout.endswith("\n"))
                                + int(bool(stderr) and not stderr.endswith("\n"))
                            ),
                            total_bytes=total_bytes,
                            timeout_seconds=timeout,
                        )
                    )
                    last_progress = now
                    changed = False
                if (cancelled or timed_out) and process.poll() is not None:
                    break

            for reader in readers:
                reader.join(timeout=0.5)
            while True:
                try:
                    name, chunk = output_queue.get_nowait()
                except Empty:
                    break
                if not chunk:
                    continue
                total_lines += chunk.count("\n")
                total_bytes += len(chunk.encode("utf-8", errors="replace"))
                if name == "stdout":
                    stdout = self._append_bounded(
                        stdout,
                        chunk,
                        self.max_output_bytes,
                    )
                else:
                    stderr = self._append_bounded(
                        stderr,
                        chunk,
                        self.max_output_bytes,
                    )
            elapsed = time.monotonic() - started
            reported_lines = (
                total_lines
                + int(bool(stdout) and not stdout.endswith("\n"))
                + int(bool(stderr) and not stderr.endswith("\n"))
            )
            if progress_callback is not None:
                progress_callback(
                    self._progress_payload(
                        stdout=stdout,
                        stderr=stderr,
                        elapsed_seconds=elapsed,
                        total_lines=reported_lines,
                        total_bytes=total_bytes,
                        timeout_seconds=timeout,
                    )
                )
            try:
                return_code = int(process.wait(timeout=0.5))
            except subprocess.TimeoutExpired:
                self._terminate_process(process)
                return_code = int(process.wait(timeout=0.5))
            return SandboxCommandResult(
                exit_code=(130 if cancelled else 124 if timed_out else return_code),
                stdout=stdout,
                stderr=stderr,
                timed_out=timed_out,
                cancelled=cancelled,
                elapsed_seconds=round(elapsed, 3),
                total_lines=reported_lines,
                total_bytes=total_bytes,
            )
        finally:
            if process is not None and process.poll() is None:
                self._terminate_process(process)
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
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
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
        risk="write",
        destructive=False,
        concurrency_safe=False,
        interrupt_behavior="block",
        engine_names={"langgraph"},
        trace_kind="workspace",
        search_hint="write or update local project files",
    )
    registered.append("write_workspace_file")
    registry.register(
        name="edit_workspace_file",
        description=(
            "Replace one exact UTF-8 text fragment in an existing workspace "
            "file. Prefer this over rewriting the whole file."
        ),
        arguments_model=EditWorkspaceFileArguments,
        handler=lambda args: workspace.edit_text(
            args.path,
            args.old_text,
            args.new_text,
            replace_all=args.replace_all,
        ),
        read_only=False,
        risk="write",
        destructive=False,
        concurrency_safe=False,
        interrupt_behavior="block",
        engine_names={"langgraph"},
        trace_kind="workspace",
        search_hint="make a precise edit to an existing local text file",
    )
    registered.append("edit_workspace_file")
    if sandbox is not None and sandbox.available():
        registry.register(
            name="run_sandbox_command",
            description=(
                "Run a Bash command inside Anthropic Sandbox Runtime on Linux "
                "with workspace-only writes and no network access."
            ),
            arguments_model=RunSandboxCommandArguments,
            handler=lambda args: sandbox.run(
                args.command,
                timeout_seconds=args.timeout_seconds,
                progress_callback=progress_callback,
                cancel_check=cancel_check,
            ).__dict__,
            read_only=False,
            risk="execute",
            destructive=True,
            concurrency_safe=False,
            interrupt_behavior="cancel",
            engine_names={"langgraph"},
            trace_kind="sandbox",
            search_hint="run tests builds and Bash commands safely",
        )
        registered.append("run_sandbox_command")
    return tuple(registered)
