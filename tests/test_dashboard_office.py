"""Tests for the animated agents office snapshot and HTTP routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.routing import APIRoute

from app.dashboard.app import create_app
from app.dashboard.office.state import build_office_snapshot
from app.dashboard.routes.office import router


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _route_endpoint(path: str):
    application = create_app()
    return next(
        route.endpoint
        for route in application.routes
        if isinstance(route, APIRoute) and route.path == path
    )


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


def test_office_router_exposes_state_endpoint() -> None:
    assert [route.path for route in router.routes] == ["/api/office/state"]


def test_snapshot_gracefully_handles_missing_runtime_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LIVE_TRADING_ENABLED", raising=False)

    snapshot = build_office_snapshot(base_dir=tmp_path).to_dict()

    assert snapshot["kpi"] == {
        "staff": 4,
        "working": 0,
        "in_progress": 0,
        "done": 0,
    }
    assert [agent["id"] for agent in snapshot["agents"]] == [
        "yuna",
        "nara",
        "miro",
        "dami",
    ]
    assert snapshot["agents"][0]["status"] == "offline"
    assert snapshot["agents"][1]["task"] == "Journal kosong"
    assert snapshot["agents"][-1]["task"] == "Live trading terkunci"


def test_snapshot_maps_fresh_runtime_work_to_agent_jobs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC).isoformat()
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    _write_json(
        tmp_path / "logs" / "latest_signals.json",
        {
            "timestamp": now,
            "signals": [
                {
                    "symbol": "BTC/USDT",
                    "action": "BUY",
                    "confidence": 96,
                    "entry": 100,
                    "stop_loss": 95,
                    "risk": "LOW",
                    "failed_gates": [],
                }
            ],
        },
    )
    _write_json(
        tmp_path / "logs" / "agent_pipeline.json",
        {
            "enabled": True,
            "generated_at": now,
            "execute_decisions": False,
            "entries": [
                {
                    "symbol": "BTC/USDT",
                    "result": {
                        "eligible": True,
                        "chart_reading": {"bias": "BULLISH"},
                        "decision": {"action": "ENTRY", "confidence": 91},
                    },
                }
            ],
        },
    )
    _write_json(
        tmp_path / "logs" / "paper_state.json",
        {
            "updated_at": now,
            "balance": 1000,
            "open_positions": {
                "BTC/USDT": {
                    "side": "LONG",
                    "entry": 100,
                }
            },
        },
    )

    payload = build_office_snapshot(base_dir=tmp_path).to_dict()
    agents = {agent["id"]: agent for agent in payload["agents"]}

    assert payload["kpi"]["staff"] == 4
    assert payload["kpi"]["working"] == 2
    assert payload["kpi"]["in_progress"] == 1
    assert agents["nara"]["status"] == "offline"
    assert agents["yuna"]["detail"] == "bias=BULLISH | sinyal scanner"
    assert agents["miro"]["task"] == "Decide ENTRY"
    assert agents["miro"]["has_alert"] is True
    assert agents["dami"]["status"] == "offline"


def test_office_page_and_api_are_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BOT_API_KEY", raising=False)
    office_page = _route_endpoint("/office")
    state_api = _route_endpoint("/api/office/state")

    page = office_page(_request("/office"))
    payload = state_api()

    assert page.status_code == 200
    assert '<canvas id="office-canvas"' in page.body.decode()
    assert payload["kpi"]["staff"] == 4

    static_dir = Path(__file__).parents[1] / "app" / "dashboard" / "static"
    assert "requestAnimationFrame(loop)" in (
        static_dir / "office.js"
    ).read_text(encoding="utf-8")


def test_office_frontend_keeps_four_agents_visible_and_names_report_targets() -> None:
    """Guard against desks hiding agents and ambiguous handoff bubbles."""

    static_dir = Path(__file__).parents[1] / "app" / "dashboard" / "static"
    script = (static_dir / "office.js").read_text(encoding="utf-8")

    assert 'scene.push({ kind: "agent", value: agent, zY: agent.y + s * 3 })' in script
    assert "Yuna → Nara:" in script
    assert "Yuna → Miro:" in script
    assert "Nara → Miro:" in script
    assert "Miro → Dami:" in script
    assert "Dami → Nara:" in script
    assert "laporan ke" in script


def test_agents_squad_embeds_animated_office_below_existing_characters() -> None:
    """The office belongs inside Agents > Agent Squad, with fullscreen optional."""

    dashboard_dir = Path(__file__).parents[1] / "app" / "dashboard"
    template = (dashboard_dir / "templates" / "index.html").read_text(encoding="utf-8")
    office_template = (dashboard_dir / "templates" / "office.html").read_text(encoding="utf-8")

    squad_end = template.index('</div>\n            </div>\n            <section class="agent-office"')
    office_start = template.index('<section class="agent-office"')
    caption_start = template.index('<p id="agent-squad-caption"')
    assert squad_end < office_start < caption_start
    assert '<canvas id="office-canvas" width="1280" height="720"' in template
    assert 'style="position:relative;z-index:2;margin:4px auto 0;overflow:hidden;width:min(100%,640px);aspect-ratio:640 / 384;background:#0d0e15;"' in template
    assert 'style="position:absolute;top:calc(-100% * 296 / 384);left:calc(-100% * 304 / 640);width:calc(100% * 1280 / 640);height:calc(100% * 720 / 384);max-width:none;display:block;background:#0d0e15;image-rendering:pixelated;"' in template
    assert 'src="/office?embed=1&amp;v={{ asset_version }}"' not in template
    assert 'type="module" src="/static/office.js?v={{ asset_version }}"' in template
    assert "agent-office-head" not in template
    assert "agent-office-frame-wrap" not in template
    assert "Alur laporan:" not in template
    assert 'class="agent-squad-caption" hidden' in template
    assert 'class="office-embedded"' in office_template

    dashboard_css = (dashboard_dir / "static" / "dashboard.css").read_text(encoding="utf-8")
    office_css = (dashboard_dir / "static" / "office.css").read_text(encoding="utf-8")
    assert '.agent-squad-panel > .agent-squad-stage' not in dashboard_css
    assert "body.office-embedded #office-header" in office_css
    assert "body.office-embedded #office-footer" in office_css
    assert "display: none !important" in office_css
    assert ".agent-office #office-canvas" in dashboard_css
    assert "margin:4px auto 0" in dashboard_css
    assert "width:min(100%,640px)" in dashboard_css
    assert "aspect-ratio:640 / 384" in dashboard_css
    assert "top:calc(-100% * 296 / 384)" in dashboard_css
    assert "left:calc(-100% * 304 / 640)" in dashboard_css
    assert "width:calc(100% * 1280 / 640)" in dashboard_css
    assert "height:calc(100% * 720 / 384)" in dashboard_css
    assert "top:calc(-100% * 152 / 416)" not in dashboard_css
    assert "height:calc(100% * 720 / 416)" not in dashboard_css
    assert "top:calc(-100% * 152 / 568)" not in dashboard_css
    assert "height:calc(100% * 720 / 568)" not in dashboard_css
    assert "top:calc(-100% * 8 / 704)" not in dashboard_css
    assert "height:calc(100% * 720 / 704)" not in dashboard_css


def test_office_page_sets_cookie_for_protected_state_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_API_KEY", "office-secret")
    office_page = _route_endpoint("/office")

    page = office_page(_request("/office"))
    cookie_headers = [
        value.decode()
        for name, value in page.raw_headers
        if name.lower() == b"set-cookie"
    ]

    assert page.status_code == 200
    assert any(
        "dashboard_token=office-secret" in header and "HttpOnly" in header
        for header in cookie_headers
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_learning_agent_office_tracks_journal_activity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")

    # Journal lama (di luar window 30m) -> idle, bukan working
    old_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _write_jsonl(
        tmp_path / "data" / "learning_journal.jsonl",
        [{"timestamp": old_ts, "symbol": "BTC/USDT", "pnl_percent": 1.2}],
    )
    payload = build_office_snapshot(base_dir=tmp_path).to_dict()
    nara = next(a for a in payload["agents"] if a["id"] == "nara")
    assert nara["status"] == "idle"
    assert "1 journal" in nara["detail"]

    # Observasi baru (fresh) -> working
    fresh_ts = datetime.now(UTC).isoformat()
    _write_jsonl(
        tmp_path / "data" / "chart_observations.jsonl",
        [{"timestamp": fresh_ts, "symbol": "ETH/USDT", "stage": "ENTRY"}],
    )
    payload = build_office_snapshot(base_dir=tmp_path).to_dict()
    nara = next(a for a in payload["agents"] if a["id"] == "nara")
    assert nara["status"] == "working"
    assert nara["task"] == "Olah insight baru"


def test_yuna_detail_marks_position_monitor_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    now = datetime.now(UTC).isoformat()
    _write_json(
        tmp_path / "logs" / "agent_pipeline.json",
        {
            "enabled": True,
            "generated_at": now,
            "entries": [
                {
                    "symbol": "BTC/USDT",
                    "result": {
                        "stage": "POSITION_MONITOR",
                        "eligible": True,
                        "chart_reading": {"bias": "BEARISH"},
                        "decision": None,
                    },
                }
            ],
        },
    )
    payload = build_office_snapshot(base_dir=tmp_path).to_dict()
    yuna = next(a for a in payload["agents"] if a["id"] == "yuna")
    assert yuna["status"] == "working"
    assert yuna["detail"] == "bias=BEARISH | posisi open"


def test_office_shows_multi_candidate_count(tmp_path: Path) -> None:
    """Office harus tampilkan jumlah + daftar simbol bila ada >1 kandidat/posisi."""
    now = datetime.now(UTC).isoformat()
    _write_json(
        tmp_path / "logs" / "agent_pipeline.json",
        {
            "enabled": True,
            "generated_at": now,
            "execute_decisions": False,
            "entries": [
                {
                    "symbol": "BTC/USDT",
                    "result": {
                        "eligible": True,
                        "chart_reading": {"bias": "BULLISH"},
                        "decision": {"action": "ENTRY", "confidence": 92},
                    },
                },
                {
                    "symbol": "ETH/USDT",
                    "result": {
                        "eligible": True,
                        "chart_reading": {"bias": "BULLISH"},
                        "decision": {"action": "HOLD", "confidence": 70},
                    },
                },
            ],
            "monitor": [
                {
                    "symbol": "SOL/USDT",
                    "result": {
                        "stage": "POSITION_MONITOR",
                        "eligible": True,
                        "chart_reading": {"bias": "BEARISH"},
                    },
                }
            ],
        },
    )
    payload = build_office_snapshot(base_dir=tmp_path).to_dict()
    yuna = next(a for a in payload["agents"] if a["id"] == "yuna")
    assert yuna["status"] == "working"
    # 2 entries + 1 monitor = 3 chart dipantau
    assert "3 chart" in yuna["task"]
    assert "BTC" in yuna["task"]
    assert "ETH" in yuna["task"]
    assert "SOL" in yuna["task"]

    miro = next(a for a in payload["agents"] if a["id"] == "miro")
    assert miro["status"] == "working"
    assert "3 simbol" in miro["task"]