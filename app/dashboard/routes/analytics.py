from __future__ import annotations

from fastapi import APIRouter

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
def analytics() -> dict[str, object]:
    return dashboard_service.analytics()
