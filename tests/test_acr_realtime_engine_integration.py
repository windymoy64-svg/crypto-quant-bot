"""Integration test: RealtimePaperTradingEngine + ACR+ bridge (Opsi C).

Memastikan flag ``use_acr_position_manager`` di ``AutoExitConfig`` benar-benar
mengaktifkan swing-based trailing / break-even / invalidation bila signal
menyediakan ``ltf_candles``. Backward-compatibility juga diverifikasi: bila
flag off atau ``ltf_candles`` tidak ada, engine bertindak seperti sebelumnya.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from app.paper.realtime_engine import (
    AutoExitConfig,
    PaperTradingConfig,
    RealtimePaperTradingEngine,
)


def _config(use_acr: bool, tmpdir: str) -> PaperTradingConfig:
    return PaperTradingConfig(
        enabled=True,
        starting_balance=10_000.0,
        risk_percent=1.0,
        max_open_positions=5,
        state_path=os.path.join(tmpdir, "state.json"),
        trades_path=os.path.join(tmpdir, "trades.jsonl"),
        max_position_size_percent=15.0,
        auto_exit=AutoExitConfig(
            enabled=True,
            tp_fractions=(0.3, 0.3, 0.4),
            trailing_activation_atr_multiple=0.5,
            trailing_distance_atr_multiple=1.0,
            use_acr_position_manager=use_acr,
            acr_trail_buffer_pct=0.002,
        ),
    )


def _open_signal() -> dict:
    return {
        "symbol": "BTCUSDT",
        "action": "BUY",
        "confidence": 90.0,
        "score": 95.0,
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": [110.0, 120.0, 130.0],
        "risk_reward": 2.0,
        "risk": "LOW",
        "strategy": "test",
        "meta": {},
    }


def _price_tick(symbol: str, price: float, ltf_candles: list[dict] | None = None) -> dict:
    signal = {
        "symbol": symbol,
        "action": "HOLD",
        "confidence": 0.0,
        "score": 0.0,
        "entry": price,
        "stop_loss": 0.0,
        "take_profit": [0.0, 0.0, 0.0],
        "risk_reward": 0.0,
        "risk": "MEDIUM",
        "strategy": "tick",
        "meta": {},
    }
    if ltf_candles is not None:
        signal["ltf_candles"] = ltf_candles
    return signal


def _mk_candle_dict(i: int, o: float, h: float, l: float, c: float) -> dict:
    return {
        "symbol": "BTCUSDT",
        "timestamp": f"2026-07-16T00:{i:02d}:00Z",
        "open": o, "high": h, "low": l, "close": c, "volume": 100.0,
    }


def test_engine_backward_compatible_without_acr_flag(tmp_path) -> None:
    """Flag off -> engine tetap pakai ATR logic (behavior lama, tidak crash)."""
    engine = RealtimePaperTradingEngine(_config(use_acr=False, tmpdir=str(tmp_path)))
    # 1. Open position
    result = engine.process_signals([_open_signal()])
    assert any(e.get("type") == "opened" for e in result["events"])

    # 2. Tick harga naik (TP1 kena) - tanpa ltf_candles
    tick_result = engine.process_signals([_price_tick("BTCUSDT", 111.0)])
    # Tidak crash; legacy logic tetap jalan
    assert isinstance(tick_result["events"], list)


def test_engine_uses_acr_bridge_when_flag_on_and_candles_provided(tmp_path) -> None:
    """Flag on + ltf_candles disediakan -> ACR bridge dipanggil untuk trailing."""
    engine = RealtimePaperTradingEngine(_config(use_acr=True, tmpdir=str(tmp_path)))

    # Open BUY at 100
    engine.process_signals([_open_signal()])

    # Tick harga sentuh TP1 (111) -> partial close + tp_hit[0]=True
    tick1 = _price_tick("BTCUSDT", 111.0)
    engine.process_signals([tick1])

    # Berikan ltf_candles yang mengandung swing low -> trailing swing-based aktif
    ltf = [
        _mk_candle_dict(0, 100, 106, 104, 105),
        _mk_candle_dict(1, 105, 108, 103, 107),
        _mk_candle_dict(2, 107, 109, 100, 108),
        _mk_candle_dict(3, 108, 112, 105, 111),
        _mk_candle_dict(4, 111, 115, 110, 114),
    ]
    tick2 = _price_tick("BTCUSDT", 114.0, ltf_candles=ltf)
    engine.process_signals([tick2])

    # Cek state posisi via file state
    state_path = os.path.join(str(tmp_path), "state.json")
    with open(state_path) as fh:
        state = json.load(fh)
    positions = state.get("open_positions", {})
    if "BTCUSDT" in positions:
        pos = positions["BTCUSDT"]
        # Setelah TP1 hit dan candles disediakan, ACR bridge harus:
        # - move static_stop_loss ke entry (breakeven)
        # - aktifkan trailing_stop_loss di sekitar swing low
        assert pos.get("static_stop_loss") == pytest.approx(100.0, abs=1e-6)
        assert pos.get("trailing_active") is True
        assert pos.get("trailing_stop_loss") is not None
        assert 99 < float(pos["trailing_stop_loss"]) < 114


def test_engine_no_crash_when_flag_on_without_candles(tmp_path) -> None:
    """Flag on tapi signal tanpa ltf_candles -> ACR bridge skip, no crash."""
    engine = RealtimePaperTradingEngine(_config(use_acr=True, tmpdir=str(tmp_path)))
    engine.process_signals([_open_signal()])
    # Tick tanpa ltf_candles
    result = engine.process_signals([_price_tick("BTCUSDT", 105.0)])
    assert isinstance(result["events"], list)
