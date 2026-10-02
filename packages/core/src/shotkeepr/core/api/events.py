"""Bus di eventi in-process per avanzamento, notifiche e degrado (ADR-003)."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class EventKind(StrEnum):
    PROGRESS = "PROGRESS"
    NOTIFICATION = "NOTIFICATION"
    DEGRADATION = "DEGRADATION"


@dataclass(frozen=True, slots=True)
class Event:
    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "payload": self.payload, "at": self.at.isoformat()}


class EventBus:
    """Pub/sub thread-safe: un produttore (pipeline) e N consumatori (connessioni WebSocket)."""

    def __init__(self) -> None:
        self._subscribers: list[queue.Queue[Event]] = []
        self._lock = threading.Lock()

    def subscribe(self) -> queue.Queue[Event]:
        q: queue.Queue[Event] = queue.Queue()
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: queue.Queue[Event]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def publish(self, event: Event) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for q in subscribers:
            q.put(event)
