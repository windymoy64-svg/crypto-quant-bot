from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


EventCallback = Callable[[dict[str, Any]], None]
ErrorCallback = Callable[[Exception], None]


@dataclass
class BinanceStreamCallbacks:
    on_kline: EventCallback | None = None
    on_ticker: EventCallback | None = None
    on_book: EventCallback | None = None
    on_trade: EventCallback | None = None
    on_depth: EventCallback | None = None
    on_message: EventCallback | None = None
    on_error: ErrorCallback | None = None
    on_open: Callable[[], None] | None = None
    on_close: Callable[[], None] | None = None


@dataclass
class BinanceStreamDispatcher:
    callbacks: BinanceStreamCallbacks = field(default_factory=BinanceStreamCallbacks)

    def dispatch_raw(self, raw_message: str) -> None:
        payload = json.loads(raw_message)
        event = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(event, dict):
            return
        self.dispatch(event)

    def dispatch(self, event: dict[str, Any]) -> None:
        if self.callbacks.on_message:
            self.callbacks.on_message(event)
        event_type = str(event.get("e") or "")
        if event_type == "kline" and self.callbacks.on_kline:
            self.callbacks.on_kline(event)
        elif event_type == "24hrMiniTicker" and self.callbacks.on_ticker:
            self.callbacks.on_ticker(event)
        elif event_type == "bookTicker" and self.callbacks.on_book:
            self.callbacks.on_book(event)
        elif event_type == "aggTrade" and self.callbacks.on_trade:
            self.callbacks.on_trade(event)
        elif event_type == "depthUpdate" and self.callbacks.on_depth:
            self.callbacks.on_depth(event)

    def dispatch_error(self, error: Exception) -> None:
        if self.callbacks.on_error:
            self.callbacks.on_error(error)