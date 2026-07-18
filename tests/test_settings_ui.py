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