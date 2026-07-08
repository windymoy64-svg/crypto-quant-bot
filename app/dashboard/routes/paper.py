from __future__ import annotations

from fastapi import APIRouter

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["paper"])


@router.get("/paper")
def paper() -> dict[str, object]:
    return dashboard_service.paper()
