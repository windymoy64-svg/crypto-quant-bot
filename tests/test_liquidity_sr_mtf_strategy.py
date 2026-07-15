from __future__ import annotations

from app.core.models import Candle
from app.strategies.liquidity_sr_mtf import (
    MTFAlignment,
    MTFContext,
    StrategyDecision,
    evaluate,
)


def _c(
    index: int,
    open_: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1000.0,
) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-06T00:{index:02d}:00Z",
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


# ---------------------------------------------------------------------------
# Fixtures shared across happy-path tests
# ---------------------------------------------------------------------------


def _big_up_candles() -> list[Candle]:
    """Big TF fixture with an UP structure and a fresh support zone at 95-96."""
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # swing high 110 (HH)
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),      # swing low 95 (HL) -> support zone
        _c(5, 96, 100, 96, 99),
        _c(6, 99, 108, 98, 107),
        _c(7, 107, 115, 106, 113),   # swing high 115 (HH) -> UP
        _c(8, 113, 114, 108, 109),
        _c(9, 109, 110, 100, 101),
        _c(10, 101, 105, 100, 104),
        _c(11, 104, 105, 96, 96),    # close 96 sits in support zone
    ]


def _mid_up_candles() -> list[Candle]:
    """Mid TF fixture with a confirmed SELL_SIDE sweep at 95 and fresh BUY_SIDE above."""
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # BUY_SIDE pool at 110 (fresh)
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),      # SELL_SIDE pool at 95
        _c(5, 96, 100, 95.5, 99),
        _c(6, 99, 103, 98, 102),
        _c(7, 102, 105, 100, 103),
        _c(8, 103, 106, 92, 98),      # wick 92 sweeps 95 then close 98 -> confirmed
        _c(9, 98, 100, 96, 99),
        _c(10, 99, 101, 96, 100),
        _c(11, 100, 101, 96, 97),
    ]


def _small_bullish_engulfing() -> list[Candle]:
    return [
        _c(0, 97, 98, 96, 97),
        _c(1, 97, 98, 96, 96),
        _c(2, 96, 97, 94, 94.5),
        _c(3, 94.5, 95, 93, 93.5),    # bearish
        _c(4, 93, 96.5, 93, 96),      # bullish engulfing
    ]


def _small_neutral() -> list[Candle]:
    # Close inside support zone (95-96, with tolerance ~ [94.9, 96.1]) but
    # neither engulfing nor pin bar. Body-dominated bullish candles so
    # body/total > 0.35 and prev/curr direction don't form an engulfing pair.
    return [
        _c(0, 95.80, 95.90, 95.78, 95.88),
        _c(1, 95.88, 95.95, 95.86, 95.93),
        _c(2, 95.93, 95.99, 95.91, 95.97),
        _c(3, 95.97, 96.02, 95.95, 96.00),
        _c(4, 96.00, 96.05, 95.98, 96.03),
    ]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_evaluate_emits_buy_when_all_hard_gates_pass() -> None:
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=_small_bullish_engulfing(),
    )

    decision = evaluate(ctx)

    assert decision.action == "BUY"
    assert decision.strategy == "liquidity_sr_mtf"
    assert decision.entry == 96
    assert decision.stop_loss is not None and decision.stop_loss < decision.entry
    assert decision.take_profit_1 is not None
    assert decision.take_profit_2 is not None
    # Minimum 1:2 RR enforced.
    risk = decision.entry - decision.stop_loss
    reward = decision.take_profit_1 - decision.entry
    assert reward >= 2 * risk - 1e-9

    assert "big_tf_trend_up" in decision.reasons
    assert "price_in_support_zone" in decision.reasons
    assert "sell_side_liquidity_swept_confirmed" in decision.reasons
    assert "fresh_buy_side_target_available" in decision.reasons
    assert any(r.startswith("small_tf_confirmation_") for r in decision.reasons)

    assert decision.anchor is not None
    assert "support_zone" in decision.anchor
    assert "sweep_event" in decision.anchor
    assert "fresh_target_pool" in decision.anchor


def test_evaluate_is_deterministic() -> None:
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=_small_bullish_engulfing(),
    )

    first = evaluate(ctx)
    second = evaluate(ctx)

    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# Hard-gate HOLD paths
# ---------------------------------------------------------------------------


