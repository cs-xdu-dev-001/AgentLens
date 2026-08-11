from __future__ import annotations

from pathlib import Path
import sys
from threading import Event
import time
from datetime import datetime, timezone

from sqlalchemy import text


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.database import Database  # noqa: E402
from knowflow.services.agent_event_store import AgentEventStore  # noqa: E402
from knowflow.services.agent_run_coordinator import AgentRunCoordinator  # noqa: E402
from knowflow.services.agent_run_store import AgentRunStore  # noqa: E402


def wait_finished(coordinator: AgentRunCoordinator, run_id: str) -> None:
    for _ in range(100):
        if not coordinator.is_active(run_id):
            return
        time.sleep(0.01)
    raise AssertionError(f"Agent run did not finish: {run_id}")


def main() -> None:
    db_path = ROOT / "data" / "test-dbs" / "agent-event-store.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    database = Database(f"sqlite:///{db_path.as_posix()}")
    runs = AgentRunStore(database=database)
    events = AgentEventStore(database=database)
    coordinator = AgentRunCoordinator(event_store=events)
    runs.create_run(
        user_id=1,
        session_id="session-event-store",
        user_message_id=1,
        goal_summary="验证事件重放",
        trigger_mode="auto",
        run_id="run_event_store",
    )

    completed = Event()
    delivered: list[dict] = []

    def first_turn(cancel_event, publish) -> None:
        del cancel_event
        delivered.append(publish({"type": "run_started"}))
        delivered.append(publish({
            "type": "text_delta",
            "text": "不落盘的增量",
        }))
        delivered.append(publish({
            "type": "answer",
            "content": "结果 api_key=secret-value-123456",
            "final": True,
        }))
        delivered.append(publish({
            "type": "done",
            "status": "completed",
        }))
        completed.set()

    assert coordinator.start("run_event_store", first_turn)
    assert completed.wait(1)
    wait_finished(coordinator, "run_event_store")
    replay = events.list_after(1, "run_event_store")
    assert [item["eventName"] for item in replay] == [
        "run.started",
        "message.completed",
        "run.completed",
    ]
    assert [item["sequence"] for item in replay] == [1, 3, 4]
    assert [item["eventId"] for item in replay] == [
        delivered[index]["eventId"] for index in (0, 2, 3)
    ]
    assert "secret-value" not in str(replay)
    assert events.list_after(2, "run_event_store") == []
    assert events.list_after(
        1,
        "run_event_store",
        after_sequence=3,
    )[0]["sequence"] == 4

    resumed = Event()

    def second_turn(cancel_event, publish) -> None:
        del cancel_event
        publish({"type": "approval_required", "status": "waiting"})
        resumed.set()

    assert coordinator.start("run_event_store", second_turn)
    assert resumed.wait(1)
    wait_finished(coordinator, "run_event_store")
    replay = events.list_after(1, "run_event_store")
    assert replay[-1]["eventName"] == "approval.required"
    assert replay[-1]["sequence"] == 5

    runs.create_run(
        user_id=1,
        session_id="session-worker-failure",
        user_message_id=2,
        goal_summary="验证异常终态",
        trigger_mode="auto",
        run_id="run_worker_failure",
    )

    def failed_turn(cancel_event, publish) -> None:
        del cancel_event, publish
        raise RuntimeError("api_key=must-not-leak")

    assert coordinator.start("run_worker_failure", failed_turn)
    wait_finished(coordinator, "run_worker_failure")
    failure_events = events.list_after(1, "run_worker_failure")
    assert failure_events[-1]["eventName"] == "error.raised"
    assert failure_events[-1]["error"]["code"] == "agent_run_failed"
    assert "must-not-leak" not in str(failure_events)

    runs.create_run(
        user_id=1,
        session_id="session-expired-events",
        user_message_id=3,
        goal_summary="验证过期事件清理",
        trigger_mode="auto",
        run_id="run_expired_events",
    )
    runs.transition_run(1, "run_expired_events", "running")
    runs.transition_run(1, "run_expired_events", "completed")
    events.append(
        "run_expired_events",
        {
            "type": "done",
            "sequence": 1,
            "status": "completed",
        },
    )
    runs.create_run(
        user_id=1,
        session_id="session-active-events",
        user_message_id=4,
        goal_summary="验证活动事件保留",
        trigger_mode="auto",
        run_id="run_active_events",
    )
    events.append(
        "run_active_events",
        {"type": "run_started", "sequence": 1},
    )
    with database.engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE agent_run
                SET updated_at='2024-01-01 00:00:00'
                WHERE id IN (
                  'run_expired_events', 'run_active_events'
                )
                """
            )
        )
    removed = events.cleanup_expired(
        now=datetime(2026, 8, 11, tzinfo=timezone.utc),
    )
    assert removed == 1, removed
    assert events.list_after(1, "run_expired_events") == []
    assert events.list_after(1, "run_active_events"), (
        "Active Agent runs must not lose replay events."
    )

    print("durable Agent event replay checks passed")


if __name__ == "__main__":
    main()
