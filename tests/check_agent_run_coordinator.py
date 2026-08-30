from __future__ import annotations

import sys
from pathlib import Path
from threading import Event


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from knowflow.services.agent_run_coordinator import AgentRunCoordinator
import knowflow.app as app_module


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

    shutdown_started = [Event(), Event()]
    shutdown_finished = [Event(), Event()]

    def shutdown_worker(index: int):
        def worker(cancel_event, publish) -> None:
            del publish
            shutdown_started[index].set()
            assert cancel_event.wait(1)
            shutdown_finished[index].set()

        return worker

    assert coordinator.start("run_shutdown_a", shutdown_worker(0))
    assert coordinator.start("run_shutdown_b", shutdown_worker(1))
    assert all(event.wait(1) for event in shutdown_started)
    assert coordinator.shutdown(timeout_seconds=1) == ()
    assert all(event.is_set() for event in shutdown_finished)
    assert not coordinator.is_active("run_shutdown_a")
    assert not coordinator.is_active("run_shutdown_b")
    assert not coordinator.start("run_after_shutdown", shutdown_worker(0))
    coordinator.start_accepting()
    reopened_started = Event()

    def reopened_worker(cancel_event, publish) -> None:
        del publish
        reopened_started.set()
        assert cancel_event.wait(1)

    assert coordinator.start("run_after_startup", reopened_worker)
    assert reopened_started.wait(1)
    assert coordinator.cancel_and_wait("run_after_startup", timeout_seconds=1)

    blocked_shutdown_coordinator = AgentRunCoordinator()
    shutdown_blocked_started = Event()
    shutdown_blocked_release = Event()

    def shutdown_blocked(cancel_event, publish) -> None:
        del publish
        shutdown_blocked_started.set()
        assert cancel_event.wait(1)
        assert shutdown_blocked_release.wait(1)

    assert blocked_shutdown_coordinator.start(
        "run_shutdown_blocked", shutdown_blocked
    )
    assert shutdown_blocked_started.wait(1)
    assert blocked_shutdown_coordinator.shutdown(
        timeout_seconds=0.01
    ) == ("run_shutdown_blocked",)
    assert blocked_shutdown_coordinator.is_active("run_shutdown_blocked")
    assert not blocked_shutdown_coordinator.start(
        "run_during_shutdown", shutdown_blocked
    )
    try:
        blocked_shutdown_coordinator.start_accepting()
    except RuntimeError as exc:
        assert "previous workers are active" in str(exc)
    else:
        raise AssertionError("active workers must block a new app lifecycle")
    shutdown_blocked_release.set()
    assert blocked_shutdown_coordinator.cancel_and_wait(
        "run_shutdown_blocked", timeout_seconds=1
    )
    blocked_shutdown_coordinator.start_accepting()

    shutdown_calls: list[tuple[str, float | None]] = []

    class Stoppable:
        def __init__(self, name: str):
            self.name = name

        def stop(self) -> None:
            shutdown_calls.append((self.name, None))

    class Closable:
        def close(self) -> None:
            shutdown_calls.append(("memory_manager", None))

    class ShutdownCoordinator:
        def shutdown(self, *, timeout_seconds: float):
            shutdown_calls.append(("agent_runs", timeout_seconds))
            return ()

    app_module.approval_runner = Stoppable("approval_runner")
    app_module.agent_run_coordinator = ShutdownCoordinator()
    app_module.memory_operation_runner = Stoppable("memory_operation_runner")
    app_module.memory_manager = Closable()
    app_module.close_memory_runtime()
    assert shutdown_calls == [
        ("approval_runner", None),
        ("agent_runs", 5.0),
        ("memory_operation_runner", None),
        ("memory_manager", None),
    ]

    print("agent run cancellation and app shutdown wait for workers")


if __name__ == "__main__":
    main()
