from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from langgraph.checkpoint.base import empty_checkpoint

from knowflow.services.langgraph_checkpoint import (
    LangGraphCheckpointError,
    LangGraphCheckpointStore,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        database = root / "nested" / "checkpoints.sqlite3"
        store = LangGraphCheckpointStore(database)

        with store.open(create=False) as saver:
            assert saver is None
        assert not database.exists()
        assert not database.parent.exists()

        with store.open() as saver:
            assert saver is not None
            assert saver.serde.pickle_fallback is False
            assert saver.serde._allowed_msgpack_modules is None
            saver.put(
                {
                    "configurable": {
                        "thread_id": store.thread_id(
                            7, "run_checkpoint_test"
                        ),
                        "checkpoint_ns": "",
                    }
                },
                empty_checkpoint(),
                {},
                {},
            )

        assert database.is_file()
        healthy = store.diagnostic()
        assert healthy["ready"] is True
        assert healthy["name"] == "langgraph_checkpoint"
        if os.name != "nt":
            assert database.parent.stat().st_mode & 0o777 == 0o750
            assert database.stat().st_mode & 0o777 == 0o600

        store.delete_threads(7, ["run_checkpoint_test"])
        store.delete_threads(7, ["run_checkpoint_test"])
        with store.open(create=False) as saver:
            assert saver is not None
            assert (
                saver.get_tuple(
                    {
                        "configurable": {
                            "thread_id": store.thread_id(
                                7, "run_checkpoint_test"
                            )
                        }
                    }
                )
                is None
            )

        missing = root / "missing" / "checkpoints.sqlite3"
        LangGraphCheckpointStore(missing).delete_threads(7, ["run_missing"])
        assert not missing.exists()
        assert not missing.parent.exists()

        with patch(
            "knowflow.services.langgraph_checkpoint.sqlite3.connect",
            side_effect=sqlite3.OperationalError("database unavailable"),
        ):
            try:
                with store.open():
                    raise AssertionError("unavailable database should fail")
            except LangGraphCheckpointError as exc:
                assert exc.code == "langgraph_checkpoint_unavailable"
                assert "database unavailable" not in exc.message

        original_connect = sqlite3.connect
        fallback_events: list[LangGraphCheckpointError] = []

        def permission_then_memory(path, *args, **kwargs):
            if str(path) != ":memory:":
                raise PermissionError("synthetic permission failure")
            return original_connect(path, *args, **kwargs)

        fallback_store = LangGraphCheckpointStore(
            root / "readonly" / "checkpoints.sqlite3",
            allow_volatile_fallback=True,
        )
        with patch(
            "knowflow.services.langgraph_checkpoint.sqlite3.connect",
            side_effect=permission_then_memory,
        ):
            with fallback_store.open(on_fallback=fallback_events.append) as saver:
                assert saver is not None
                saver.setup()
        assert len(fallback_events) == 1
        assert fallback_events[0].code == "langgraph_checkpoint_permission_denied"
        assert "doctor --cli" in fallback_events[0].message
        assert not fallback_store.path.exists()

        strict_resume_store = LangGraphCheckpointStore(
            root / "readonly" / "missing.sqlite3",
            allow_volatile_fallback=True,
        )
        with strict_resume_store.open(create=False) as saver:
            assert saver is None
        missing_status = strict_resume_store.diagnostic()
        assert missing_status["ready"] is True
        assert "首次任务" in str(missing_status["detail"])

    print("LangGraph checkpoint store is lazy, strict, and disposable")


if __name__ == "__main__":
    main()
