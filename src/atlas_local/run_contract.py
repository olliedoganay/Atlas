from __future__ import annotations

import queue
import threading
from datetime import UTC, datetime
from typing import Any, TypedDict

TERMINAL_EVENT_TYPES = {"run_completed", "run_failed"}


class RunEvent(TypedDict):
    type: str
    timestamp: str
    payload: dict[str, Any]


class RunTraceItem(TypedDict, total=False):
    timestamp: str
    stage: str
    rationale: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    artifacts: dict[str, Any]


class RunHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[str, list[queue.Queue[RunEvent]]] = {}

    def subscribe(self, run_id: str) -> queue.Queue[RunEvent]:
        subscriber: queue.Queue[RunEvent] = queue.Queue()
        with self._lock:
            self._queues.setdefault(run_id, []).append(subscriber)
        return subscriber

    def unsubscribe(self, run_id: str, subscriber: queue.Queue[RunEvent]) -> None:
        with self._lock:
            queues = self._queues.get(run_id, [])
            self._queues[run_id] = [item for item in queues if item is not subscriber]
            if not self._queues[run_id]:
                self._queues.pop(run_id, None)

    def publish(self, run_id: str, event: RunEvent) -> None:
        with self._lock:
            subscribers = list(self._queues.get(run_id, []))
        for subscriber in subscribers:
            subscriber.put(event)


def make_run_event(event_type: str, payload: dict[str, Any], *, timestamp: str | None = None) -> RunEvent:
    return {
        "type": event_type,
        "timestamp": timestamp or now_timestamp(),
        "payload": payload,
    }


def make_trace_item(item: dict[str, Any], *, timestamp: str | None = None) -> RunTraceItem:
    enriched: RunTraceItem = dict(item)
    enriched.setdefault("timestamp", timestamp or now_timestamp())
    return enriched


def now_timestamp() -> str:
    return datetime.now(UTC).isoformat()
