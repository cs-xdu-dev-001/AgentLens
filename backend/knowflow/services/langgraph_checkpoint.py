from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TYPE_CHECKING


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
    ):
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = max(0.1, float(timeout_seconds))

    @contextmanager
    def open(
        self,
        *,
        create: bool = True,
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

            if create:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._set_mode(self.path.parent, 0o750)

            connection = sqlite3.connect(
                self.path,
                timeout=self.timeout_seconds,
                check_same_thread=False,
            )
            self._set_mode(self.path, 0o600)
            serializer = JsonPlusSerializer(
                allowed_msgpack_modules=None,
                pickle_fallback=False,
            )
            yield SqliteSaver(connection, serde=serializer)
        except LangGraphCheckpointError:
            raise
        except (ImportError, OSError, sqlite3.Error) as exc:
            raise LangGraphCheckpointError(
                "langgraph_checkpoint_unavailable",
                "LangGraph checkpoint存储暂不可用。",
            ) from exc
        finally:
            if connection is not None:
                connection.close()

    def delete_threads(self, run_ids: list[str]) -> None:
        thread_ids = tuple(
            dict.fromkeys(
                str(run_id).strip() for run_id in run_ids if run_id
            )
        )
        if not thread_ids:
            return

        with self.open(create=False) as saver:
            if saver is None:
                return
            for thread_id in thread_ids:
                saver.delete_thread(thread_id)

    @staticmethod
    def _set_mode(path: Path, mode: int) -> None:
        if os.name != "nt":
            path.chmod(mode)
