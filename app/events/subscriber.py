from __future__ import annotations

from typing import Any

from app.events.bus import EventHandler, event_bus


def subscribe(event_type: type[Any] | str, handler: EventHandler) -> None:
    event_bus.subscribe(event_type, handler)


def unsubscribe(event_type: type[Any] | str, handler: EventHandler) -> None:
    event_bus.unsubscribe(event_type, handler)