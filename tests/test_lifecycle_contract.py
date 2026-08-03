from __future__ import annotations

from app.execution.lifecycle_contract import (
    LIFECYCLE_VERSION,
    take_profit_levels,
    take_profit_quantities,
    validate_entry_order_parity,
    validate_live_capabilities,
)
from app.executor_agent.models import OrderRequest


def test_configured_rr_builds_same_three_level_geometry_for_long_and_short() -> None:
    assert take_profit_levels(
        entry=100, stop_loss=97, side="BUY", planned_levels=(),
        target_risk_reward=2,
    ) == (106.0, 109.0, 112.0)
    assert take_profit_levels(
        entry=100, stop_loss=103, side="SELL", planned_levels=(),
        target_risk_reward=2,
    ) == (94.0, 91.0, 88.0)


def test_tp_quantities_are_exact_initial_size_30_30_40() -> None:
    quantities = take_profit_quantities(7.0, 3)
    assert quantities == (2.1, 2.1, 2.8)
    assert sum(quantities) == 7.0


def test_shadow_parity_accepts_complete_reduce_only_ladder() -> None:
    orders = [
        OrderRequest("BTC/USDT", "BUY", "MARKET", 1, meta={"role": "entry"}),
        OrderRequest("BTC/USDT", "SELL", "STOP_MARKET", 1, stop_price=97,
                     reduce_only=True, meta={"role": "stop_loss"}),
        *[
            OrderRequest("BTC/USDT", "SELL", "LIMIT", qty, price=price,
                         reduce_only=True, meta={"role": f"take_profit_{index}"})
            for index, (qty, price) in enumerate(((0.3, 106), (0.3, 109), (0.4, 112)), 1)
        ],
    ]
    report = validate_entry_order_parity(orders)
    assert report.compatible is True
    assert report.lifecycle_version == LIFECYCLE_VERSION


def test_shadow_parity_rejects_tp1_only_plan() -> None:
    orders = [
        OrderRequest("BTC/USDT", "BUY", "MARKET", 1, meta={"role": "entry"}),
        OrderRequest("BTC/USDT", "SELL", "STOP_MARKET", 1, stop_price=97,
                     reduce_only=True, meta={"role": "stop_loss"}),
        OrderRequest("BTC/USDT", "SELL", "LIMIT", 0.4, price=106,
                     reduce_only=True, meta={"role": "take_profit_1"}),
    ]
    assert validate_entry_order_parity(orders).compatible is False


def test_live_capabilities_report_exact_missing_lifecycle_feature() -> None:
    report = validate_live_capabilities({"three_stage_tp": True})
    assert report.compatible is False
    assert "missing_live_capability:mandatory_stop" in report.reasons