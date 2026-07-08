from __future__ import annotations

from typing import Any

from app.events.bus import event_bus


def publish(event: Any) -> None:
    event_bus.publish(event)