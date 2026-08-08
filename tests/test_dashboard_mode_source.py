from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "app/dashboard/static/dashboard.js"
TEMPLATE = ROOT / "app/dashboard/templates/index.html"


def test_execution_mode_is_loaded_before_dashboard_data() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'const execution=await getJson("/api/settings/execution")' in javascript
    assert 'if(state.executionMode==="paper") endpoints.push(["paper","/api/paper"])' in javascript
    assert 'if(state.executionMode!=="paper") payload.paper=clone(DEFAULT_PAYLOAD.paper)' in javascript
    assert 'multi_portfolio' in javascript


def test_live_mode_never_selects_paper_fallback() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'const paperMode=mode==="paper"' in javascript
    assert 'const realSourceSelected=!paperMode' in javascript
    assert 'const realSourceSelected=realConnected||' not in javascript
    assert 'render(clone(DEFAULT_PAYLOAD))' not in javascript
    assert 'const real=realSourceSelected&&Number(multi.accounts_connected??0)>0' not in javascript
    assert 'return String(state.executionMode||"paper").toLowerCase() !== "paper" ? list(multi?.positions)' in javascript


def test_websocket_waits_for_authoritative_execution_mode() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'if(state.executionMode) state.wsSnapshotTimer=setTimeout' in javascript
    assert 'mode:state.executionMode' in javascript


def test_overview_panels_follow_execution_mode_not_connection_race() -> None:
    html = TEMPLATE.read_text(encoding="utf-8")

    assert 'mode && mode !== "paper"' in html
    assert 'mode === "paper" ? (paper || {})' in html
    assert 'realConnected(multi)\n                ? realSourceFromMulti(multi)' not in html
    assert 'const mode = String(window.__executionMode || "paper").toLowerCase();' in html
    assert 'return mode !== "paper" ? realSourceFromMulti(multi)' in html


def test_analytics_chart_has_execution_mode_source_selector() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'const real=String(state.executionMode||payload?.execution_mode||"paper").toLowerCase()!=="paper"' in javascript
    assert 'payload?.multiPortfolio??payload?.multi_portfolio??{}' in javascript
    services = (ROOT / "app/dashboard/services.py").read_text(encoding="utf-8")
    assert '"execution_mode": execution.mode' in services


def test_legacy_health_route_is_protected() -> None:
    app = (ROOT / "app/dashboard/app.py").read_text(encoding="utf-8")

    assert '@dashboard.get("/health", dependencies=[Depends(require_api_key)])' in app
