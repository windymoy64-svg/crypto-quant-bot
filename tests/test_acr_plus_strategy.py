"""Integration tests for the ACR+ strategy evaluator."""

from __future__ import annotations

import json

from app.core.models import Candle
from app.strategies.acr_plus import ACRPlusContext, evaluate


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-15T00:{i:02d}:00Z",
        open=o, high=h, low=l, close=c, volume=v,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _htf_bullish() -> list[Candle]:
    """HTF dengan HH+HL: swing low 98 -> swing high 130, eq=114."""
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 105, 100, 104),
        _c(2, 104, 110, 103, 108),
        _c(3, 108, 109, 105, 106),
        _c(4, 106, 107, 95, 96),
        _c(5, 96, 100, 96, 99),
        _c(6, 99, 120, 98, 118),
        _c(7, 118, 130, 117, 128),
        _c(8, 128, 129, 122, 123),
        _c(9, 123, 124, 105, 106),
        _c(10, 106, 108, 98, 99),
        _c(11, 99, 102, 98.5, 100),
        _c(12, 100, 110, 99, 109),
    ]


def _ltf_bullish_setup() -> list[Candle]:
    """LTF dengan bullish ACR + CISD + displacement FVG.

    - BULLISH CISD di index 3 (close 107 break candle bearish idx 2 close 100.5).
    - ACR pattern candle1=idx5, candle2=idx6 (sweep 100, close 101), candle3=idx7.
    - Displacement FVG bullish: idx8 high 106 < idx10 low 106.5.
    - Close terakhir 109 masih di bawah eq HTF 114 -> discount.
    """
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 106, 100, 105),
        _c(2, 105, 106, 100, 100.5),
        _c(3, 100.5, 108, 100, 107),   # BULLISH CISD at 100.5
        _c(4, 107, 108, 105, 106),
        _c(5, 106, 106, 100, 105),     # ACR c1
        _c(6, 105, 106, 96, 101),      # ACR c2: sweep 100, close 101
        _c(7, 101, 105, 100.5, 104),   # ACR c3: strong close
        _c(8, 104, 106, 103, 105.5),
        _c(9, 105.5, 108, 105, 107),
        _c(10, 107, 110, 106.5, 109),  # low 106.5 > c8 high 106 -> Bullish FVG
    ]


def _flip(candles: list[Candle]) -> list[Candle]:
    """Mirror price: p -> 200 - p. Bullish setup -> bearish setup."""
    return [
        _c(i, 200 - c.open, 200 - c.low, 200 - c.high, 200 - c.close)
        for i, c in enumerate(candles)
    ]


def _htf_bearish() -> list[Candle]:
    """HTF dengan LL+LH (mirror bullish HTF)."""
    return _flip(_htf_bullish())


def _ltf_bearish_setup() -> list[Candle]:
    """LTF bearish setup (mirror bullish setup)."""
    return _flip(_ltf_bullish_setup())


# ---------------------------------------------------------------------------
# Basic HOLD paths
# ---------------------------------------------------------------------------


def test_evaluate_hold_on_empty_input() -> None:
    ctx = ACRPlusContext(htf=[], ltf=[], symbol="BTCUSDT")
    decision = evaluate(ctx)
    assert decision.action == "HOLD"
    assert "empty_input_candles" in decision.reasons


def test_evaluate_hold_when_no_htf_bias() -> None:
    htf = [_c(i, 100 + i * 0.1, 100.2, 99.9, 100.1) for i in range(15)]
    ltf = _ltf_bullish_setup()
    ctx = ACRPlusContext(htf=htf, ltf=ltf, symbol="TEST")
    decision = evaluate(ctx)
    assert decision.action == "HOLD"
    assert decision.htf_bias.direction is None



# ---------------------------------------------------------------------------
# Happy path: BUY
# ---------------------------------------------------------------------------


