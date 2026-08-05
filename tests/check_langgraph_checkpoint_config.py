from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        relative = Path("data") / "langgraph-config-test" / "checkpoints.sqlite3"
        expected = (ROOT / relative).resolve()
        expected.unlink(missing_ok=True)
        expected.parent.rmdir() if expected.parent.exists() else None

        os.environ["KNOWFLOW_LANGGRAPH_CHECKPOINT_DB"] = str(relative)
        sys.path.insert(0, str(BACKEND))

        from knowflow.config import LANGGRAPH_CHECKPOINT_DB

        assert LANGGRAPH_CHECKPOINT_DB == expected
        assert not expected.exists()
        assert not expected.parent.exists()

        absolute = Path(temporary) / "nested" / "absolute.sqlite3"
        source = (BACKEND / "knowflow" / "config.py").read_text(
            encoding="utf-8"
        )
        assert "KNOWFLOW_LANGGRAPH_CHECKPOINT_DB" in source
        assert "runtime_path(" in source
        assert not absolute.exists()

    requirements = (BACKEND / "requirements.txt").read_text(
        encoding="utf-8"
    )
    assert "langgraph-checkpoint-sqlite==3.1.0" in requirements

    print("LangGraph checkpoint path is lazy and version-pinned")


if __name__ == "__main__":
    main()
