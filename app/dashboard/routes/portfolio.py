from __future__ import annotations

from fastapi import APIRouter

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio")
def portfolio() -> dict[str, object]:
    return dashboard_service.portfolio()


@router.get("/live/orders")
def live_orders() -> dict[str, object]:
    return dashboard_service.live_orders()
