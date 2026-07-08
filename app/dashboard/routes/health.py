from __future__ import annotations

from fastapi import APIRouter

from app.dashboard.services import dashboard_service

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    return dashboard_service.health()
