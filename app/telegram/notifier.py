from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from app.telegram.control_center import TelegramNotificationFormatter

TELEGRAM_API_BASE = "https://api.telegram.org"
logger = logging.getLogger(__name__)


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

        # Get token and chat_id with proper fallback priority:
        # 1. Explicit parameter (for tests/dry runs)
        # 2. Environment variables (for production)
        self.token = token if token is not None else os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("TELEGRAM_CHAT_ID", "")

        self.formatter = TelegramNotificationFormatter()
        self.outbox: list[str] = []
        self.delivered_count = 0

    @property
    def is_configured(self) -> bool:
        """Check if notifier has valid credentials."""
        return bool(self.token and self.chat_id)

    def send(self, message: str) -> bool:
        """Send a message to Telegram.

        If configured and live mode is on, delivers to Telegram API.
        Otherwise, just stores in outbox for testing.
        """
        self.outbox.append(message)
        if self.enabled and self.live and self.is_configured:
            return self._deliver(message)
        return False

    def _deliver(self, message: str) -> bool:
        if not (self.token and self.chat_id):
            return False
        url = f"{TELEGRAM_API_BASE}/bot{self.token}/sendMessage"
        body: dict[str, object] = {
            "chat_id": self.chat_id,
            "text": message,
            "disable_web_page_preview": True,
        }
        # TradeReporter emits HTML, while legacy indicator messages may contain
        # comparison operators such as "MA5 < MA20" and must stay plain text.
        if "<b>" in message or "</b>" in message:
            body["parse_mode"] = "HTML"
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                response.read()
            self.delivered_count += 1
            return True
        except (urllib.error.URLError, OSError) as exc:
            # Delivery failures must never crash the trading loop.
            logger.warning("Telegram delivery failed: %s", exc)
            return False

    def notify(self, event_type: str, payload: dict[str, object] | None = None) -> None:
        self.send(self.formatter.format(event_type, payload or {}))