def test_evaluate_holds_on_empty_candles() -> None:
    ctx = MTFContext(big=[], mid=[], small=[])
    decision = evaluate(ctx)

    assert decision.action == "HOLD"
    assert decision.reasons == ["empty_candles"]
    assert decision.entry is None
    assert decision.stop_loss is None
    assert decision.meta.get("veto") == "empty_candles"


def test_evaluate_holds_when_big_tf_trend_is_side() -> None:
    # Sequence HH, HL, HH, LL -> last high is HH but last low is LL -> SIDE.
    sideways_big = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # HH
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 95, 96),      # HL
        _c(5, 96, 100, 96, 99),
        _c(6, 99, 108, 98, 107),
        _c(7, 107, 115, 106, 113),   # HH
        _c(8, 113, 114, 108, 109),
        _c(9, 109, 110, 90, 92),      # LL (90 < 95)
        _c(10, 92, 100, 92, 99),
        _c(11, 99, 102, 98, 101),
    ]
    ctx = MTFContext(
        big=sideways_big,
        mid=_mid_up_candles(),
        small=_small_bullish_engulfing(),
    )
    decision = evaluate(ctx)

    assert decision.action == "HOLD"
    assert "big_tf_trend_side" in decision.reasons
    assert decision.meta.get("veto") == "big_tf_trend_side"
    assert decision.mtf_alignment.big_trend == "SIDE"



def test_evaluate_holds_when_price_is_far_above_support_zone() -> None:
    # Same big TF (UP) but small TF close nowhere near the support zone
    # at 95-96. Anchor gate must fail.
    far_small = [
        _c(0, 200, 201, 199, 200),
        _c(1, 200, 202, 199, 201),
        _c(2, 201, 203, 200, 202),
        _c(3, 202, 203, 200, 201),
        _c(4, 201, 202, 200, 201),
    ]
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=far_small,
    )
    decision = evaluate(ctx)

    assert decision.action == "HOLD"
    assert decision.meta.get("veto") == "no_active_support_zone"


def test_evaluate_holds_when_no_confirmed_sweep_on_mid_tf() -> None:
    # Mid TF without any confirmed sweep event: uniform gentle uptrend,
    # no candle wick pierces a swing low and closes back.
    mid_no_sweep = [
        _c(0, 100, 101, 99, 100),
        _c(1, 100, 102, 100, 101),
        _c(2, 101, 103, 101, 102),
        _c(3, 102, 104, 102, 103),
        _c(4, 103, 105, 103, 104),
        _c(5, 104, 106, 104, 105),
        _c(6, 105, 107, 105, 106),
        _c(7, 106, 108, 106, 107),
        _c(8, 107, 109, 107, 108),
    ]
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=mid_no_sweep,
        small=_small_bullish_engulfing(),
    )
    decision = evaluate(ctx)

    assert decision.action == "HOLD"
    assert decision.meta.get("veto") == "no_confirmed_sell_side_sweep"


def test_evaluate_holds_without_small_tf_confirmation() -> None:
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=_small_neutral(),
    )
    decision = evaluate(ctx)

    assert decision.action == "HOLD"
    assert decision.meta.get("veto") == "no_small_tf_confirmation"


# ---------------------------------------------------------------------------
# JSON serializability + payload contract
# ---------------------------------------------------------------------------


def test_decision_payload_is_json_serializable() -> None:
    import json

    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=_small_bullish_engulfing(),
    )
    decision = evaluate(ctx)
    payload = decision.to_dict()

    encoded = json.dumps(payload)
    assert isinstance(encoded, str)
    assert payload["action"] == "BUY"
    assert payload["strategy"] == "liquidity_sr_mtf"
    assert "mtf_alignment" in payload
    assert payload["mtf_alignment"]["big_trend"] == "UP"
    assert "anchor" in payload
    assert "reasons" in payload and payload["reasons"]


def test_hold_payload_carries_veto_reason() -> None:
    import json

    ctx = MTFContext(big=[], mid=[], small=[])
    payload = evaluate(ctx).to_dict()
    encoded = json.dumps(payload)

    assert isinstance(encoded, str)
    assert payload["action"] == "HOLD"
    assert payload["meta"]["veto"] == "empty_candles"
    assert payload["anchor"] is None
    assert payload["entry"] is None