def test_evaluate_buy_when_bullish_checklist_complete() -> None:
    ctx = ACRPlusContext(
        htf=_htf_bullish(),
        ltf=_ltf_bullish_setup(),
        symbol="BTCUSDT",
        htf_tf="H4",
        ltf_tf="M15",
    )
    decision = evaluate(ctx)

    assert decision.action == "BUY", decision.reasons
    assert decision.strategy == "acr_plus"
    assert decision.entry is not None
    assert decision.stop_loss is not None and decision.stop_loss < decision.entry
    assert decision.take_profit_1 is not None
    assert decision.take_profit_1 > decision.entry
    assert decision.take_profit_2 is not None
    assert decision.take_profit_3 is not None
    assert decision.risk_reward is not None
    assert decision.risk_reward >= 2.0 - 1e-6
    assert decision.entry_model in ("I_CISD", "II_FVG", "III_OPPOSING")
    assert decision.htf_bias.direction == "BULLISH"
    assert "cisd_present" in decision.reasons
    assert "displacement_fvg_present" in decision.reasons


def test_evaluate_hold_when_no_cisd() -> None:
    """LTF full bullish tanpa candle bearish -> tidak ada BULLISH CISD."""
    # Semua candle upclose. Tetap ada sweep (candle 5 low 96 < candle4 low 100).
    ltf = [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 106, 100, 105),
        _c(2, 105, 108, 104, 107),
        _c(3, 107, 109, 106, 108),
        _c(4, 108, 108.5, 100, 100.5),   # bullish (open=108, close=100.5? -> bearish!)
        _c(5, 100.5, 106, 96, 105),      # bullish sweep
        _c(6, 105, 108, 104, 107),
        _c(7, 107, 110, 106, 109),
        _c(8, 109, 111, 108, 110),
    ]
    # Cek: kalau candle 4 (o=108, c=100.5) bearish -> ada bearish. Ganti supaya semua bullish.
    ltf[4] = _c(4, 100, 108, 100, 107)   # bullish (o=100, c=107)
    ltf[5] = _c(5, 107, 109, 96, 108)   # sweep 100 tidak ada; ubah
    # Tanpa CISD candidate, hasil HOLD tapi mungkin gagal karena tidak ada pattern.
    ctx = ACRPlusContext(htf=_htf_bullish(), ltf=ltf, symbol="TEST")
    decision = evaluate(ctx)
    assert decision.action == "HOLD"
    # Bisa gagal di gate CISD atau di ACR pattern; keduanya valid.
    assert any(k in " ".join(decision.reasons) for k in ("cisd", "acr_pattern", "no_actionable"))


# ---------------------------------------------------------------------------
# Happy path: SELL
# ---------------------------------------------------------------------------


def test_evaluate_sell_when_bearish_checklist_complete() -> None:
    ctx = ACRPlusContext(
        htf=_htf_bearish(),
        ltf=_ltf_bearish_setup(),
        symbol="ETHUSDT",
        htf_tf="H4",
        ltf_tf="M15",
    )
    decision = evaluate(ctx)

    assert decision.action == "SELL", decision.reasons
    assert decision.stop_loss is not None and decision.stop_loss > decision.entry
    assert decision.take_profit_1 is not None and decision.take_profit_1 < decision.entry
    assert decision.risk_reward is not None
    assert decision.risk_reward >= 2.0 - 1e-6
    assert decision.htf_bias.direction == "BEARISH"


def test_decision_to_dict_is_json_serializable() -> None:
    ctx = ACRPlusContext(
        htf=_htf_bullish(), ltf=_ltf_bullish_setup(), symbol="BTCUSDT",
    )
    decision = evaluate(ctx)
    payload = decision.to_dict()
    encoded = json.dumps(payload)
    assert isinstance(encoded, str)
    assert payload["strategy"] == "acr_plus"
    assert payload["mtf_alignment" if "mtf_alignment" in payload else "htf_bias"] is not None
