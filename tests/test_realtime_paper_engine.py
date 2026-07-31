import json
from pathlib import Path

from app.paper.realtime_engine import PaperTradingConfig, RealtimePaperTradingEngine


def test_paper_engine_opens_virtual_position(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    signal = {
        "symbol": "BTC/USDT",
        "action": "BUY",
        "entry": 100.0,
        "stop_loss": 95.0,
        "take_profit": [110.0],
        "confidence": 95.0,
    }

    result = engine.process_signals([signal])

    assert result["open_positions"]
    assert result["events"][0]["type"] == "opened"


def test_paper_engine_closes_position_on_take_profit(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "BUY",
                "entry": 100.0,
                "stop_loss": 95.0,
                "take_profit": [110.0],
                "confidence": 95.0,
            }
        ]
    )

    result = engine.process_signals(
        [
            {
                "symbol": "BTC/USDT",
                "action": "SKIP",
                "entry": 111.0,
                "stop_loss": 95.0,
                "take_profit": [120.0],
                "confidence": 70.0,
            }
        ]
    )

    assert not result["open_positions"]
    assert result["events"][0]["type"] == "closed"
    assert result["events"][0]["close_scope"] == "full"
    assert result["events"][0]["close_label"] == "Full close — take profit 1"


def test_paper_engine_updates_unranked_position_with_tracking_tick(
    tmp_path: Path,
) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [
            {
                "symbol": "ALLO/USDT",
                "action": "BUY",
                "entry": 0.37,
                "stop_loss": 0.36,
                "take_profit": [0.40, 0.42, 0.44],
                "confidence": 95.0,
            }
        ]
    )

    result = engine.process_signals(
        [
            {
                "symbol": "ALLO/USDT",
                "action": "SKIP",
                "entry": 0.375,
                "stop_loss": 0.36,
                "take_profit": [0.40, 0.42, 0.44],
                "confidence": 0.0,
            }
        ]
    )

    position = result["open_positions"][0]
    assert position["last_price"] == 0.375
    assert position["unrealized_pnl"] > 0


def test_percent_overrides_apply_to_new_long_position(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        take_profit_percent=5,
        stop_loss_percent=2,
        trailing_stop_percent=1,
        leverage=25,
    )
    engine = RealtimePaperTradingEngine(config)

    result = engine.process_signals(
        [{
            "symbol": "BTC/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 90.0,
            "take_profit": [120.0],
            "confidence": 95.0,
        }]
    )

    position = result["open_positions"][0]
    assert position["stop_loss"] == 98.0
    assert position["take_profit"] == [105.0]
    assert position["configured_leverage"] == 25
    assert position["leverage"] == 25
    assert position["used_capital"] == 200.0

    tracked = engine.process_signals(
        [{
            "symbol": "BTC/USDT",
            "action": "SKIP",
            "entry": 102.0,
            "stop_loss": 90.0,
            "take_profit": [120.0],
            "confidence": 0.0,
        }]
    )
    position = tracked["open_positions"][0]
    assert position["trailing_active"] is True
    assert position["trailing_stop_loss"] == 100.98


def test_configured_margin_and_rr_override_default_sizing(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=100,
        risk_percent=0.5,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        leverage=25,
        target_margin_percent=5,
        target_risk_reward=2,
    )
    engine = RealtimePaperTradingEngine(config)

    result = engine.process_signals(
        [{
            "symbol": "TEST/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 98.0,
            "take_profit": [101.0],
            "confidence": 95.0,
        }]
    )

    position = result["open_positions"][0]
    assert position["size"] == 1.25
    assert position["used_capital"] == 5.0
    assert position["take_profit"] == [104.0, 106.0, 108.0]
    assert position["rr_tp1"] == 2.0
    assert position["tp_level_source"] == "configured_rr"
    assert position["configured_margin_percent"] == 5
    assert position["configured_risk_reward"] == 2
    assert position["sizing_source"] == "configured_margin"
    assert abs((position["entry"] - position["stop_loss"]) * position["size"]) == 2.5
    assert abs((position["take_profit"][0] - position["entry"]) * position["size"]) == 5.0


def test_percent_overrides_apply_to_new_short_position(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
        take_profit_percent=5,
        stop_loss_percent=2,
    )
    engine = RealtimePaperTradingEngine(config)

    result = engine.process_signals(
        [{
            "symbol": "BTC/USDT",
            "action": "SELL",
            "entry": 100.0,
            "stop_loss": 110.0,
            "take_profit": [80.0],
            "confidence": 95.0,
        }]
    )

    position = result["open_positions"][0]
    assert position["stop_loss"] == 102.0
    assert position["take_profit"] == [95.0]


