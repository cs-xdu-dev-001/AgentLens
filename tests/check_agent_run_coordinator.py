from __future__ import annotations

import sys
from pathlib import Path
from threading import Event


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_run_coordinator import AgentRunCoordinator


def main() -> None:
    coordinator = AgentRunCoordinator()
    started = Event()

    def cancellable(cancel_event, publish) -> None:
        del publish
        started.set()
        assert cancel_event.wait(1)

    assert coordinator.start("run_cancellable", cancellable)
    assert started.wait(1)
    assert coordinator.cancel_and_wait(
        "run_cancellable", timeout_seconds=1
    )
    assert not coordinator.is_active("run_cancellable")
    assert coordinator.cancel_and_wait("run_missing", timeout_seconds=0)

    release = Event()
    blocked_started = Event()

    def blocked(cancel_event, publish) -> None:
        del publish
        blocked_started.set()
        assert cancel_event.wait(1)
        assert release.wait(1)

    assert coordinator.start("run_blocked", blocked)
    assert blocked_started.wait(1)
    assert not coordinator.cancel_and_wait(
        "run_blocked", timeout_seconds=0.01
    )
    assert coordinator.is_active("run_blocked")
    release.set()
    assert coordinator.cancel_and_wait("run_blocked", timeout_seconds=1)

    print("agent run cancellation waits for workers before cleanup")


if __name__ == "__main__":
    main()
