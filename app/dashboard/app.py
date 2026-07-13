from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request
from fastapi.params import Depends as DependsParam
from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config.env import get_exchange_credentials
from app.config.production import production_shutdown, production_startup
from app.dashboard.routes import analytics, backtest, health, market, paper, portfolio
from app.dashboard.scheduler import shutdown_scheduler, start_scheduler
from app.dashboard.services import dashboard_service, read_json_file
from app.dashboard.websocket import event_hub, router as websocket_router



def require_api_key(
    authorization: str | None = Header(default=None),
    dashboard_token: str | None = Cookie(default=None),
) -> None:
    expected = os.getenv("BOT_API_KEY")

    if not expected:
        return

    if authorization == f"Bearer {expected}":
        return

    if dashboard_token == expected:
        return

    raise HTTPException(
        status_code=401,
        detail="invalid api key",
    )


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    production_startup()
    start_scheduler()
    try:
        yield
    finally:
        await event_hub.shutdown()
        shutdown_scheduler()
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
        _include_http_router(
            dashboard,
            route.router.routes,
            dependencies=[Depends(require_api_key)],
        )

    _include_websocket_router(dashboard, websocket_router.routes)

    _register_compat_routes(dashboard)

    return dashboard



def _include_http_router(
    dashboard: FastAPI,
    routes: list[object],
    dependencies: list[DependsParam],
) -> None:
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        dashboard.add_api_route(
            path=route.path,
            endpoint=route.endpoint,
            response_model=route.response_model,
            status_code=route.status_code,
            tags=route.tags,
            dependencies=[*dependencies, *route.dependencies],
            summary=route.summary,
            description=route.description,
            response_description=route.response_description,
            responses=route.responses,
            deprecated=route.deprecated,
            methods=route.methods,
            operation_id=route.operation_id,
            response_model_include=route.response_model_include,
            response_model_exclude=route.response_model_exclude,
            response_model_by_alias=route.response_model_by_alias,
            response_model_exclude_unset=route.response_model_exclude_unset,
            response_model_exclude_defaults=route.response_model_exclude_defaults,
            response_model_exclude_none=route.response_model_exclude_none,
            include_in_schema=route.include_in_schema,
            response_class=route.response_class,
            name=route.name,
        )


def _include_websocket_router(
    dashboard: FastAPI,
    routes: list[object],
) -> None:
    for route in routes:
        if not isinstance(route, APIWebSocketRoute):
            continue
        dashboard.add_api_websocket_route(
            path=route.path,
            endpoint=route.endpoint,
            name=route.name,
        )


def _register_compat_routes(dashboard: FastAPI) -> None:
    templates = Jinja2Templates(
        directory=str(Path(__file__).parent / "templates")
    )

    @dashboard.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "request": request,
                "app_name": "Crypto Quant Bot",
                "release": "v1.0",
                "read_only": True,
            },
        )
        api_key = os.getenv("BOT_API_KEY")
        cookie_secure = os.getenv("DASHBOARD_COOKIE_SECURE", "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if api_key:
            response.set_cookie(
                key="dashboard_token",
                value=api_key,
                httponly=True,
                secure=cookie_secure,
                samesite="strict",
                max_age=60 * 60 * 12,
            )
        return response

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