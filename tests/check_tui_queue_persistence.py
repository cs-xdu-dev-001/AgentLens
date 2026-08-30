from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import tempfile

from knowflow.tui.state import PromptQueueStore


def item(identifier: str, sequence: int) -> dict[str, object]:
    return {
        "id": identifier,
        "text": f"task {identifier}",
        "displayText": f"任务{identifier}",
        "priority": "next",
        "sequence": sequence,
        "mode": "prompt",
        "reasoningEffort": "default",
        "permissionMode": "ask",
        "attachmentPaths": [],
    }


with tempfile.TemporaryDirectory() as raw_directory:
    path = Path(raw_directory) / "queues" / "workspace.json"
    store = PromptQueueStore(path)

    assert store.sync([item("one", 1), item("two", 2)], paused=False)
    snapshot = store.load()
    assert [value["id"] for value in snapshot["items"]] == ["one", "two"]
    assert not snapshot["paused"]

    assert store.claim("one", "turn-1")
    assert store.sync([item("two", 2)], paused=False)
    claimed = store.load()
    assert [value["id"] for value in claimed["items"]] == ["one", "two"]
    assert claimed["items"][0]["lifecycle"] == "started"

    restored = store.restore()
    assert restored["recovered"] == 1
    assert restored["paused"]
    assert restored["durable"]
    assert restored["items"][0]["lifecycle"] == "queued"

    assert store.claim("one", "turn-2")
    assert store.resolve("turn-2")
    assert [value["id"] for value in store.load()["items"]] == ["two"]

    fallback = item("race", 3)
    assert store.claim("race", "turn-race", fallback_item=fallback)
    race = next(value for value in store.load()["items"] if value["id"] == "race")
    assert race["lifecycle"] == "started"
    assert race["requestId"] == "turn-race"
    assert store.resolve("turn-race")

    corrupt_path = Path(raw_directory) / "queues" / "corrupt.json"
    corrupt_path.write_text("{not-json", encoding="utf-8")
    corrupt = PromptQueueStore(corrupt_path).restore()
    assert corrupt["items"] == []
    assert corrupt["durable"] is False

    failing_path = Path(raw_directory) / "queues" / "failing.json"
    failing_store = PromptQueueStore(failing_path)
    assert failing_store.sync([item("started", 1)], paused=False)
    assert failing_store.claim("started", "turn-started")
    failing_store.save = lambda _snapshot: False  # type: ignore[method-assign]
    failed_restore = failing_store.restore()
    assert failed_restore["recovered"] == 1
    assert failed_restore["paused"] is True
    assert failed_restore["durable"] is False

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700

print("tui persistent queue checks passed")
