from __future__ import annotations

import threading
import time
from typing import Any

from app.exchange.binance.exceptions import BinanceConfigurationError
from app.exchange.binance.heartbeat import BinanceHeartbeat
from app.exchange.binance.reconnect import BinanceReconnectPolicy
from app.exchange.binance.stream import BinanceStreamCallbacks, BinanceStreamDispatcher
from app.exchange.binance.subscription import BinanceSubscription


class BinanceWebSocket:
    """Read-only Binance combined websocket engine with reconnect support."""

    def __init__(
        self,
        testnet: bool = True,
        *,
        callbacks: BinanceStreamCallbacks | None = None,
        heartbeat: BinanceHeartbeat | None = None,
        reconnect_policy: BinanceReconnectPolicy | None = None,
    ) -> None:
        self.testnet = testnet
        self.single_base_url = "wss://testnet.binance.vision/ws" if testnet else "wss://stream.binance.com:9443/ws"
        self.combined_base_url = "wss://testnet.binance.vision" if testnet else "wss://stream.binance.com:9443"
        self.callbacks = callbacks or BinanceStreamCallbacks()
        self.dispatcher = BinanceStreamDispatcher(self.callbacks)
        self.heartbeat = heartbeat or BinanceHeartbeat()
        self.reconnect_policy = reconnect_policy or BinanceReconnectPolicy()
        self.subscription = BinanceSubscription()
        self._ws_app: Any | None = None
        self._thread: threading.Thread | None = None
        self._stop_requested = False
        self._lock = threading.RLock()

    def stream_url(self, stream: str) -> str:
        return f"{self.single_base_url}/{stream}"

    def combined_stream_url(self, streams: list[str]) -> str:
        return f"{self.combined_base_url}/stream?streams={'/'.join(streams)}"

    def subscribe_market_data(
        self,
        symbols: list[str],
        *,
        interval: str = "1m",
        include_kline: bool = True,
        include_mini_ticker: bool = True,
        include_book_ticker: bool = True,
        include_depth: bool = False,
        include_agg_trade: bool = False,
    ) -> BinanceSubscription:
        self.subscription = BinanceSubscription.for_market_data(
            symbols,
            interval=interval,
            include_kline=include_kline,
            include_mini_ticker=include_mini_ticker,
            include_book_ticker=include_book_ticker,
            include_depth=include_depth,
            include_agg_trade=include_agg_trade,
        )
        return self.subscription

    def on_kline(self, callback: Any) -> None:
        self.callbacks.on_kline = callback

    def on_ticker(self, callback: Any) -> None:
        self.callbacks.on_ticker = callback

    def on_book(self, callback: Any) -> None:
        self.callbacks.on_book = callback

    def on_trade(self, callback: Any) -> None:
        self.callbacks.on_trade = callback

    def on_depth(self, callback: Any) -> None:
        self.callbacks.on_depth = callback

    def start(self, *, blocking: bool = False) -> None:
        if self.subscription.is_empty():
            raise BinanceConfigurationError("No Binance websocket streams subscribed")
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_requested = False
        if blocking:
            self._run_with_reconnect()
            return
        with self._lock:
            self._thread = threading.Thread(target=self._run_with_reconnect, name="binance-websocket", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_requested = True
            if self._ws_app is not None:
                self._ws_app.close()
            thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)

    def _run_with_reconnect(self) -> None:
        attempt = 0
        while not self._stop_requested and self.reconnect_policy.should_retry(attempt):
            attempt += 1
            try:
                self._run_once()
            except Exception as exc:
                self.dispatcher.dispatch_error(exc)
            if self._stop_requested:
                break
            time.sleep(self.reconnect_policy.delay_for(attempt))

    def _run_once(self) -> None:
        websocket_client = self._load_websocket_client()
        url = self.combined_stream_url(self.subscription.streams)
        self._ws_app = websocket_client.WebSocketApp(
            url,
            on_open=self._handle_open,
            on_message=self._handle_message,
            on_error=self._handle_error,
            on_close=self._handle_close,
        )
        try:
            self._ws_app.run_forever(ping_interval=int(self.heartbeat.interval_seconds), ping_timeout=10)
        finally:
            self._ws_app = None

    def _handle_open(self, ws_app: Any) -> None:
        self.heartbeat.mark_message()
        if self.callbacks.on_open:
            self.callbacks.on_open()

    def _handle_message(self, ws_app: Any, message: str) -> None:
        self.heartbeat.mark_message()
        self.dispatcher.dispatch_raw(message)

    def _handle_error(self, ws_app: Any, error: Exception) -> None:
        self.dispatcher.dispatch_error(error)

    def _handle_close(self, ws_app: Any, close_status_code: int | None = None, close_msg: str | None = None) -> None:
        if self.callbacks.on_close:
            self.callbacks.on_close()

    def _load_websocket_client(self) -> Any:
        try:
            import websocket as websocket_client
        except ImportError as exc:
            raise BinanceConfigurationError("Install websocket-client to run Binance realtime streams") from exc
        return websocket_client