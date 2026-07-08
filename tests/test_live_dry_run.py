from __future__ import annotations

from app.core.models import TradingSignal
from app.live import BinancePayloadBuilder, LiveConfig, LiveExecutor, LiveOrder, LiveOrderValidator, LiveTradingManager
from app.risk.manager import RiskDecision


def _signal(action: str = "BUY") -> TradingSignal:
    return TradingSignal(
        symbol="BTC/USDT",
        action=action,
        score=95.0,
        confidence=95.0,
        entry=100000.0,
        stop_loss=99000.0,
        take_profit=[101500.0, 102500.0, 103500.0],
        risk_reward=2.5,
        risk="LOW",
        strategy="test",
        meta={},
    )


def _risk(approved: bool = True, quantity: float = 0.001) -> RiskDecision:
    return RiskDecision(
        approved=approved,
        reason="approved" if approved else "test_rejected",
        symbol="BTC/USDT",
        timestamp="2026-07-07T00:00:00+00:00",
        requested_entry=100000.0,
        stop_loss=99000.0,
        take_profit=101500.0,
        quantity=quantity,
        notional=100.0,
    )


def _order(quantity: float = 0.001, quote_amount: float = 100.0) -> LiveOrder:
    return LiveOrder(
        symbol="BTC/USDT",
        side="BUY",
        order_type="MARKET",
        quantity=quantity,
        quote_amount=quote_amount,
        price=100000.0,
        stop_loss=99000.0,
        take_profit=101500.0,
        timestamp="2026-07-07T00:00:00+00:00",
    )


def test_binance_market_buy_payload_is_valid() -> None:
    payload = BinancePayloadBuilder().build_market_buy(_order())

    assert payload == {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": 100.0,
    }


def test_live_order_validator_accepts_only_valid_buy_with_approved_risk() -> None:
    validator = LiveOrderValidator()

    assert validator.validate(signal=_signal(), risk_decision=_risk(), order=_order()).valid is True
    assert validator.validate(signal=_signal("WATCH"), risk_decision=_risk(), order=_order()).reason == "only_buy_action_supported"
    assert validator.validate(signal=_signal(), risk_decision=_risk(False), order=_order()).reason == "risk_not_approved:test_rejected"
    assert validator.validate(signal=_signal(), risk_decision=_risk(), order=_order(quantity=0)).reason == "quantity_must_be_positive"
    assert validator.validate(signal=_signal(), risk_decision=_risk(), order=_order(quote_amount=0)).reason == "quote_amount_must_be_positive"


def test_live_executor_dry_run_does_not_call_network(monkeypatch) -> None:
    called = False
    executor = LiveExecutor(LiveConfig(dry_run=True))

    def fail_if_called(payload):
        nonlocal called
        called = True
        raise AssertionError("network call must not happen in dry run")

    monkeypatch.setattr(executor, "_send_live_order", fail_if_called)
    result = executor.execute(payload={"symbol": "BTCUSDT"}, order=_order())

    assert called is False
    assert result.mode == "DRY_RUN"
    assert result.payload == {"symbol": "BTCUSDT"}


def test_live_manager_returns_dry_run_result_and_logs_json(tmp_path) -> None:
    result = LiveTradingManager(
        LiveConfig(enabled=False, dry_run=True, default_quote_amount=100.0),
        log_path=tmp_path / "live_dry_run.jsonl",
    ).execute(_signal(), _risk())

    assert result.mode == "DRY_RUN"
    assert result.status == "prepared"
    assert result.payload["symbol"] == "BTCUSDT"
    assert result.payload["quoteOrderQty"] == 100.0
    assert (tmp_path / "live_dry_run.jsonl").read_text(encoding="utf-8").strip()