def test_close_from_decision_immediate_always_closes(tmp_path: Path) -> None:
    """IMMEDIATE closes when pnl_ratio is past micro-BE band (e.g. 0.5R)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    # Tick to a small profit (0.5R) then force-close via IMMEDIATE.
    engine.process_signals(
        [{"symbol": "BTC/USDT", "action": "SKIP", "entry": 102.5,
          "stop_loss": 95.0, "take_profit": [110.0], "confidence": 0.0}]
    )
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=102.5,
        reason="choch_bearish_against_long", urgency="IMMEDIATE",
        pnl_ratio=0.5,
    )
    assert closed is not None
    assert closed["type"] == "closed"
    state = config.state_path
    import json
    with open(state) as f:
        data = json.load(f)
    assert "BTC/USDT" not in data["open_positions"]


def test_close_from_decision_next_candle_skips_small_profit(tmp_path: Path) -> None:
    """NEXT_CANDLE urgency is suppressed when 0 < PnL <= 1R (let winners run)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    # 0.5R profit → NEXT_CANDLE should be suppressed.
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=102.5,
        reason="bias_reversal", urgency="NEXT_CANDLE",
        pnl_ratio=0.5,
        min_hold_seconds=0,
    )
    assert closed is None
    import json
    with open(config.state_path) as f:
        data = json.load(f)
    assert "BTC/USDT" in data["open_positions"]


def test_close_from_decision_next_candle_closes_loser(tmp_path: Path) -> None:
    """NEXT_CANDLE urgency closes the position when PnL < -0.3R (cut loss)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=97.0,
        reason="bias_reversal", urgency="NEXT_CANDLE",
        pnl_ratio=-0.6,
        min_hold_seconds=0,
    )
    assert closed is not None
    assert closed["type"] == "closed"


def test_close_from_decision_next_candle_closes_big_winner(tmp_path: Path) -> None:
    """NEXT_CANDLE urgency closes the position when PnL > 1R (lock big profit)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=108.0,
        reason="bias_reversal", urgency="NEXT_CANDLE",
        pnl_ratio=1.6,
        min_hold_seconds=0,
    )
    assert closed is not None
    assert closed["type"] == "closed"


def test_close_from_decision_next_candle_skips_fresh_position(tmp_path: Path) -> None:
    """NEXT_CANDLE is suppressed when position age < min_hold_seconds."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    # Fresh position (just opened), even with -0.6R loss → skip.
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=97.0,
        reason="bias_reversal", urgency="NEXT_CANDLE",
        pnl_ratio=-0.6,
        min_hold_seconds=300.0,
    )
    assert closed is None
    import json
    with open(config.state_path) as f:
        data = json.load(f)
    assert "BTC/USDT" in data["open_positions"]


def test_close_from_decision_next_candle_skips_flat_pnl(tmp_path: Path) -> None:
    """NEXT_CANDLE is suppressed when PnL is flat/tiny drawdown (not meaningful loss)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    # Flat PnL (0.0) with min_hold=0 → still skip (not meaningful loss).
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=100.0,
        reason="bias_reversal", urgency="NEXT_CANDLE",
        pnl_ratio=0.0,
        min_hold_seconds=0,
    )
    assert closed is None


def test_chart_agent_legacy_limit_signal_enters_market_immediately(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True, starting_balance=10_000, risk_percent=1,
        max_open_positions=3, state_path=str(tmp_path / "state.json"),
        trades_path=str(tmp_path / "trades.jsonl"), pending_order_ttl_seconds=900,
    )
    engine = RealtimePaperTradingEngine(config)
    result = engine.process_signals([{
        "symbol": "BTC/USDT", "action": "BUY", "entry": 95.0,
        "current_price": 100.0, "entry_zone": [94.0, 96.0],
        "entry_mode": "LIMIT", "stop_loss": 92.0,
        "take_profit": [101.0, 104.0, 107.0], "confidence": 90.0,
    }])
    assert result["open_positions"][0]["entry"] == 100.0
    assert result["pending_orders"] == []


def test_chart_agent_market_entry_when_price_inside_zone(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True, starting_balance=10_000, risk_percent=1,
        max_open_positions=3, state_path=str(tmp_path / "state.json"),
        trades_path=str(tmp_path / "trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    result = engine.process_signals([{
        "symbol": "BTC/USDT", "action": "BUY", "entry": 95.0,
        "current_price": 95.5, "entry_zone": [94.0, 96.0],
        "entry_mode": "LIMIT", "stop_loss": 92.0,
        "take_profit": [102.5], "confidence": 90.0,
    }])
    assert result["open_positions"][0]["entry"] == 95.5
    assert result["pending_orders"] == []


