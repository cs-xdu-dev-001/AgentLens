from __future__ import annotations

from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.runtime_preflight import (
    inspect_runtime_paths,
    require_runtime_paths,
)


def main() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        data = root / "state"
        checkpoint = data / "langgraph" / "checkpoints.sqlite3"

        before = inspect_runtime_paths(
            directories=(("state", data),),
            files=(("checkpoint", checkpoint),),
        )
        assert all(not item.ready for item in before)
        assert not data.exists()

        ready = require_runtime_paths(
            directories=(("state", data),),
            files=(("checkpoint", checkpoint),),
        )
        assert all(item.ready for item in ready)
        assert data.is_dir()
        assert checkpoint.parent.is_dir()
        assert not checkpoint.exists()

    source = (ROOT / "backend" / "knowflow" / "config.py").read_text(
        encoding="utf-8"
    )
    assert "KNOWFLOW_DATA_DIR" in source
    assert "TOOL_RESULT_DIR.mkdir" not in source
    assert "WORKSPACE_DIR.mkdir" not in source

    print("runtime storage is lazy, configurable, and startup-gated")


if __name__ == "__main__":
    main()
