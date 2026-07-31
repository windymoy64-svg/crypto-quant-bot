import asyncio
from collections import deque
import logging
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dashboard.services import dashboard_service, utc_now_iso
from app.dashboard.routes.multi_portfolio import multi_portfolio
from app.dashboard.routes.agent import pipeline_snapshot, synchronized_snapshot
from app.events.subscriber import subscribe
from app.exchange.binance.stream import BinanceStreamCallbacks
from app.exchange.binance.websocket import BinanceWebSocket
from app.exchange.public_http_client import PublicHttpExchangeClient


router = APIRouter()
logger = logging.getLogger(__name__)


class DashboardEventHub:
    def __init__(self, max_events: int = 200, max_pending_events: int = 500) -> None:
        self.connections: set[WebSocket] = set()
        self.live_events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._max_pending_events = max(1, max_pending_events)
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._agent_pipeline_task: asyncio.Task[None] | None = None
        self._price_stream_task: asyncio.Task[None] | None = None
        self._subscribed = False
        self._binance_ws: BinanceWebSocket | None = None
        self._tracked_symbols: list[str] = []
        self._price_exchange = ""

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._ensure_runtime()
        try:
            snapshot = await asyncio.to_thread(dashboard_service.snapshot)
            await websocket.send_json({"type": "snapshot", "payload": snapshot})
            await websocket.send_json({
                "type": "agent_snapshot",
                "payload": await asyncio.to_thread(synchronized_snapshot),
            })
            await websocket.send_json({"type": "live_events", "payload": list(self.live_events)})
        except Exception:
            logger.exception("Failed to initialize dashboard websocket connection")
            return
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def shutdown(self) -> None:
        if self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
        if self._snapshot_task and not self._snapshot_task.done():
            self._snapshot_task.cancel()
        if self._agent_pipeline_task and not self._agent_pipeline_task.done():
            self._agent_pipeline_task.cancel()
        if self._price_stream_task and not self._price_stream_task.done():
            self._price_stream_task.cancel()
        if self._binance_ws is not None:
            self._binance_ws.stop()
            self._binance_ws = None
        for websocket in list(self.connections):
            try:
                await websocket.close()
            except Exception:
                logger.exception("Failed to close dashboard websocket")
            finally:
                self.disconnect(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in list(self.connections):
            try:
                await websocket.send_json(message)
            except Exception:
                logger.exception("Dropping stale dashboard websocket connection")
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)

    def handle_event(self, event: object) -> None:
        payload = event.to_dict() if hasattr(event, "to_dict") else {"value": str(event)}
        message = {
            "type": "event",
            "event_type": payload.get("event_type", event.__class__.__name__),
            "occurred_at": payload.get("occurred_at", utc_now_iso()),
            "payload": payload,
        }
        self.live_events.append(message)
        if self._loop and self._queue:
            try:
                self._loop.call_soon_threadsafe(self._enqueue_latest, message)
                # Broadcast entry_candidate_processed with dedicated type for realtime UI
                if payload.get("event_type") == "entry_candidate_processed":
                    realtime_msg = {
                        "type": "entry_candidate_processed",
                        "payload": payload,
                    }
                    self._loop.call_soon_threadsafe(self._enqueue_latest, realtime_msg)
            except RuntimeError:
                logger.exception("Dashboard websocket event loop is unavailable")

    def _enqueue_latest(self, message: dict[str, Any]) -> None:
        """Enqueue tanpa membiarkan producer cepat menghabiskan RAM.

        Event dashboard bersifat realtime dan selalu dilengkapi snapshot
        periodik. Saat consumer tertinggal, event paling lama lebih aman
        dibuang daripada menumbuhkan antrean tanpa batas.
        """

        if self._queue is None:
            return
        if self._queue.full():
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            # Hanya mungkin bila ada enqueue lain di loop yang sama di antara
            # pemeriksaan dan put; snapshot berikutnya tetap menyegarkan state.
            pass

    def _ensure_runtime(self) -> None:
        loop = asyncio.get_running_loop()
        loop_changed = self._loop is not None and self._loop is not loop
        if loop_changed and self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
        if loop_changed and self._snapshot_task and not self._snapshot_task.done():
            self._snapshot_task.cancel()
        if loop_changed and self._agent_pipeline_task and not self._agent_pipeline_task.done():
            self._agent_pipeline_task.cancel()
        if self._queue is None or loop_changed:
            self._loop = loop
            self._queue = asyncio.Queue(maxsize=self._max_pending_events)
            self._drain_task = None
            self._snapshot_task = None
            self._agent_pipeline_task = None
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain())
        if self._snapshot_task is None or self._snapshot_task.done():
            self._snapshot_task = asyncio.create_task(self._broadcast_snapshots())
        if self._agent_pipeline_task is None or self._agent_pipeline_task.done():
            self._agent_pipeline_task = asyncio.create_task(
                self._broadcast_agent_pipeline_updates()
            )
        if self._price_stream_task is None or self._price_stream_task.done():
            self._price_stream_task = asyncio.create_task(self._sync_price_stream())
        if not self._subscribed:
            subscribe("*", self.handle_event)
            self._subscribed = True

    async def _drain(self) -> None:
        if self._queue is None:
            return
        while True:
            message = await self._queue.get()
            try:
                await self.broadcast(message)
            except Exception:
                logger.exception("Dashboard websocket broadcast failed")

    async def _broadcast_snapshots(self, interval_seconds: int = 5) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            if not self.connections:
                continue
            try:
                snapshot = await asyncio.to_thread(dashboard_service.snapshot)
                await self.broadcast({
                    "type": "snapshot",
                    "payload": snapshot,
                })
                await self.broadcast({
                    "type": "agent_snapshot",
                    "payload": await asyncio.to_thread(synchronized_snapshot),
                })
            except Exception:
                logger.exception("Periodic snapshot broadcast failed")

    async def _broadcast_agent_pipeline_updates(
        self, interval_seconds: float = 1.0,
    ) -> None:
        """Stream cross-process pipeline progress without polling heavy panels."""

        last_generated_at = ""
        while True:
            await asyncio.sleep(interval_seconds)
            if not self.connections:
                continue
            try:
                pipeline = await asyncio.to_thread(pipeline_snapshot)
                generated_at = str(pipeline.get("generated_at") or "")
                if not generated_at or generated_at == last_generated_at:
                    continue
                last_generated_at = generated_at
                await self.broadcast({
                    "type": "agent_pipeline_update",
                    "payload": pipeline,
                })
            except Exception:
                logger.exception("Realtime agent pipeline broadcast failed")

    async def _sync_price_stream(self, interval_seconds: int = 2) -> None:
        """Keep active prices near-realtime using the selected exchange source."""
        while True:
            await asyncio.sleep(interval_seconds)
            if not self.connections:
                continue
            try:
                symbols, exchange = self._open_position_symbols()
                if exchange == "bitunix":
                    if self._binance_ws is not None:
                        self._binance_ws.stop()
                        self._binance_ws = None
                    self._tracked_symbols = symbols
                    self._price_exchange = exchange
                    await self._poll_bitunix_prices(symbols)
                elif symbols != self._tracked_symbols or exchange != self._price_exchange:
                    self._price_exchange = exchange
                    self._restart_price_stream(symbols)
            except Exception:
                logger.exception("Realtime price stream sync failed")

    def _open_position_symbols(self) -> tuple[list[str], str]:
        """Symbols that need live price ticks (paper + multi-portfolio)."""
        symbols: list[str] = []
        seen: set[str] = set()

        def _add(raw: object) -> None:
            symbol = str(raw or "").strip().upper().replace("-", "/")
            if not symbol or symbol in seen:
                return
            seen.add(symbol)
            symbols.append(symbol)

        paper = dashboard_service.paper()
        if isinstance(paper, dict):
            for bucket in (paper.get("open_positions"), paper.get("pending_orders")):
                if not isinstance(bucket, list):
                    continue
                for row in bucket:
                    if isinstance(row, dict):
                        _add(row.get("symbol"))

        # Real / multi-account positions (same source as Overview P&L Stream).
        try:
            multi = multi_portfolio()
        except Exception:
            multi = None
        if isinstance(multi, dict):
            for bucket in (multi.get("positions"), multi.get("open_orders")):
                for row in bucket or []:
                    if isinstance(row, dict):
                        _add(row.get("symbol"))
            exchange = str(multi.get("active_execution_exchange") or "binance").lower()
        else:
            exchange = "binance"

        return symbols, exchange

    async def _poll_bitunix_prices(self, symbols: list[str]) -> None:
        """Publish genuine Bitunix prices for every live position/pending order."""

        if not symbols:
            return
        client = PublicHttpExchangeClient("bitunix", timeout_seconds=5)
        for symbol in symbols:
            try:
                ticker = await asyncio.to_thread(client.fetch_ticker, symbol)
                price = float(ticker.get("last") or 0)
            except Exception:
                logger.warning("Bitunix ticker refresh failed for %s", symbol, exc_info=True)
                continue
            if price <= 0:
                continue
            self._enqueue_latest({
                "type": "price_update",
                "payload": {
                    "symbol": symbol,
                    "price": price,
                    "source": "bitunix_public_ticker",
                    "timestamp": utc_now_iso(),
                },
            })

    def _restart_price_stream(self, symbols: list[str]) -> None:
        if self._binance_ws is not None:
            self._binance_ws.stop()
            self._binance_ws = None
        self._tracked_symbols = symbols
        if not symbols:
            return
        callbacks = BinanceStreamCallbacks(on_message=self._handle_price_message)
        stream = BinanceWebSocket(callbacks=callbacks)
        stream.subscribe_market_data(
            symbols,
            interval="1m",
            include_kline=False,
            include_mini_ticker=True,
            include_book_ticker=True,
        )
        stream.start()
        self._binance_ws = stream
        logger.info("Started dashboard realtime price stream: %s", ", ".join(symbols))

    def _handle_price_message(self, event: dict[str, Any]) -> None:
        """Called from Binance WS thread — enqueue price_update for broadcast."""
        symbol = self._symbol_from_stream_event(event)
        price = self._price_from_stream_event(event)
        if not symbol or price <= 0 or not self._loop or not self._queue:
            return
        message: dict[str, Any] = {
            "type": "price_update",
            "payload": {
                "symbol": symbol,
                "price": price,
                "source": "binance_websocket",
                "timestamp": utc_now_iso(),
            },
        }
        try:
            self._loop.call_soon_threadsafe(self._enqueue_latest, message)
        except RuntimeError:
            pass

    def _symbol_from_stream_event(self, event: dict[str, Any]) -> str:
        raw = str(event.get("s") or "").upper()
        if not raw:
            return ""
        by_compact = {s.replace("/", ""): s for s in self._tracked_symbols}
        return by_compact.get(raw, "")

    def _price_from_stream_event(self, event: dict[str, Any]) -> float:
        # miniTicker: c = close price; bookTicker: a = best ask, b = best bid
        for key in ("c", "a", "b"):
            value = event.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        return 0.0


event_hub = DashboardEventHub()


@router.websocket("/ws")
async def dashboard_ws(websocket: WebSocket) -> None:
    expected = os.getenv("BOT_API_KEY")
    token = (
        websocket.query_params.get("api_key")
        or websocket.query_params.get("token")
        or websocket.cookies.get("dashboard_token")
    )
    if expected and token != expected:
        await websocket.accept()
        await websocket.close(code=1008, reason="Unauthorized")
        return
    await event_hub.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            await websocket.send_json({"type": "heartbeat", "timestamp": utc_now_iso()})
    except WebSocketDisconnect:
        event_hub.disconnect(websocket)
    except Exception:
        logger.exception("Dashboard websocket connection failed")
        event_hub.disconnect(websocket)