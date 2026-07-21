"""Deterministic entry guards applied before a position is opened.

These guards are intentionally pure: they consume a context dict and return a
``GateResult``. They never touch the network or mutate state, so the realtime
loop can compose them without hidden coupling.

Guards implemented here:

- ``ClosedCandleGuard``: reject entries when the latest candle on the entry
  timeframe may still be forming (polling cadence vs. candle duration).
- ``RegimeGate``: reject entries in regimes that the operator flags as
  not-tradeable (e.g. ``MIXED`` / ``RANGING``) plus a separate observation set
  for short entries while short calibration is incomplete.
- ``LiquiditySpreadGate``: reject entries when the bid/ask spread, quote
  volume, or expected round-trip cost make the trade uneconomic.

All guards default to permissive so existing callers/tests keep working; the
realtime layer opts into stricter settings via ``EntryGuardConfig``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Timeframe duration in minutes. Kept tiny and explicit rather than pulling a
# heavier parser: the bot only uses a handful of LTFs.
_TIMEFRAME_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "1d": 1440,
}


@dataclass(frozen=True)
class GateResult:
    valid: bool
    reason: str
    checks: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"valid": self.valid, "reason": self.reason, "checks": self.checks}


@dataclass(frozen=True)
class EntryGuardConfig:
    """Operator-tunable thresholds for the realtime entry guards.

    Defaults are permissive so legacy tests and backtests keep working. The
    realtime runtime overrides these from ``configs/realtime.json``.
    """

    enabled: bool = False
    closed_candle_tolerance_seconds: int = 5
    reject_regimes: tuple[str, ...] = ()
    short_observation_regimes: tuple[str, ...] = ()
    min_quote_volume_usd: float = 0.0
    max_spread_percent_of_stop: float = 0.0
    max_round_trip_cost_percent: float = 0.0
    taker_fee_rate: float = 0.001
    slippage_basis_points: float = 5.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EntryGuardConfig":
        data = data or {}

        def _tuple(key: str) -> tuple[str, ...]:
            value = data.get(key, ())
            if not isinstance(value, (list, tuple)):
                return ()
            return tuple(str(item).upper() for item in value if str(item))

        return cls(
            enabled=bool(data.get("enabled", False)),
            closed_candle_tolerance_seconds=int(
                data.get("closed_candle_tolerance_seconds", 5)
            ),
            reject_regimes=_tuple("reject_regimes"),
            short_observation_regimes=_tuple("short_observation_regimes"),
            min_quote_volume_usd=float(data.get("min_quote_volume_usd", 0.0)),
            max_spread_percent_of_stop=float(
                data.get("max_spread_percent_of_stop", 0.0)
            ),
            max_round_trip_cost_percent=float(
                data.get("max_round_trip_cost_percent", 0.0)
            ),
            taker_fee_rate=float(data.get("taker_fee_rate", 0.001)),
            slippage_basis_points=float(
                data.get("slippage_basis_points", 5.0)
            ),
        )


def _timeframe_minutes(timeframe: str) -> int | None:
    return _TIMEFRAME_MINUTES.get(str(timeframe).lower())


def _parse_timestamp(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp defensively. Returns None on failure.

    ``datetime.fromisoformat`` handles ``2026-01-01T00:00:00+00:00`` and the
    trailing-``Z`` form on 3.11+. We normalise ``Z`` for older runtimes.
    """
    if not raw:
        return None
    try:
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class ClosedCandleGuard:
    """Reject entries when the latest candle may still be forming.

    The bot polls on a fixed cadence (e.g. 60s). Decisions must be based on a
    candle that has actually closed for the chosen entry timeframe, otherwise a
    5m/15m signal can repaint as the candle keeps printing. Price ticks may
    still update SL/TP for existing positions; this guard only blocks *new*
    entries.
    """

    def __init__(self, tolerance_seconds: int = 5) -> None:
        self.tolerance_seconds = max(0, int(tolerance_seconds))

    def validate(
        self,
        *,
        last_candle_timestamp: str | None,
        now: datetime | None,
        timeframe: str,
    ) -> GateResult:
        minutes = _timeframe_minutes(timeframe)
        if minutes is None:
            return GateResult(False, "unknown_timeframe", {"timeframe": timeframe})

        if not last_candle_timestamp:
            return GateResult(False, "missing_candle_timestamp", {"timeframe": timeframe})

        if now is None:
            now = datetime.now(tz=timezone.utc)

        closed_at = _parse_timestamp(last_candle_timestamp)
        if closed_at is None:
            return GateResult(False, "invalid_candle_timestamp", {"timeframe": timeframe})

        candle_seconds = minutes * 60
        age_seconds = (now - closed_at).total_seconds() - candle_seconds
        valid = age_seconds >= -self.tolerance_seconds
        return GateResult(
            valid,
            "ok" if valid else "candle_not_closed",
            {
                "timeframe": timeframe,
                "candle_seconds": candle_seconds,
                "age_seconds": round(age_seconds, 2),
                "tolerance_seconds": self.tolerance_seconds,
            },
        )


