from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from app.live.config import LiveConfig


@dataclass(frozen=True)
class LiveSafetyDecision:
    approved: bool
    reason: str
    enabled: bool
    dry_run: bool
    confirm_live: bool
    exchange: str
    operator: str
    timestamp: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LiveSafetyGate:
    enabled: bool = False
    dry_run: bool = True
    confirm_live: bool = False
    exchange: str = "binance"
    operator: str = "unknown"
    timestamp: str = ""

    @classmethod
    def from_config(cls, config: LiveConfig, *, operator: str = "unknown") -> "LiveSafetyGate":
        return cls(
            enabled=config.enabled,
            dry_run=config.dry_run,
            confirm_live=config.confirm_live,
            exchange=config.exchange,
            operator=operator,
            timestamp=datetime.now(UTC).isoformat(),
        )

    def evaluate(self) -> LiveSafetyDecision:
        timestamp = self.timestamp or datetime.now(UTC).isoformat()
        if not self.enabled:
            return self._decision(False, "live_safety_enabled_false", timestamp)
        if self.dry_run:
            return self._decision(False, "live_safety_dry_run_true", timestamp)
        if not self.confirm_live:
            return self._decision(False, "live_safety_confirm_live_false", timestamp)
        return self._decision(True, "live_safety_approved", timestamp)

    def _decision(self, approved: bool, reason: str, timestamp: str) -> LiveSafetyDecision:
        return LiveSafetyDecision(
            approved=approved,
            reason=reason,
            enabled=self.enabled,
            dry_run=self.dry_run,
            confirm_live=self.confirm_live,
            exchange=self.exchange,
            operator=self.operator,
            timestamp=timestamp,
        )