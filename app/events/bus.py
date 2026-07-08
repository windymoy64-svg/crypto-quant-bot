from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any, Callable

EventHandler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[type[Any] | str, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def publish(self, event: Any) -> None:
        handlers = self._handlers_for(event)
        for handler in handlers:
            handler(event)

    def subscribe(self, event_type: type[Any] | str, handler: EventHandler) -> None:
        with self._lock:
            if handler not in self._subscribers[event_type]:
                self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: type[Any] | str, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._subscribers.get(event_type)
            if not handlers:
                return
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._subscribers.pop(event_type, None)

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()

    def _handlers_for(self, event: Any) -> list[EventHandler]:
        event_type_name = event.__class__.__name__
        with self._lock:
            handlers = list(self._subscribers.get(event.__class__, []))
            handlers.extend(self._subscribers.get(event_type_name, []))
            handlers.extend(self._subscribers.get("*", []))
        return handlers


event_bus = EventBus()