from __future__ import annotations

from app.live.config import LiveConfig
from app.live.models import LiveExecutionResult, LiveOrder


class LiveExecutor:
    def __init__(self, config: LiveConfig | None = None) -> None:
        self.config = config or LiveConfig()

    def execute(self, *, payload: dict[str, object], order: LiveOrder) -> LiveExecutionResult:
        if self.config.dry_run:
            return LiveExecutionResult(
                mode="DRY_RUN",
                status="prepared",
                payload=payload,
                reason="dry_run_no_network_call",
                order=order,
            )

        return LiveExecutionResult(
            mode="LIVE_DISABLED",
            status="rejected",
            payload=payload,
            reason="live_execution_disabled_in_sprint_20a",
            order=order,
        )

    def _send_live_order(self, payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("Live network order submission is disabled for Sprint 20A")
