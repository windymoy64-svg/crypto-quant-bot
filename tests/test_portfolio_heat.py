"""Tests for PortfolioHeatGuard."""

from __future__ import annotations

from app.risk.portfolio_heat import OpenPositionRisk, PortfolioHeatGuard, base_cluster


def _pos(symbol: str, side: str, risk: float) -> OpenPositionRisk:
    return OpenPositionRisk(symbol=symbol, side=side, risk_amount=risk)


def test_heat_guard_passes_under_threshold() -> None:
    guard = PortfolioHeatGuard(max_portfolio_heat_percent=2.0)
    result = guard.validate(
        equity=10_000.0,
        open_positions=[_pos("BTC/USDT", "BUY", 100.0)],
        candidate=_pos("ETH/USDT", "BUY", 50.0),
    )
    assert result.valid is True
    assert result.reason == "ok"


def test_heat_guard_blocks_when_heat_exceeded() -> None:
    guard = PortfolioHeatGuard(max_portfolio_heat_percent=2.0)
    # 100 + 110 = 210 / 10_000 = 2.1% > 2%
    result = guard.validate(
        equity=10_000.0,
        open_positions=[_pos("BTC/USDT", "BUY", 100.0)],
        candidate=_pos("ETH/USDT", "BUY", 110.0),
    )
    assert result.valid is False
    assert result.reason == "portfolio_heat_exceeded"


def test_heat_guard_blocks_same_direction_cap() -> None:
    guard = PortfolioHeatGuard(max_portfolio_heat_percent=10.0, max_same_direction=2)
    existing = [
        _pos("BTC/USDT", "BUY", 10.0),
        _pos("ETH/USDT", "BUY", 10.0),
    ]
    result = guard.validate(
        equity=10_000.0,
        open_positions=existing,
        candidate=_pos("SOL/USDT", "BUY", 10.0),
    )
    assert result.valid is False
    assert "long_direction_cap" in result.reason


def test_heat_guard_blocks_correlation_cap() -> None:
    guard = PortfolioHeatGuard(max_portfolio_heat_percent=10.0, max_per_cluster=1)
    # Both BTC → same cluster
    result = guard.validate(
        equity=10_000.0,
        open_positions=[_pos("BTC/USDT", "BUY", 10.0)],
        candidate=_pos("WBTC/USDT", "BUY", 10.0),
    )
    assert result.valid is False
    assert result.reason == "correlation_cap_exceeded"


def test_heat_guard_short_direction_counted_separately() -> None:
    guard = PortfolioHeatGuard(max_portfolio_heat_percent=10.0, max_same_direction=1)
    existing = [_pos("BTC/USDT", "BUY", 10.0)]
    # SELL is a different direction → should pass
    result = guard.validate(
        equity=10_000.0,
        open_positions=existing,
        candidate=_pos("ETH/USDT", "SELL", 10.0),
    )
    assert result.valid is True


def test_base_cluster_groups_stables() -> None:
    assert base_cluster("USDC/USDT") == "STABLE"
    assert base_cluster("FDUSD/USDT") == "STABLE"


def test_base_cluster_groups_btc() -> None:
    assert base_cluster("BTC/USDT") == "BTC"
    assert base_cluster("WBTC/USDT") == "BTC"


def test_base_cluster_returns_base_for_others() -> None:
    assert base_cluster("SOL/USDT") == "SOL"
