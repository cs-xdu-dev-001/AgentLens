from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
from queue import Queue
from threading import Event, Lock, Thread, current_thread
from time import monotonic
from typing import Any

from .agent_event_protocol import AgentEventNormalizer
from .agent_event_store import AgentEventStore


logger = logging.getLogger(__name__)


@dataclass
class ActiveAgentRun:
    cancel_event: Event = field(default_factory=Event)
    subscribers: list[Queue] = field(default_factory=list)
    thread: Thread | None = None
    normalize_event: AgentEventNormalizer | None = None
    publish_lock: Lock = field(default_factory=Lock)


class AgentRunCoordinator:
    def __init__(self, *, event_store: AgentEventStore | None = None):
        self._lock = Lock()
        self._lifecycle_lock = Lock()
        self._active: dict[str, ActiveAgentRun] = {}
        self._shutting_down = False
        self.event_store = event_store

    def start_accepting(self) -> None:
        """Allow new workers for a fresh application lifecycle."""
        with self._lifecycle_lock:
            with self._lock:
                if self._active:
                    raise RuntimeError(
                        "Cannot accept Agent runs while previous workers are active."
                    )
                self._shutting_down = False

    def start(
        self,
        run_id: str,
        target: Callable[
            [Event, Callable[[dict[str, Any]], dict[str, Any]]],
            None,
        ],
    ) -> bool:
        initial_sequence = (
            self.event_store.latest_sequence(run_id)
            if self.event_store is not None
            else 0
        )
        active = ActiveAgentRun(normalize_event=AgentEventNormalizer(
            run_id,
            initial_sequence=initial_sequence,
        ))

        def publish(event: dict[str, Any]) -> dict[str, Any]:
            return self.publish(run_id, event)

        def worker() -> None:
            try:
                target(active.cancel_event, publish)
            except Exception as exc:
                logger.error(
                    "Agent run worker failed: %s (%s)",
                    run_id,
                    type(exc).__name__,
                )
                if type(exc).__name__ == "AgentRunCancelled":
                    publish({
                        "type": "cancelled",
                        "code": "agent_run_cancelled",
                        "message": "Agent run was cancelled.",
                    })
                else:
                    publish({
                        "type": "error",
                        "code": "agent_run_failed",
                        "message": "Agent run failed.",
                    })
            finally:
                self.finish(run_id)

        thread = Thread(target=worker, daemon=True)
        active.thread = thread
        with self._lock:
            if self._shutting_down or run_id in self._active:
                return False
            self._active[run_id] = active
            try:
                thread.start()
            except Exception:
                self._active.pop(run_id, None)
                raise
        return True

    def finish(self, run_id: str) -> None:
        with self._lock:
            active = self._active.get(run_id)
        if active is None:
            return
        with active.publish_lock:
            with self._lock:
                if self._active.get(run_id) is not active:
                    return
                self._active.pop(run_id, None)
                subscribers = list(active.subscribers)
        for subscriber in subscribers:
            subscriber.put({"type": "stream_closed", "runId": run_id})

    def is_active(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._active

    def cancel(
        self,
        run_id: str,
        event: dict[str, Any] | None = None,
    ) -> bool:
        with self._lock:
            active = self._active.get(run_id)
            if active is None:
                return False
            if event is None:
                active.cancel_event.set()
                return True

        source = dict(event)
        source.pop("sequence", None)
        with active.publish_lock:
            with self._lock:
                if self._active.get(run_id) is not active:
                    return False
                subscribers = list(active.subscribers)
                public = (
                    active.normalize_event(source)
                    if active.normalize_event is not None
                    else source
                )
            if self.event_store is not None:
                try:
                    self.event_store.append(run_id, public)
                except Exception:
                    logger.exception(
                        "Unable to persist cancellation event for run %s.",
                        run_id,
                    )
            for subscriber in subscribers:
                subscriber.put(dict(public))
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

    def shutdown(
        self,
        *,
        timeout_seconds: float = 5.0,
    ) -> tuple[str, ...]:
        """Cancel all active workers and wait for one shared shutdown deadline."""
        with self._lifecycle_lock:
            deadline = monotonic() + max(0.0, float(timeout_seconds))
            with self._lock:
                self._shutting_down = True
                active_runs = list(self._active.items())
                for _, active in active_runs:
                    active.cancel_event.set()

            caller = current_thread()
            for _, active in active_runs:
                thread = active.thread
                if thread is not None and thread is not caller:
                    thread.join(max(0.0, deadline - monotonic()))

            with self._lock:
                remaining = tuple(sorted(
                    run_id
                    for run_id, active in active_runs
                    if self._active.get(run_id) is active
                ))
            if remaining:
                logger.warning(
                    "Agent run shutdown timed out with active runs: %s",
                    ", ".join(remaining),
                )
            return remaining

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

    def publish(
        self,
        run_id: str,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        with self._lock:
            active = self._active.get(run_id)
        source = dict(event)
        source.pop("sequence", None)
        if active is None:
            return source
        with active.publish_lock:
            with self._lock:
                if self._active.get(run_id) is not active:
                    return source
                subscribers = list(active.subscribers)
                public = (
                    active.normalize_event(source)
                    if active.normalize_event is not None
                    else source
                )
            if self.event_store is not None:
                try:
                    self.event_store.append(run_id, public)
                except Exception:
                    logger.exception(
                        "Unable to persist Agent event for run %s.",
                        run_id,
                    )
            for subscriber in subscribers:
                subscriber.put(dict(public))
            return public
