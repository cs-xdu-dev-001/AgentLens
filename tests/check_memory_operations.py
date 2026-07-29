from __future__ import annotations

from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import CURRENT_SCHEMA_VERSION, Database  # noqa: E402
from knowflow.services.memory_operations import (  # noqa: E402
    MemoryOperationError,
    MemoryOperationStore,
)


def expect_code(code: str, action) -> None:
    try:
        action()
    except MemoryOperationError as exc:
        assert exc.code == code, exc.code
    else:
        raise AssertionError(f"expected {code}")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "memory-operations.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    database = Database(f"sqlite:///{db_path.as_posix()}")
    assert CURRENT_SCHEMA_VERSION == 8

    with database.engine.connect() as conn:
        columns = database.table_columns(conn, "memory_operation")
    assert {
        "id",
        "user_id",
        "session_id",
        "message_id",
        "agent_run_id",
        "kind",
        "status",
        "attempt_count",
        "next_attempt_at",
        "result_json",
        "error_code",
        "error_message",
        "started_at",
        "finished_at",
        "created_at",
        "updated_at",
    }.issubset(columns)

    store = MemoryOperationStore(database=database)
    recall_id, write_id = store.create_for_message(
        user_id=7,
        session_id="session-alice",
        message_id=11,
        agent_run_id=None,
        recalled=[
            {
                "id": "alice-memory",
                "memory": "默认使用Python。",
            }
        ],
    )
    duplicate = store.create_for_message(
        user_id=7,
        session_id="session-alice",
        message_id=11,
        agent_run_id=None,
        recalled=[],
    )
    assert duplicate == (recall_id, write_id)

    activity = store.activity_for_message(user_id=7, message_id=11)
    assert activity is not None
    assert activity["messageId"] == 11
    assert activity["summary"]["recalled"] == 1
    assert activity["operations"][0]["kind"] == "recall"
    assert activity["operations"][0]["status"] == "succeeded"
    assert activity["operations"][1]["kind"] == "write"
    assert activity["operations"][1]["status"] == "queued"
    assert store.activity_for_message(user_id=8, message_id=11) is None

    now = utcnow()
    claimed = store.claim_due(now=now)
    assert claimed is not None
    assert claimed["id"] == write_id
    assert claimed["status"] == "running"
    assert claimed["attemptCount"] == 1
    assert store.claim_due(now=now) is None

    store.reschedule(
        write_id,
        error_code="memory_upstream_unavailable",
        error_message="记忆服务暂时不可用。",
        next_attempt_at=now + timedelta(seconds=5),
    )
    assert store.claim_due(now=now + timedelta(seconds=4)) is None
    second = store.claim_due(now=now + timedelta(seconds=5))
    assert second is not None
    assert second["attemptCount"] == 2

    store.mark_failed(
        write_id,
        error_code="memory_request_rejected",
        error_message="记忆写入未完成。",
    )
    expect_code(
        "memory_operation_not_found",
        lambda: store.retry_failed(user_id=8, operation_id=write_id),
    )
    retried = store.retry_failed(user_id=7, operation_id=write_id)
    assert retried["status"] == "queued"
    assert retried["attemptCount"] == 0
    expect_code(
        "memory_operation_conflict",
        lambda: store.retry_failed(user_id=7, operation_id=write_id),
    )

    third = store.claim_due(now=utcnow() + timedelta(seconds=1))
    assert third is not None
    store.mark_succeeded(
        write_id,
        [
            {
                "event": "ADD",
                "id": "new-memory",
                "memory": "优先完善记忆可靠性。",
            }
        ],
    )
    completed = store.activity_for_message(user_id=7, message_id=11)
    assert completed is not None
    assert completed["summary"]["added"] == 1
    assert completed["operations"][1]["status"] == "succeeded"

    store.redact_memory(user_id=7, memory_id="new-memory")
    redacted = store.activity_for_message(user_id=7, message_id=11)
    assert redacted is not None
    write_items = redacted["operations"][1]["items"]
    assert write_items[0]["content"] == ""

    stale_recall, stale_write = store.create_for_message(
        user_id=7,
        session_id="session-stale",
        message_id=12,
        agent_run_id="run-stale",
        recalled=[],
    )
    del stale_recall
    stale_claim = store.claim_due(now=utcnow())
    assert stale_claim is not None and stale_claim["id"] == stale_write
    recovered = store.recover_interrupted(
        stale_before=utcnow() + timedelta(seconds=1)
    )
    assert recovered == 1
    recovered_activity = store.activity_for_message(
        user_id=7,
        message_id=12,
    )
    assert recovered_activity is not None
    assert recovered_activity["operations"][1]["status"] == "queued"

    store.redact_user(user_id=7)
    cleared = store.activity_for_message(user_id=7, message_id=11)
    assert cleared is not None
    assert all(
        item["content"] == ""
        for operation in cleared["operations"]
        for item in operation["items"]
    )

    print("durable memory operation store checks passed")


if __name__ == "__main__":
    main()
