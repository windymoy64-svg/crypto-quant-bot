from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config.env import get_exchange_credentials
from app.config.production import production_shutdown, production_startup
from app.dashboard.routes import analytics, backtest, health, market, paper, portfolio
from app.dashboard.services import dashboard_service, read_json_file
from app.dashboard.websocket import event_hub, router as websocket_router



def require_api_key(
    authorization: str | None = Header(default=None),
) -> None:
    expected = os.getenv("BOT_API_KEY")

    if not expected:
        return

    if authorization == f"Bearer {expected}":
        return

    raise HTTPException(
        status_code=401,
        detail="invalid api key",
    )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    production_startup()
    try:
        yield
    finally:
        await event_hub.shutdown()
        production_shutdown()


def create_app() -> FastAPI:
    dashboard = FastAPI(
        title="Crypto Quant Bot Dashboard",
        version="1.0.0",
        lifespan=_lifespan,
    )

    base_dir = Path(__file__).parent

    dashboard.mount(
        "/static",
        StaticFiles(directory=str(base_dir / "static")),
        name="static",
    )

    for route in (
        market,
        portfolio,
        paper,
        backtest,
        analytics,
        health,
    ):
        dashboard.include_router(
            route.router,
            dependencies=[Depends(require_api_key)],
        )

    dashboard.include_router(websocket_router)

    _register_compat_routes(dashboard)

    return dashboard



def _register_compat_routes(dashboard: FastAPI) -> None:
    templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )

    @dashboard.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "app_name": "Crypto Quant Bot",
                "release": "v1.0",
                "read_only": True,
            },
        )

    @dashboard.get("/health")
    def legacy_health() -> dict[str, object]:
        return dashboard_service.health()

    @dashboard.get("/status", dependencies=[Depends(require_api_key)])
    def status() -> dict[str, object]:
        latest = dashboard_service.market()
        paper_state = dashboard_service.paper()
        credentials = get_exchange_credentials()

        return {
            "status": "ok",
            "latest_signal_timestamp": latest.get("timestamp"),
            "paper_balance": paper_state.get("balance"),
            "open_positions": len(
                paper_state.get("open_positions", [])
            ),
            "exchange": credentials.exchange_id,
            "exchange_api_configured": credentials.configured,
            "live_trading_enabled": (
                os.getenv(
                    "LIVE_TRADING_ENABLED",
                    "false",
                ).lower()
                == "true"
            ),
            "live_trading_dry_run": (
                os.getenv(
                    "LIVE_TRADING_DRY_RUN",
                    "true",
                ).lower()
                == "true"
            ),
            "read_only": True,
        }

    @dashboard.get(
        "/signals/latest",
        dependencies=[Depends(require_api_key)],
    )
    def latest_signals() -> object:
        return read_json_file(
            "logs/latest_signals.json",
            {"signals": []},
        )

    @dashboard.get(
        "/paper/state",
        dependencies=[Depends(require_api_key)],
    )
    def paper_state() -> object:
        return dashboard_service.paper()


app = create_app()