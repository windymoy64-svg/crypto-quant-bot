import asyncio
from collections import deque
import logging
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.dashboard.services import dashboard_service, utc_now_iso
from app.events.subscriber import subscribe


router = APIRouter()
logger = logging.getLogger(__name__)


class DashboardEventHub:
    def __init__(self, max_events: int = 200) -> None:
        self.connections: set[WebSocket] = set()
        self.live_events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._queue: asyncio.Queue[dict[str, Any]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._drain_task: asyncio.Task[None] | None = None
        self._snapshot_task: asyncio.Task[None] | None = None
        self._subscribed = False

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._ensure_runtime()
        try:
            await websocket.send_json({"type": "snapshot", "payload": dashboard_service.snapshot()})
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
                self._loop.call_soon_threadsafe(self._queue.put_nowait, message)
            except RuntimeError:
                logger.exception("Dashboard websocket event loop is unavailable")

    def _ensure_runtime(self) -> None:
        loop = asyncio.get_running_loop()
        loop_changed = self._loop is not None and self._loop is not loop
        if loop_changed and self._drain_task and not self._drain_task.done():
            self._drain_task.cancel()
        if loop_changed and self._snapshot_task and not self._snapshot_task.done():
            self._snapshot_task.cancel()
        if self._queue is None or loop_changed:
            self._loop = loop
            self._queue = asyncio.Queue()
            self._drain_task = None
            self._snapshot_task = None
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain())
        if self._snapshot_task is None or self._snapshot_task.done():
            self._snapshot_task = asyncio.create_task(self._broadcast_snapshots())
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

    async def _broadcast_snapshots(self, interval_seconds: int = 15) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            if not self.connections:
                continue
            try:
                await self.broadcast({
                    "type": "snapshot",
                    "payload": dashboard_service.snapshot(),
                })
            except Exception:
                logger.exception("Periodic snapshot broadcast failed")


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
        await websocket.close(code=1008)
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