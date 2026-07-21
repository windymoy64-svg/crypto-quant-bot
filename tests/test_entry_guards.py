"""Tests for entry guards: ClosedCandleGuard, RegimeGate, LiquiditySpreadGate."""

from __future__ import annotations

from datetime import datetime, timezone

from app.risk.entry_guards import (
    ClosedCandleGuard,
    EntryGuardConfig,
    LiquiditySpreadGate,
    RegimeGate,
)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ---------------------------------------------------------------------------
# EntryGuardConfig
# ---------------------------------------------------------------------------


def test_entry_guard_config_defaults_disabled() -> None:
    cfg = EntryGuardConfig.from_dict(None)
    assert cfg.enabled is False
    assert cfg.reject_regimes == ()
    assert cfg.short_observation_regimes == ()
    assert cfg.min_quote_volume_usd == 0.0


def test_entry_guard_config_from_dict() -> None:
    cfg = EntryGuardConfig.from_dict({
        "enabled": True,
        "reject_regimes": ["MIXED", "RANGING"],
        "short_observation_regimes": ["TRENDING_BEARISH"],
        "max_spread_percent_of_stop": 15.0,
        "taker_fee_rate": 0.0002,
    })
    assert cfg.enabled is True
    assert cfg.reject_regimes == ("MIXED", "RANGING")
    assert cfg.short_observation_regimes == ("TRENDING_BEARISH",)
    assert cfg.max_spread_percent_of_stop == 15.0


# ---------------------------------------------------------------------------
# ClosedCandleGuard
# ---------------------------------------------------------------------------


def test_closed_candle_passes_for_old_candle() -> None:
    guard = ClosedCandleGuard(tolerance_seconds=5)
    # 15m candle opened 20 minutes ago → safely closed.
    ts = "2026-01-01T00:00:00+00:00"
    now = datetime(2026, 1, 1, 0, 20, 0, tzinfo=timezone.utc)
    result = guard.validate(last_candle_timestamp=ts, now=now, timeframe="15m")
    assert result.valid is True
    assert result.reason == "ok"


def test_closed_candle_rejects_in_progress_candle() -> None:
    guard = ClosedCandleGuard(tolerance_seconds=5)
    # 15m candle opened 5 minutes ago → still forming.
    ts = "2026-01-01T00:00:00+00:00"
    now = datetime(2026, 1, 1, 0, 5, 0, tzinfo=timezone.utc)
    result = guard.validate(last_candle_timestamp=ts, now=now, timeframe="15m")
    assert result.valid is False
    assert result.reason == "candle_not_closed"


def test_closed_candle_rejects_unknown_timeframe() -> None:
    guard = ClosedCandleGuard()
    result = guard.validate(
        last_candle_timestamp="2026-01-01T00:00:00+00:00",
        now=_now(),
        timeframe="99m",
    )
    assert result.valid is False
    assert "unknown_timeframe" in result.reason


def test_closed_candle_rejects_missing_timestamp() -> None:
    guard = ClosedCandleGuard()
    result = guard.validate(
        last_candle_timestamp=None,
        now=_now(),
        timeframe="15m",
    )
    assert result.valid is False


# ---------------------------------------------------------------------------
# RegimeGate
# ---------------------------------------------------------------------------


def test_regime_gate_blocks_rejected_regime() -> None:
    gate = RegimeGate(reject_regimes=("MIXED", "RANGING"))
    result = gate.validate(action="BUY", regime="MIXED")
    assert result.valid is False
    assert "MIXED" in result.reason


def test_regime_gate_allows_trending_bullish_for_buy() -> None:
    gate = RegimeGate(reject_regimes=("MIXED",))
    result = gate.validate(action="BUY", regime="TRENDING_BULLISH")
    assert result.valid is True


def test_regime_gate_blocks_short_in_observation_regime() -> None:
    gate = RegimeGate(short_observation_regimes=("TRENDING_BEARISH",))
    result = gate.validate(action="SELL", regime="TRENDING_BEARISH")
    assert result.valid is False
    assert "short_observation_regime" in result.reason


def test_regime_gate_allows_buy_in_short_observation_regime() -> None:
    gate = RegimeGate(short_observation_regimes=("TRENDING_BEARISH",))
    result = gate.validate(action="BUY", regime="TRENDING_BEARISH")
    assert result.valid is True


def test_regime_gate_case_insensitive() -> None:
    gate = RegimeGate(reject_regimes=("mixed",))
    result = gate.validate(action="BUY", regime="MIXED")
    assert result.valid is False


# ---------------------------------------------------------------------------
# LiquiditySpreadGate
# ---------------------------------------------------------------------------


def test_liquidity_gate_passes_when_all_zero_thresholds() -> None:
    gate = LiquiditySpreadGate()
    result = gate.validate(
        ticker={"bid": 99.9, "ask": 100.1},
        entry=100.0,
        stop_loss=98.0,
        take_profit=104.0,
    )
    assert result.valid is True


def test_liquidity_gate_blocks_wide_spread() -> None:
    gate = LiquiditySpreadGate(max_spread_percent_of_stop=10.0)
    # spread = 2.0, stop_distance = 2.0 → spread = 100% of stop.
    result = gate.validate(
        ticker={"bid": 99.0, "ask": 101.0},
        entry=100.0,
        stop_loss=98.0,
        take_profit=104.0,
    )
    assert result.valid is False
    assert result.reason == "spread_too_wide"


def test_liquidity_gate_passes_narrow_spread() -> None:
    gate = LiquiditySpreadGate(max_spread_percent_of_stop=10.0)
    # spread = 0.1, stop_distance = 2.0 → 5% of stop.
    result = gate.validate(
        ticker={"bid": 99.95, "ask": 100.05},
        entry=100.0,
        stop_loss=98.0,
        take_profit=104.0,
    )
    assert result.valid is True


def test_liquidity_gate_blocks_low_volume() -> None:
    gate = LiquiditySpreadGate(min_quote_volume_usd=1_000_000.0)
    result = gate.validate(
        ticker={"bid": 99.9, "ask": 100.1, "quoteVolume": 500.0},
        entry=100.0,
        stop_loss=98.0,
        take_profit=104.0,
    )
    assert result.valid is False
    assert result.reason == "quote_volume_too_low"
