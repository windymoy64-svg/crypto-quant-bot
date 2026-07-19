"""Animated office visualization backend.

Modul kecil yang membaca artefak runtime bot (signals, paper state, agent
pipeline output) dan menerjemahkannya menjadi ``OfficeSnapshot`` yang bisa
dikonsumsi oleh halaman animated agents di dashboard.
"""

from app.dashboard.office.state import (
    AgentState,
    OfficeSnapshot,
    build_office_snapshot,
)

__all__ = [
    "AgentState",
    "OfficeSnapshot",
    "build_office_snapshot",
]
