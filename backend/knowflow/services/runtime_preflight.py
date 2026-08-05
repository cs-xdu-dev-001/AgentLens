from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Iterable


@dataclass(frozen=True)
class RuntimePathStatus:
    name: str
    path: str
    kind: str
    ready: bool
    error: str | None = None


class RuntimePreflightError(RuntimeError):
    def __init__(self, statuses: tuple[RuntimePathStatus, ...]):
        self.statuses = statuses
        failed = ", ".join(item.name for item in statuses if not item.ready)
        super().__init__(f"Runtime storage is unavailable: {failed}")


def _set_mode(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)


def _check_directory(name: str, path: Path, *, prepare: bool) -> RuntimePathStatus:
    target = Path(path).expanduser().resolve()
    try:
        if prepare:
            target.mkdir(parents=True, exist_ok=True)
            _set_mode(target, 0o750)
        if not target.is_dir():
            raise OSError("directory does not exist")
        if not os.access(target, os.R_OK | os.W_OK | os.X_OK):
            raise PermissionError("directory is not readable and writable")
        return RuntimePathStatus(name, str(target), "directory", True)
    except OSError as exc:
        return RuntimePathStatus(
            name,
            str(target),
            "directory",
            False,
            type(exc).__name__,
        )


def _check_file(name: str, path: Path, *, prepare: bool) -> RuntimePathStatus:
    target = Path(path).expanduser().resolve()
    parent = target.parent
    try:
        if prepare:
            parent.mkdir(parents=True, exist_ok=True)
            _set_mode(parent, 0o750)
        if not parent.is_dir():
            raise OSError("parent directory does not exist")
        if not os.access(parent, os.R_OK | os.W_OK | os.X_OK):
            raise PermissionError("parent directory is not readable and writable")
        if target.exists():
            if not target.is_file():
                raise OSError("path is not a regular file")
            if not os.access(target, os.R_OK | os.W_OK):
                raise PermissionError("file is not readable and writable")
        return RuntimePathStatus(name, str(target), "file", True)
    except OSError as exc:
        return RuntimePathStatus(
            name,
            str(target),
            "file",
            False,
            type(exc).__name__,
        )


def inspect_runtime_paths(
    *,
    directories: Iterable[tuple[str, Path]],
    files: Iterable[tuple[str, Path]],
    prepare: bool = False,
) -> tuple[RuntimePathStatus, ...]:
    return tuple(
        [
            _check_directory(name, path, prepare=prepare)
            for name, path in directories
        ]
        + [_check_file(name, path, prepare=prepare) for name, path in files]
    )


def require_runtime_paths(
    *,
    directories: Iterable[tuple[str, Path]],
    files: Iterable[tuple[str, Path]],
) -> tuple[RuntimePathStatus, ...]:
    statuses = inspect_runtime_paths(
        directories=directories,
        files=files,
        prepare=True,
    )
    if any(not item.ready for item in statuses):
        raise RuntimePreflightError(statuses)
    return statuses


def require_linux_sandbox(command: str, shell: str, limit_command: str) -> None:
    if not sys.platform.startswith("linux"):
        raise RuntimeError("Sandbox execution is supported only on Linux.")
    if not (shutil.which(command) or Path(command).is_file()):
        raise RuntimeError("Anthropic Sandbox Runtime is not available.")
    if not (shutil.which(shell) or Path(shell).is_file()):
        raise RuntimeError("The configured Linux sandbox shell is not available.")
    if not (shutil.which(limit_command) or Path(limit_command).is_file()):
        raise RuntimeError("The configured Linux resource limiter is not available.")
