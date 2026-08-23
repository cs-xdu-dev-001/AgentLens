from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, TYPE_CHECKING


if TYPE_CHECKING:
    from langgraph.checkpoint.sqlite import SqliteSaver


class LangGraphCheckpointError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class LangGraphCheckpointStore:
    def __init__(
        self,
        path: Path,
        *,
        timeout_seconds: float = 30.0,
        allow_volatile_fallback: bool = False,
    ):
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = max(0.1, float(timeout_seconds))
        self.allow_volatile_fallback = bool(allow_volatile_fallback)

    @staticmethod
    def thread_id(user_id: int, run_id: str) -> str:
        owner_id = int(user_id)
        identifier = str(run_id or "").strip()
        if owner_id <= 0 or not identifier:
            raise ValueError("A valid user_id and run_id are required.")
        return f"user:{owner_id}:run:{identifier}"

    @contextmanager
    def open(
        self,
        *,
        create: bool = True,
        on_fallback: Callable[[LangGraphCheckpointError], None] | None = None,
    ) -> Iterator[SqliteSaver | None]:
        if not create and not self.path.is_file():
            yield None
            return

        connection: sqlite3.Connection | None = None
        try:
            from langgraph.checkpoint.serde.jsonplus import (
                JsonPlusSerializer,
            )
            from langgraph.checkpoint.sqlite import SqliteSaver

            try:
                if create:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self._set_mode(self.path.parent, 0o750)
                connection = sqlite3.connect(
                    self.path,
                    timeout=self.timeout_seconds,
                    check_same_thread=False,
                )
                self._set_mode(self.path, 0o600)
                self._assert_healthy(connection)
            except (OSError, sqlite3.Error) as exc:
                failure = self._public_error(exc)
                if not (create and self.allow_volatile_fallback):
                    raise failure from exc
                if connection is not None:
                    connection.close()
                connection = sqlite3.connect(
                    ":memory:",
                    timeout=self.timeout_seconds,
                    check_same_thread=False,
                )
                if on_fallback is not None:
                    on_fallback(failure)
            serializer = JsonPlusSerializer(
                allowed_msgpack_modules=None,
                pickle_fallback=False,
            )
            yield SqliteSaver(connection, serde=serializer)
        except LangGraphCheckpointError:
            raise
        except (ImportError, OSError, sqlite3.Error) as exc:
            raise self._public_error(exc) from exc
        finally:
            if connection is not None:
                connection.close()

    def delete_threads(self, user_id: int, run_ids: list[str]) -> None:
        thread_ids = tuple(
            dict.fromkeys(
                self.thread_id(user_id, run_id)
                for run_id in run_ids
                if str(run_id or "").strip()
            )
        )
        if not thread_ids:
            return

        with self.open(create=False) as saver:
            if saver is None:
                return
            saver.setup()
            with saver.conn:
                saver.conn.executemany(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    ((thread_id,) for thread_id in thread_ids),
                )
                saver.conn.executemany(
                    "DELETE FROM writes WHERE thread_id = ?",
                    ((thread_id,) for thread_id in thread_ids),
                )

    def diagnostic(self) -> dict[str, object]:
        """Check dependency and path health without creating a checkpoint file."""
        connection: sqlite3.Connection | None = None
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401

            if self.path.is_file():
                connection = sqlite3.connect(
                    self.path,
                    timeout=self.timeout_seconds,
                    check_same_thread=False,
                )
                self._assert_healthy(connection)
                detail = f"可读写：{self.path}"
            else:
                candidate = self.path.parent
                while not candidate.exists() and candidate.parent != candidate:
                    candidate = candidate.parent
                if not candidate.is_dir() or not os.access(
                    candidate,
                    os.W_OK | os.X_OK,
                ):
                    raise PermissionError("checkpoint parent is not writable")
                detail = f"将在首次任务时创建：{self.path}"
            return {
                "name": "langgraph_checkpoint",
                "ready": True,
                "detail": detail,
            }
        except (ImportError, OSError, sqlite3.Error) as exc:
            failure = self._public_error(exc)
            return {
                "name": "langgraph_checkpoint",
                "ready": False,
                "detail": f"{failure.message} 路径：{self.path}",
                "errorCode": failure.code,
            }
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _set_mode(path: Path, mode: int) -> None:
        if os.name != "nt":
            path.chmod(mode)

    @staticmethod
    def _assert_healthy(connection: sqlite3.Connection) -> None:
        row = connection.execute("PRAGMA quick_check").fetchone()
        if not row or str(row[0]).lower() != "ok":
            raise sqlite3.DatabaseError("checkpoint database is malformed")

    @staticmethod
    def _public_error(exc: Exception) -> LangGraphCheckpointError:
        if isinstance(exc, ImportError):
            return LangGraphCheckpointError(
                "langgraph_checkpoint_dependency_missing",
                "LangGraph checkpoint依赖不完整。请运行knowflow update后重试。",
            )
        marker = str(exc).lower()
        if isinstance(exc, PermissionError) or "unable to open database file" in marker:
            return LangGraphCheckpointError(
                "langgraph_checkpoint_permission_denied",
                "LangGraph checkpoint没有读写权限。请运行knowflow doctor --cli检查本地数据目录；修复权限后重试。",
            )
        if isinstance(exc, sqlite3.DatabaseError) and any(
            value in marker for value in ("malformed", "not a database")
        ):
            return LangGraphCheckpointError(
                "langgraph_checkpoint_corrupt",
                "LangGraph checkpoint数据库损坏。请先备份本地AgentLens数据，再移走损坏的checkpoint文件。",
            )
        if isinstance(exc, sqlite3.OperationalError) and "locked" in marker:
            return LangGraphCheckpointError(
                "langgraph_checkpoint_locked",
                "LangGraph checkpoint正被其他进程占用。请关闭其他AgentLens进程后重试。",
            )
        return LangGraphCheckpointError(
            "langgraph_checkpoint_unavailable",
            "LangGraph checkpoint存储暂不可用。请运行knowflow doctor --cli检查本地运行环境。",
        )
