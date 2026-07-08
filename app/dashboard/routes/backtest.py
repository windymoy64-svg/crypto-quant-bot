from __future__ import annotations

from fastapi import APIRouter

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["backtest"])


@router.get("/backtest")
def backtest() -> dict[str, object]:
    return dashboard_service.backtest()
