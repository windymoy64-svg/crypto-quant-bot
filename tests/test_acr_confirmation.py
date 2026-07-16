"""Tests for ACR+ confirmation bridge (Opsi C - filter/enhancement)."""

from __future__ import annotations

from app.core.models import Candle, TradingSignal
from app.strategies.acr_confirmation import (
    confirm_signal,
    enrich_trading_signal,
)


def _c(i: int, o: float, h: float, l: float, c: float, v: float = 1000.0) -> Candle:
    return Candle(
        symbol="TEST",
        timestamp=f"2026-07-16T00:{i:02d}:00Z",
        open=o, high=h, low=l, close=c, volume=v,
    )


def _htf_bullish() -> list[Candle]:
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


def _ltf_bullish() -> list[Candle]:
    return [
        _c(0, 100, 102, 99, 101),
        _c(1, 101, 106, 100, 105),
        _c(2, 105, 106, 100, 100.5),
        _c(3, 100.5, 108, 100, 107),
        _c(4, 107, 108, 105, 106),
        _c(5, 106, 106, 100, 105),
        _c(6, 105, 106, 96, 101),
        _c(7, 101, 105, 100.5, 104),
        _c(8, 104, 106, 103, 105.5),
        _c(9, 105.5, 108, 105, 107),
        _c(10, 107, 110, 106.5, 109),
    ]


def _flip(candles: list[Candle]) -> list[Candle]:
    return [
        Candle(
            symbol=c.symbol, timestamp=c.timestamp,
            open=200 - c.open, high=200 - c.low,
            low=200 - c.high, close=200 - c.close, volume=c.volume,
        )
        for c in candles
    ]


# confirm_signal ------------------------------------------------------------


def test_confirm_align_when_buy_matches_acr_bullish() -> None:
    r = confirm_signal(
        symbol="BTCUSDT", signal_action="BUY",
        htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert r.alignment == "align"
    assert r.veto is False
    assert r.acr_action == "BUY"
    assert r.confidence_multiplier > 1.0


def test_confirm_conflict_vetos_when_sell_opposite_bullish_acr() -> None:
    r = confirm_signal(
        symbol="BTCUSDT", signal_action="SELL",
        htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert r.alignment == "conflict"
    assert r.veto is True
    assert r.acr_action == "BUY"


def test_confirm_neutral_when_acr_holds() -> None:
    empty_htf = [_c(i, 100, 100.1, 99.9, 100) for i in range(10)]
    r = confirm_signal(
        symbol="BTCUSDT", signal_action="BUY",
        htf_candles=empty_htf, ltf_candles=_ltf_bullish(),
    )
    assert r.alignment == "neutral"
    assert r.veto is False
    assert r.confidence_multiplier < 1.0


def test_confirm_veto_on_neutral_when_configured() -> None:
    empty_htf = [_c(i, 100, 100.1, 99.9, 100) for i in range(10)]
    r = confirm_signal(
        symbol="BTCUSDT", signal_action="BUY",
        htf_candles=empty_htf, ltf_candles=_ltf_bullish(),
        veto_on_neutral=True,
    )
    assert r.veto is True


def test_confirm_skips_when_candles_missing() -> None:
    r = confirm_signal(
        symbol="X", signal_action="BUY", htf_candles=[], ltf_candles=[],
    )
    assert r.alignment == "neutral"
    assert r.veto is False


def test_confirm_bearish_align() -> None:
    r = confirm_signal(
        symbol="ETHUSDT", signal_action="SELL",
        htf_candles=_flip(_htf_bullish()), ltf_candles=_flip(_ltf_bullish()),
    )
    assert r.alignment == "align"
    assert r.acr_action == "SELL"


# enrich_trading_signal ------------------------------------------------------


def _make_signal(action: str = "BUY", confidence: float = 80.0) -> TradingSignal:
    return TradingSignal(
        symbol="BTCUSDT",
        action=action,   # type: ignore[arg-type]
        score=90.0, confidence=confidence,
        entry=100.0, stop_loss=95.0,
        take_profit=[110.0, 120.0, 130.0],
        risk_reward=2.0, risk="MEDIUM",
        strategy="Weighted Rule Engine", meta={},
    )


def test_enrich_trading_signal_align_updates_confidence_and_meta() -> None:
    signal = _make_signal("BUY", 80.0)
    enriched, confirmation = enrich_trading_signal(
        signal, htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert confirmation.alignment == "align"
    assert enriched.action == "BUY"
    assert enriched.confidence > signal.confidence
    assert "acr_confirmation" in enriched.meta


def test_enrich_trading_signal_conflict_vetos_to_skip() -> None:
    signal = _make_signal("SELL", 80.0)
    enriched, confirmation = enrich_trading_signal(
        signal, htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert confirmation.veto is True
    assert enriched.action == "SKIP"
    assert enriched.meta.get("veto_reason", "").startswith("acr_veto_")


def test_enrich_signal_dict_path() -> None:
    signal = {
        "symbol": "BTCUSDT", "action": "BUY", "confidence": 80.0,
        "entry": 100.0, "stop_loss": 95.0,
        "take_profit": [110.0, 120.0, 130.0], "meta": {},
    }
    enriched, confirmation = enrich_trading_signal(
        signal, htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert isinstance(enriched, dict)
    assert enriched["action"] == "BUY"
    assert enriched["confidence"] > 80.0
    assert "acr_confirmation" in enriched["meta"]


def test_enrich_signal_skips_non_directional_action() -> None:
    signal = _make_signal("WATCH", 80.0)
    enriched, confirmation = enrich_trading_signal(
        signal, htf_candles=_htf_bullish(), ltf_candles=_ltf_bullish(),
    )
    assert enriched.action == "WATCH"
    assert "signal_action_not_buy_or_sell_skip" in confirmation.reasons
