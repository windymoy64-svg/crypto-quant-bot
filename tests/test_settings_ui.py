from __future__ import annotations

from collections import Counter
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app/dashboard/templates/index.html"
SCRIPT = ROOT / "app/dashboard/static/dashboard.js"


def test_dashboard_template_has_no_duplicate_ids() -> None:
    ids = re.findall(r'\bid="([^"]+)"', TEMPLATE.read_text(encoding="utf-8"))
    duplicates = [name for name, count in Counter(ids).items() if count > 1]

    assert duplicates == []


def test_exchange_selector_uses_dedicated_unique_id() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'id="settings-exchange-panel"' in html
    assert 'id="settings-exchange-select"' in html
    assert 'byId("settings-exchange-select")' in javascript
    assert 'byId("settings-exchange")' not in javascript


def test_trading_default_controls_are_present() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    for control_id in (
        "settings-tp-percent",
        "settings-sl-percent",
        "settings-trailing-percent",
        "settings-leverage",
    ):
        assert f'id="{control_id}"' in html


def test_multi_exchange_controls_and_dynamic_overview_are_present() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    javascript = SCRIPT.read_text(encoding="utf-8")

    for control_id in (
        "portfolio-view-mode",
        "portfolio-active-exchange",
        "exchange-badge",
        "mode-badge",
        "portfolio-view-badge",
    ):
        assert f'id="{control_id}"' in html

    assert '"/api/portfolio/multi"' in javascript
    assert '"/api/settings/portfolio"' in javascript
    assert "function savePortfolioSettings" in javascript
    assert 'id="multi-portfolio-card"' not in html
    assert "function renderMultiPortfolio" not in javascript


def test_static_all_mode_badges_were_replaced_by_dynamic_badges() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert '<span class="market-badge paper">Paper</span>' not in html
    assert '<span class="market-badge dry">Dry Run</span>' not in html
    assert '<span class="market-badge live">Live</span>' not in html


def test_agent_metrics_use_clean_overview_style_cards() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")
    css = (ROOT / "app/dashboard/static/dashboard.css").read_text(encoding="utf-8")

    assert "function agentMetricCard" in javascript
    assert 'class="agent-metric-icon"' in javascript
    assert javascript.count("agentMetricCard(") >= 9
    assert ".agent-metric-card" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in css
    assert ".tone-blue .agent-metric-icon" in css
    assert ".tone-amber .agent-metric-icon" in css


def test_primary_exchange_controls_exchange_specific_settings() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'data-exchange-only="binance"' in html
    assert 'id="execution-account-source"' in html
    assert 'id="execution-bot-mode"' in html
    assert 'id="execution-live-readiness"' in html
    assert "function applyPrimaryExchangeUi" in javascript
    assert "function renderExecutionModeSummary" in javascript


def test_execution_mode_and_kill_switch_controls_are_present() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'id="execution-mode-select"' in html
    assert 'id="execution-live-confirmation"' in html
    assert "ENABLE LIVE TRADING" in html
    assert "Kill Switch — Return to Paper" in html
    assert '"/api/settings/execution"' in javascript
    assert '"/api/settings/execution/kill"' in javascript