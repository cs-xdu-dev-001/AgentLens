from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any

from pydantic import BaseModel, Field


_RESULT_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


class ReadToolResultArguments(BaseModel):
    result_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=12_000, ge=1, le=20_000)


@dataclass(frozen=True)
class StoredToolResult:
    result_id: str
    original_characters: int
    stored_characters: int
    complete: bool


class ToolResultStore:
    _cleanup_lock = threading.Lock()
    _last_cleanup: dict[Path, float] = {}

    def __init__(
        self,
        root: Path,
        *,
        user_id: int,
        run_id: str,
        max_storage_chars: int = 2_000_000,
        retention_seconds: int = 7 * 24 * 60 * 60,
    ) -> None:
        self.root = Path(root).resolve()
        self.user_id = int(user_id)
        self.run_id = str(run_id)
        self.max_storage_chars = max(1, int(max_storage_chars))
        self.retention_seconds = max(60, int(retention_seconds))
        self.root.mkdir(parents=True, exist_ok=True)
        self._restrict_directory(self.root)
        self._cleanup_if_due()
        namespace = hashlib.sha256(
            f"{self.user_id}\0{self.run_id}".encode("utf-8")
        ).hexdigest()[:32]
        self._run_root = (self.root / namespace).resolve()
        self._run_root.mkdir(parents=True, exist_ok=True)
        self._restrict_directory(self._run_root)

    @staticmethod
    def _restrict_directory(path: Path) -> None:
        try:
            path.chmod(0o750)
        except OSError:
            pass

    @staticmethod
    def _restrict_file(path: Path) -> None:
        try:
            path.chmod(0o600)
        except OSError:
            pass

    def _result_id(self, call_id: str, tool_name: str) -> str:
        return hashlib.sha256(
            (
                f"{self.user_id}\0{self.run_id}\0"
                f"{call_id}\0{tool_name}"
            ).encode("utf-8")
        ).hexdigest()[:32]

    def _cleanup_if_due(self) -> None:
        current = time.monotonic()
        with self._cleanup_lock:
            previous = self._last_cleanup.get(self.root, 0.0)
            if current - previous < 300:
                return
            self._last_cleanup[self.root] = current
        self.cleanup_expired()

    def cleanup_expired(
        self,
        *,
        now: float | None = None,
        max_directories: int = 500,
    ) -> int:
        cutoff = (time.time() if now is None else float(now)) - self.retention_seconds
        removed = 0
        for index, candidate in enumerate(self.root.iterdir()):
            if index >= max(1, int(max_directories)):
                break
            try:
                directory = candidate.resolve()
                if directory.parent != self.root or not directory.is_dir():
                    continue
                if directory.stat().st_mtime >= cutoff:
                    continue
                removable = True
                for child in directory.iterdir():
                    target = child.resolve()
                    if target.parent != directory or not target.is_file():
                        removable = False
                        break
                    target.unlink()
                if removable:
                    directory.rmdir()
                    removed += 1
            except OSError:
                continue
        return removed

    def _path(self, result_id: str) -> Path:
        if not _RESULT_ID_PATTERN.fullmatch(str(result_id or "")):
            raise ValueError("Invalid stored tool result identifier.")
        path = (self._run_root / f"{result_id}.json").resolve()
        if path.parent != self._run_root:
            raise ValueError("Invalid stored tool result path.")
        return path

    def store(
        self,
        *,
        call_id: str,
        tool_name: str,
        output: dict[str, Any],
    ) -> StoredToolResult:
        serialized = json.dumps(output, ensure_ascii=False)
        stored = serialized[: self.max_storage_chars]
        result_id = self._result_id(call_id, tool_name)
        path = self._path(result_id)
        temporary = path.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_text(stored, encoding="utf-8")
        self._restrict_file(temporary)
        temporary.replace(path)
        self._restrict_file(path)
        return StoredToolResult(
            result_id=result_id,
            original_characters=len(serialized),
            stored_characters=len(stored),
            complete=len(stored) == len(serialized),
        )

    def compact(
        self,
        *,
        call_id: str,
        tool_name: str,
        output: dict[str, Any],
        max_result_size_chars: int,
    ) -> dict[str, Any]:
        serialized = json.dumps(output, ensure_ascii=False)
        limit = max(1, int(max_result_size_chars))
        if len(serialized) <= limit:
            return output
        stored = self.store(
            call_id=call_id,
            tool_name=tool_name,
            output=output,
        )
        preview_size = max(1, min(limit, 4_000))
        return {
            "storedToolResult": {
                "resultId": stored.result_id,
                "originalCharacters": stored.original_characters,
                "storedCharacters": stored.stored_characters,
                "complete": stored.complete,
            },
            "preview": serialized[:preview_size],
            "instruction": (
                "Call read_tool_result with result_id and an offset "
                "to read the stored result in bounded chunks."
            ),
        }

    def read(
        self,
        result_id: str,
        *,
        offset: int = 0,
        limit: int = 12_000,
    ) -> dict[str, Any]:
        start = max(0, int(offset))
        page_size = max(1, min(20_000, int(limit)))
        path = self._path(result_id)
        if not path.is_file():
            raise FileNotFoundError("Stored tool result was not found.")
        content = path.read_text(encoding="utf-8")
        end = min(len(content), start + page_size)
        return {
            "resultId": result_id,
            "offset": start,
            "nextOffset": end if end < len(content) else None,
            "content": content[start:end],
            "eof": end >= len(content),
        }