def test_legacy_pending_limit_order_is_cancelled(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "balance": 10_000.0,
        "open_positions": {},
        "pending_orders": {
            "ETH/USDT": {
                "symbol": "ETH/USDT", "status": "PENDING",
                "entry_zone": [3000.0, 3100.0],
            },
        },
        "closed_trades": [],
    }))
    engine = RealtimePaperTradingEngine(PaperTradingConfig(
        enabled=True, starting_balance=10_000, risk_percent=1,
        max_open_positions=3, state_path=str(state_path),
        trades_path=str(tmp_path / "trades.jsonl"),
    ))

    result = engine.process_signals([])

    assert result["pending_orders"] == []
    assert result["events"][0]["type"] == "order_cancelled"
    assert result["events"][0]["reason"] == "market_entry_only"


def test_update_tp1_flag_sets_position_field(tmp_path: Path) -> None:
    """update_tp1_flag persists the tp1_enabled flag on an open position."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0, 120.0, 130.0],
            "confidence": 95.0,
        }]
    )
    updated = engine.update_tp1_flag("BTC/USDT", enabled=False)
    assert updated is True

    import json
    with open(config.state_path) as f:
        data = json.load(f)
    assert data["open_positions"]["BTC/USDT"]["tp1_enabled"] is False

    # Idempotent: same value returns False (no redundant write).
    assert engine.update_tp1_flag("BTC/USDT", enabled=False) is False


def test_tp1_disabled_skips_partial_close(tmp_path: Path) -> None:
    """When tp1_enabled=False, price hitting TP1 does NOT partial close."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0, 120.0, 130.0],
            "confidence": 95.0,
        }]
    )
    # Disable TP1 (strong structure).
    engine.update_tp1_flag("BTC/USDT", enabled=False)

    # Price hits TP1 (110) — should NOT partial close.
    result = engine.process_signals(
        [{"symbol": "BTC/USDT", "action": "SKIP", "entry": 110.0,
          "stop_loss": 95.0, "take_profit": [110.0, 120.0, 130.0],
          "confidence": 0.0}]
    )
    # Position still open, no partial_close event, tp_hit[0] still False.
    assert result["open_positions"]
    partial_events = [e for e in result["events"] if e.get("type") == "partial_close"]
    assert partial_events == []
    position = result["open_positions"][0]
    assert position["tp_hit"][0] is False


def test_tp1_enabled_partial_closes_by_default(tmp_path: Path) -> None:
    """Default (no flag / enabled=True): price hitting TP1 partial closes."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0, 120.0, 130.0],
            "confidence": 95.0,
        }]
    )
    # No flag set → default True. Price hits TP1.
    result = engine.process_signals(
        [{"symbol": "BTC/USDT", "action": "SKIP", "entry": 110.0,
          "stop_loss": 95.0, "take_profit": [110.0, 120.0, 130.0],
          "confidence": 0.0}]
    )
    partial_events = [e for e in result["events"] if e.get("type") == "partial_close"]
    assert len(partial_events) == 1
    assert partial_events[0]["close_scope"] == "partial"
    assert partial_events[0]["close_label"] == "Partial close — take profit 1"
    position = result["open_positions"][0]
    assert position["tp_hit"][0] is True


def test_empty_overrides_preserve_signal_defaults(tmp_path: Path) -> None:
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)

    result = engine.process_signals(
        [{
            "symbol": "BTC/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 94.0,
            "take_profit": [108.0, 112.0, 116.0],
            "confidence": 95.0,
        }]
    )

    position = result["open_positions"][0]
    assert position["stop_loss"] == 94.0
    # TP1 RR = 8/6 ≈ 1.33 < 2 → Opsi C floors TP1 to 2R=112, keeps 116.
    assert position["take_profit"][0] == 112.0
    assert 116.0 in position["take_profit"]
    assert position["rr_tp1"] >= 2.0
    assert position["tp_level_source"] == "normalized_min_rr"
    assert position["configured_leverage"] is None
    assert position["leverage"] == 1


def test_close_from_decision_immediate_skips_breakeven(tmp_path: Path) -> None:
    """IMMEDIATE structure exits near break-even must not flatten the trade."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    engine.process_signals(
        [{
            "symbol": "BTC/USDT", "action": "BUY", "entry": 100.0,
            "stop_loss": 95.0, "take_profit": [110.0], "confidence": 95.0,
        }]
    )
    closed = engine.close_from_decision(
        symbol="BTC/USDT", exit_price=100.1,
        reason="structure_invalidation", urgency="IMMEDIATE",
        pnl_ratio=0.02,
        min_hold_seconds=0,
    )
    assert closed is None
    import json
    with open(config.state_path) as f:
        data = json.load(f)
    assert "BTC/USDT" in data["open_positions"]



