"""Small public Bitunix ticker websocket client.

The stream is public and does not use account credentials. It is intentionally
kept separate from the authenticated execution adapter.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

import websocket


logger = logging.getLogger(__name__)
BITUNIX_PUBLIC_WS_URL = os.getenv(
    "BITUNIX_PUBLIC_WS_URL", "wss://fapi.bitunix.com/public/"
)


class BitunixTickerWebSocket:
    def __init__(
        self,
        symbols: list[str],
        on_ticker: Callable[[dict[str, Any]], None],
        *,
        url: str = BITUNIX_PUBLIC_WS_URL,
    ) -> None:
        self.symbols = list(dict.fromkeys(self._compact(symbol) for symbol in symbols if symbol))
        self.on_ticker = on_ticker
        self.url = url
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._socket: websocket.WebSocketApp | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="bitunix-ticker-ws",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            self._socket.close()
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=3)
        self._thread = None
        self._socket = None

    def _run(self) -> None:
        delay = 1.0
        while not self._stop.is_set():
            self._socket = websocket.WebSocketApp(
                self.url,
                on_open=self._on_open,
                on_message=self._on_message,
                on_error=lambda _ws, error: logger.warning(
                    "Bitunix ticker websocket error: %s", error
                ),
                on_close=lambda _ws, code, reason: logger.info(
                    "Bitunix ticker websocket closed code=%s reason=%s", code, reason
                ),
            )
            try:
                self._socket.run_forever(ping_interval=20, ping_timeout=10)
            except Exception:
                logger.exception("Bitunix ticker websocket loop failed")
            finally:
                self._socket = None
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, 30.0)

    def _on_open(self, ws: websocket.WebSocketApp) -> None:
        delay = 0.0
        for symbol in self.symbols:
            ws.send(json.dumps({
                "op": "subscribe",
                "args": [{"ch": "ticker", "symbol": symbol}],
            }))
            if delay:
                time.sleep(delay)
        logger.info("Subscribed Bitunix ticker websocket: %s", ", ".join(self.symbols))

    def _on_message(self, _ws: websocket.WebSocketApp, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return
        ticker = self.parse_ticker(payload)
        if ticker:
            self.on_ticker(ticker)

    @classmethod
    def parse_ticker(cls, payload: object) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        data = payload.get("data")
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict):
            return None
        raw_symbol = str(data.get("symbol") or payload.get("symbol") or "")
        symbol = cls._slash(raw_symbol)
        if not symbol:
            return None
        try:
            price = float(
                data.get("lastPrice")
                or data.get("last")
                or data.get("markPrice")
                or data.get("close")
                or 0
            )
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None
        try:
            timestamp = int(float(data.get("ts") or data.get("timestamp") or 0))
        except (TypeError, ValueError):
            timestamp = 0
        return {"symbol": symbol, "price": price, "timestamp": timestamp}

    @staticmethod
    def _compact(symbol: str) -> str:
        return str(symbol).strip().upper().replace("/", "").replace("-", "")

    @staticmethod
    def _slash(symbol: str) -> str:
        value = str(symbol).strip().upper().replace("-", "")
        if value.endswith("USDT") and len(value) > 4:
            return f"{value[:-4]}/USDT"
        return value
