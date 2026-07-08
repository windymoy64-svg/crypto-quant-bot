from __future__ import annotations

from app.dashboard.services import dashboard_service


def test_dashboard_service_market_portfolio_analytics_health_are_valid_objects() -> None:
    market = dashboard_service.market()
    portfolio = dashboard_service.portfolio()
    analytics = dashboard_service.analytics()
    health = dashboard_service.health()

    assert isinstance(market, dict)
    assert isinstance(portfolio, dict)
    assert isinstance(analytics, dict)
    assert isinstance(health, dict)

    assert "signals" in market
    assert "open_positions" in portfolio
    assert "performance" in analytics
    assert health["status"] == "ok"
    assert market["read_only"] is True
    assert portfolio["read_only"] is True
    assert analytics["read_only"] is True
    assert health["read_only"] is True
