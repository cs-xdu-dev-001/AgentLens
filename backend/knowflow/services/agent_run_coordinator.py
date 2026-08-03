from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from queue import Queue
from threading import Event, Lock, Thread
from typing import Any


@dataclass
class ActiveAgentRun:
    cancel_event: Event = field(default_factory=Event)
    subscribers: list[Queue] = field(default_factory=list)
    thread: Thread | None = None


class AgentRunCoordinator:
    def __init__(self):
        self._lock = Lock()
        self._active: dict[str, ActiveAgentRun] = {}

    def start(
        self,
        run_id: str,
        target: Callable[[Event, Callable[[dict[str, Any]], None]], None],
    ) -> bool:
        with self._lock:
            if run_id in self._active:
                return False
            active = ActiveAgentRun()
            self._active[run_id] = active

        def publish(event: dict[str, Any]) -> None:
            self.publish(run_id, event)

        def worker() -> None:
            try:
                target(active.cancel_event, publish)
            finally:
                self.finish(run_id)

        thread = Thread(target=worker, daemon=True)
        active.thread = thread
        thread.start()
        return True

    def finish(self, run_id: str) -> None:
        with self._lock:
            active = self._active.pop(run_id, None)
            subscribers = list(active.subscribers) if active else []
        for subscriber in subscribers:
            subscriber.put({"type": "stream_closed", "runId": run_id})

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._active

    def cancel(self, run_id: str) -> bool:
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                return False
            active.cancel_event.set()
            return True

    def cancel_and_wait(
        self,
        run_id: str,
        *,
        timeout_seconds: float = 5.0,
    ) -> bool:
        """Request cancellation and wait until the worker releases the run."""
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                return True
            active.cancel_event.set()
            thread = active.thread
        if thread is not None:
            thread.join(max(0.0, float(timeout_seconds)))
        return not self.is_active(run_id)

    def subscribe(self, run_id: str) -> Queue | None:
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                return None
            subscriber: Queue = Queue()
            active.subscribers.append(subscriber)
            return subscriber

    def unsubscribe(self, run_id: str, subscriber: Queue) -> None:
        with self._lock:
            active = self._active.get(run_id)
            if active and subscriber in active.subscribers:
                active.subscribers.remove(subscriber)

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            active = self._active.get(run_id)
            subscribers = list(active.subscribers) if active else []
        for subscriber in subscribers:
            subscriber.put(dict(event))
