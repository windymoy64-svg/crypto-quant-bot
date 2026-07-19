"""Route API untuk animated office view.

Endpoint tunggal ``GET /api/office/state`` mengembalikan snapshot semua
agent yang dirakit dari file runtime bot. Aman dipanggil polling ~1-2
detik karena hanya baca 3 file JSON kecil.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.dashboard.office.state import build_office_snapshot


router = APIRouter(prefix="/api/office", tags=["office"])


@router.get("/state")
def office_state() -> dict[str, Any]:
    snapshot = build_office_snapshot()
    return snapshot.to_dict()
