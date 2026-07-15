from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from app.telegram.control_center import TelegramNotificationFormatter

TELEGRAM_API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(
        self,
        enabled: bool = False,
        *,
        live: bool = False,
        token: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.enabled = enabled
        # Real delivery to the Telegram Bot API only happens when `live` is
        # explicitly requested. Tests and dry runs keep `live=False`, so they
        # stay fully offline and only capture messages in `outbox`.
        self.live = live
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")
        self.formatter = TelegramNotificationFormatter()
        self.outbox: list[str] = []

    def send(self, message: str) -> None:
        self.outbox.append(message)
        if self.live:
            self._deliver(message)

    def _deliver(self, message: str) -> None:
        if not (self.token and self.chat_id):
            return
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        payload = json.dumps({"chat_id": self.chat_id, "text": message}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
        except (urllib.error.URLError, OSError):
            # Delivery failures must never crash the trading loop.
            return

    def notify(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.send(self.formatter.format(event_type, payload or {}))

