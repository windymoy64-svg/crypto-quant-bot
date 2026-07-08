from __future__ import annotations

from app.telegram.control_center import TelegramNotificationFormatter


class TelegramNotifier:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.formatter = TelegramNotificationFormatter()
        self.outbox: list[str] = []

    def send(self, message: str) -> None:
        if not self.enabled:
            self.outbox.append(message)
            return
        self.outbox.append(message)

    def notify(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.send(self.formatter.format(event_type, payload or {}))