class RegimeGate:
    """Reject entries in regimes flagged not-tradeable for the given side.

    ``reject_regimes`` blocks both directions. ``short_observation_regimes`` only
    downgrades SHORT entries to observation while short calibration is incomplete;
    BUY entries in those regimes still trade. Regime strings are compared
    case-insensitively after normalization to upper-case.
    """

    def __init__(
        self,
        reject_regimes: tuple[str, ...] = (),
        short_observation_regimes: tuple[str, ...] = (),
    ) -> None:
        self.reject_regimes = tuple(r.upper() for r in reject_regimes)
        self.short_observation_regimes = tuple(
            r.upper() for r in short_observation_regimes
        )

    def validate(self, *, action: str, regime: str) -> GateResult:
        normalized = str(regime or "MIXED").upper()
        if normalized in self.reject_regimes:
            return GateResult(
                False,
                f"regime_blocked:{normalized}",
                {"regime": normalized, "reject_regimes": list(self.reject_regimes)},
            )
        if str(action).upper() == "SELL" and normalized in self.short_observation_regimes:
            return GateResult(
                False,
                f"short_observation_regime:{normalized}",
                {
                    "regime": normalized,
                    "short_observation_regimes": list(
                        self.short_observation_regimes
                    ),
                },
            )
        return GateResult(True, "ok", {"regime": normalized})


class LiquiditySpreadGate:
    """Reject entries when spread / volume / round-trip cost is uneconomic.

    All thresholds default to 0 which means "not enforced". When an operator sets
    a positive threshold, the guard fetches a ticker snapshot (bid/ask/volume) and
    estimates the round-trip cost as ``2 * taker_fee + slippage`` versus the stop
    distance and expected reward.

    ponytail: estimate-only, add real L2 depth when exchange adapter exposes it.
    """

    def __init__(
        self,
        *,
        min_quote_volume_usd: float = 0.0,
        max_spread_percent_of_stop: float = 0.0,
        max_round_trip_cost_percent: float = 0.0,
        taker_fee_rate: float = 0.001,
        slippage_basis_points: float = 5.0,
    ) -> None:
        self.min_quote_volume_usd = min_quote_volume_usd
        self.max_spread_percent_of_stop = max_spread_percent_of_stop
        self.max_round_trip_cost_percent = max_round_trip_cost_percent
        self.taker_fee_rate = taker_fee_rate
        self.slippage_basis_points = slippage_basis_points

    def validate(
        self,
        *,
        ticker: dict[str, Any] | None,
        entry: float,
        stop_loss: float,
        take_profit: float,
    ) -> GateResult:
        checks: dict[str, Any] = {}
        if self.min_quote_volume_usd > 0:
            quote_volume = float(
                (ticker or {}).get("quoteVolume")
                or (ticker or {}).get("quote_volume")
                or 0.0
            )
            checks["quote_volume_usd"] = round(quote_volume, 2)
            if quote_volume < self.min_quote_volume_usd:
                return GateResult(
                    False,
                    "quote_volume_too_low",
                    {**checks, "min_quote_volume_usd": self.min_quote_volume_usd},
                )

        bid = float((ticker or {}).get("bid") or entry)
        ask = float((ticker or {}).get("ask") or entry)
        spread = max(ask - bid, 0.0)
        stop_distance = abs(entry - stop_loss)
        if (
            self.max_spread_percent_of_stop > 0
            and stop_distance > 0
        ):
            spread_pct = (spread / stop_distance) * 100
            checks["spread_percent_of_stop"] = round(spread_pct, 4)
            if spread_pct > self.max_spread_percent_of_stop:
                return GateResult(
                    False,
                    "spread_too_wide",
                    {**checks, "max_spread_percent_of_stop": self.max_spread_percent_of_stop},
                )

        if self.max_round_trip_cost_percent > 0:
            reward = abs(take_profit - entry)
            if reward > 0:
                round_trip_cost = (
                    2 * self.taker_fee_rate * 100
                    + self.slippage_basis_points / 100.0
                )
                cost_pct_of_reward = (round_trip_cost / (reward / entry * 100)) * 100
                checks["round_trip_cost_percent"] = round(round_trip_cost, 4)
                checks["cost_percent_of_reward"] = round(cost_pct_of_reward, 4)
                if cost_pct_of_reward > self.max_round_trip_cost_percent:
                    return GateResult(
                        False,
                        "round_trip_cost_too_high",
                        {**checks, "max_round_trip_cost_percent": self.max_round_trip_cost_percent},
                    )
        return GateResult(True, "ok", checks)


__all__ = [
    "EntryGuardConfig",
    "GateResult",
    "ClosedCandleGuard",
    "RegimeGate",
    "LiquiditySpreadGate",
]