def test_inverted_long_tp_is_sanitized_and_rebuilt(tmp_path: Path) -> None:
    """LONG take-profits below entry must never be stored or partial-closed."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)

    # UNI-style bug: signal TP ladder entirely on the wrong side of entry.
    result = engine.process_signals(
        [{
            "symbol": "UNI/USDT",
            "action": "BUY",
            "entry": 3.929,
            "stop_loss": 3.83285,
            "take_profit": [3.9143, 3.957, 3.9686],
            "confidence": 87.9,
        }]
    )

    assert result["open_positions"]
    position = result["open_positions"][0]
    assert position["entry"] == 3.929
    # Inverted 3.9143 dropped; remaining above-entry levels had RR < 2 so
    # Opsi C floors TP1 to 2R (still strictly above entry).
    assert all(tp > position["entry"] for tp in position["take_profit"])
    risk = position["entry"] - position["stop_loss"]
    assert position["take_profit"][0] >= position["entry"] + 2 * risk - 1e-9
    assert position["rr_tp1"] >= 2.0
    assert position["trailing_active"] is False

    # Price dips below entry — must NOT fire take_profit_1 or arm trailing.
    result = engine.process_signals(
        [{
            "symbol": "UNI/USDT",
            "action": "SKIP",
            "entry": 3.924,
            "stop_loss": 3.83285,
            "take_profit": [3.9143, 3.957, 3.9686],
            "confidence": 0.0,
        }]
    )
    partial = [e for e in result["events"] if e.get("type") == "partial_close"]
    assert partial == []
    position = result["open_positions"][0]
    assert position["trailing_active"] is False
    assert position.get("realized_pnl_partial", 0.0) == 0.0
    assert position["tp_hit"][0] is False


def test_all_inverted_tps_fall_back_to_risk_multiples(tmp_path: Path) -> None:
    """If every TP is wrong-side, rebuild 2R/3R/4R above entry for LONG."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    result = engine.process_signals(
        [{
            "symbol": "BTC/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": [99.0, 98.0, 90.0],
            "confidence": 95.0,
        }]
    )
    position = result["open_positions"][0]
    assert position["take_profit"] == [110.0, 115.0, 120.0]
    assert position["rr_tp1"] == 2.0
    assert position["tp_level_source"] == "normalized_min_rr"




def test_low_rr_tp_is_normalized_to_min_2r(tmp_path: Path) -> None:
    """Opsi C: structural TP with RR < 2 is floored to TP1 = 2R (not rejected)."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    # ZEC-style: risk 5, TP only +3 → RR 0.6
    result = engine.process_signals(
        [{
            "symbol": "ZEC/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": [103.0],
            "confidence": 80.0,
        }]
    )
    position = result["open_positions"][0]
    assert position["take_profit"][0] == 110.0
    assert position["rr_tp1"] >= 2.0
    assert position["tp_level_source"] == "normalized_min_rr"
    assert position["take_profit"] == [110.0, 115.0, 120.0]


def test_structural_tp_above_min_rr_is_preserved(tmp_path: Path) -> None:
    """Opsi C: structural ladder with TP1 RR >= 2 stays unchanged."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    result = engine.process_signals(
        [{
            "symbol": "U/USDT",
            "action": "SELL",
            "entry": 100.0,
            "stop_loss": 105.0,
            "take_profit": [85.0, 80.0, 70.0],  # TP1 RR = 3.0
            "confidence": 90.0,
        }]
    )
    position = result["open_positions"][0]
    assert position["take_profit"] == [85.0, 80.0, 70.0]
    assert position["rr_tp1"] == 3.0
    assert position["tp_level_source"] == "structural"


def test_low_rr_keeps_farther_structural_beyond_2r(tmp_path: Path) -> None:
    """When TP1 is lifted to 2R, structural levels beyond 2R are kept."""
    config = PaperTradingConfig(
        enabled=True,
        starting_balance=10_000,
        risk_percent=1,
        max_open_positions=3,
        state_path=str(tmp_path / "paper_state.json"),
        trades_path=str(tmp_path / "paper_trades.jsonl"),
    )
    engine = RealtimePaperTradingEngine(config)
    # risk=5; 103 is 0.6R (drop as TP1), 116 is 3.2R (keep), 125 is 5R (keep)
    result = engine.process_signals(
        [{
            "symbol": "ETH/USDT",
            "action": "BUY",
            "entry": 100.0,
            "stop_loss": 95.0,
            "take_profit": [103.0, 116.0, 125.0],
            "confidence": 88.0,
        }]
    )
    position = result["open_positions"][0]
    assert position["take_profit"][0] == 110.0  # 2R floor
    assert 116.0 in position["take_profit"]
    assert 125.0 in position["take_profit"]
    assert position["tp_level_source"] == "normalized_min_rr"
    assert position["rr_tp1"] == 2.0

