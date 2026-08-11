from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from run_realtime import _limit_entry_invalid_reason


def _candle(timestamp: str, *, open_price: float = 100.0, close: float = 100.0):
    return SimpleNamespace(
        timestamp=timestamp, open=open_price, close=close,
        high=max(open_price, close) + 0.2,
        low=min(open_price, close) - 0.2,
    )


def _reading(*, regime: str = "TRENDING_BULLISH", phase: str = "fresh"):
    return SimpleNamespace(
        regime=regime, momentum_phase={"phase": phase}, structure_breaks=[],
        entry_zone=(99.0, 101.0),
    )


def _metadata(created_at: str, *, bias: str = "BULLISH"):
    return {
        "created_at": created_at,
        "role": "entry",
        "entry_context": {
            "bias": bias, "regime": "TRENDING_BULLISH",
            "entry_zone": [99.0, 101.0],
            "invalidation_level": 97.0 if bias == "BULLISH" else 103.0,
        },
    }


def test_limit_expires_after_24_five_minute_candles() -> None:
    created = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    candles = [
        _candle((created + timedelta(minutes=5 * index)).isoformat())
        for index in range(25)
    ]
    reason = _limit_entry_invalid_reason(
        order={}, metadata=_metadata(created.isoformat()), candles_5m=candles,
        reading=_reading(), now=created + timedelta(minutes=125),
    )
    assert reason == "limit_order_expired_24_candles_5m"


def test_limit_cancels_when_invalidation_breaks() -> None:
    created = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    candles = [_candle(created.isoformat(), close=96.5)]
    reason = _limit_entry_invalid_reason(
        order={}, metadata=_metadata(created.isoformat()), candles_5m=candles,
        reading=_reading(), now=created + timedelta(minutes=5),
    )
    assert reason == "limit_entry_invalidation_broken"


def test_limit_cancels_when_regime_changes() -> None:
    created = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    reason = _limit_entry_invalid_reason(
        order={}, metadata=_metadata(created.isoformat()),
        candles_5m=[_candle(created.isoformat())],
        reading=_reading(regime="RANGING"), now=created + timedelta(minutes=5),
    )
    assert reason == "limit_entry_regime_invalid"


def test_limit_cancels_when_momentum_becomes_invalid() -> None:
    created = datetime(2026, 8, 11, 0, 0, tzinfo=UTC)
    reason = _limit_entry_invalid_reason(
        order={}, metadata=_metadata(created.isoformat()),
        candles_5m=[_candle(created.isoformat())],
        reading=_reading(phase="extended"), now=created + timedelta(minutes=5),
    )
    assert reason == "limit_entry_momentum_invalid"