def test_mtf_alignment_reports_trend_per_timeframe() -> None:
    ctx = MTFContext(
        big=_big_up_candles(),
        mid=_mid_up_candles(),
        small=_small_bullish_engulfing(),
    )
    decision = evaluate(ctx)

    align = decision.mtf_alignment
    assert isinstance(align, MTFAlignment)
    assert align.big_trend == "UP"
    assert align.mid_trend in {"UP", "DOWN", "SIDE"}
    assert align.small_trend in {"UP", "DOWN", "SIDE"}
    assert isinstance(align.aligned, bool)



# ---------------------------------------------------------------------------
# SELL happy path (mirror of BUY)
# ---------------------------------------------------------------------------


def _big_down_candles() -> list[Candle]:
    """Big TF fixture with a DOWN structure and a fresh resistance zone."""
    return [
        _c(0, 100, 105, 99, 104),
        _c(1, 104, 106, 98, 99),
        _c(2, 99, 100, 90, 92),      # first swing low (HL seed)
        _c(3, 92, 96, 91, 95),
        _c(4, 95, 105, 94, 96),       # first swing high (HH seed)
        _c(5, 96, 100, 85, 87),       # LL
        _c(6, 87, 93, 86, 92),
        _c(7, 92, 100, 91, 99),
        _c(8, 99, 102, 90, 91),       # LH -> confirms DOWN
        _c(9, 91, 95, 80, 82),        # LL
        _c(10, 82, 92, 81, 90),
        _c(11, 90, 102, 88, 100),     # pullback to resistance ~ 96-105
    ]


def _mid_down_candles() -> list[Candle]:
    """Mid TF fixture with a confirmed BUY_SIDE sweep and fresh SELL_SIDE below."""
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),   # swing high 110 -> BUY_SIDE pool
        _c(3, 108, 109, 104, 105),
        _c(4, 105, 106, 90, 91),      # swing low 90 -> SELL_SIDE pool (fresh)
        _c(5, 91, 95, 90.5, 94),
        _c(6, 94, 100, 93, 99),
        _c(7, 99, 105, 98, 103),
        _c(8, 103, 115, 102, 100),   # wick 115 sweeps 110 then close 100 -> confirmed
        _c(9, 100, 103, 98, 101),
        _c(10, 101, 104, 99, 102),
        _c(11, 102, 105, 99, 100),
    ]


def _small_bearish_engulfing() -> list[Candle]:
    return [
        _c(0, 99, 100, 98, 99.5),
        _c(1, 99.5, 100, 98, 99),
        _c(2, 99, 100.5, 98.5, 100),
        _c(3, 99.5, 101, 99, 100.5),   # bullish
        _c(4, 101, 101.5, 99, 99.5),    # bearish engulfing
    ]


def test_evaluate_emits_sell_when_all_hard_gates_pass() -> None:
    ctx = MTFContext(
        big=_big_down_candles(),
        mid=_mid_down_candles(),
        small=_small_bearish_engulfing(),
    )

    decision = evaluate(ctx)

    assert decision.action == "SELL"
    assert decision.strategy == "liquidity_sr_mtf"
    assert decision.entry == 99.5
    assert decision.stop_loss is not None and decision.stop_loss > decision.entry
    assert decision.take_profit_1 is not None
    assert decision.take_profit_2 is not None
    # Minimum 1:2 RR enforced (short side).
    risk = decision.stop_loss - decision.entry
    reward = decision.entry - decision.take_profit_1
    assert reward >= 2 * risk - 1e-9

    assert "big_tf_trend_down" in decision.reasons
    assert "price_in_resistance_zone" in decision.reasons
    assert "buy_side_liquidity_swept_confirmed" in decision.reasons
    assert "fresh_sell_side_target_available" in decision.reasons
    assert any(r.startswith("small_tf_confirmation_") for r in decision.reasons)

    assert decision.anchor is not None
    assert "resistance_zone" in decision.anchor
    assert "sweep_event" in decision.anchor
    assert "fresh_target_pool" in decision.anchor
    assert decision.mtf_alignment.big_trend == "DOWN"


def test_evaluate_sell_payload_is_json_serializable() -> None:
    import json

    ctx = MTFContext(
        big=_big_down_candles(),
        mid=_mid_down_candles(),
        small=_small_bearish_engulfing(),
    )
    payload = evaluate(ctx).to_dict()
    encoded = json.dumps(payload)

    assert isinstance(encoded, str)
    assert payload["action"] == "SELL"
    assert payload["mtf_alignment"]["big_trend"] == "DOWN"
    assert "resistance_zone" in payload["anchor"]

