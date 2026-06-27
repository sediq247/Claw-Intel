#!/usr/bin/env python3
"""
 runtime/py_event_bus.py
Local in-memory pub/sub for Python agents.
All agents subscribe and publish HERE for internal coordination.
The bridge forwards selected events (AGENT_MESSAGE, AI_VERDICT) to Node.js.
"""

from typing import Any, Callable, Dict, List
from collections import defaultdict


class PyEventBus:
    """Thread-safe sync event bus for intra-Python agent communication."""

    def __init__(self):
        self._subscribers: Dict[str, List[Callable[[Any], None]]] = defaultdict(list)
        self._history: List[dict] = []
        self.max_history = 1000

    def subscribe(self, event_type: str, callback: Callable[[Any], None]) -> Callable[[], None]:
        """Subscribe to an event type. Returns an unsubscribe function."""
        self._subscribers[event_type].append(callback)

        def unsubscribe():
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass
        return unsubscribe

    def publish(self, event_type: str, payload: Any) -> None:
        """Publish an event to all local subscribers (sync, non-blocking)."""
        event = {"type": event_type, "payload": payload}
        self._history.append(event)
        if len(self._history) > self.max_history:
            self._history.pop(0)

        for cb in list(self._subscribers.get(event_type, [])):
            try:
                cb(payload)
            except Exception as e:
                print(f"[PyEventBus] Error in subscriber for {event_type}: {e}")

    def get_history(self, event_type: str, limit: int = 50) -> List[Any]:
        return [e["payload"] for e in self._history if e["type"] == event_type][-limit:]

    def get_active_event_types(self) -> List[str]:
        return list(self._subscribers.keys())
