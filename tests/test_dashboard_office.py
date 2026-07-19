"""Tests for the animated agents office snapshot and HTTP routes."""

from __future__ import annotations

import json
from datetime import UTC, datetime
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
        "staff": 7,
        "working": 0,
        "in_progress": 0,
        "done": 0,
    }
    assert [agent["id"] for agent in snapshot["agents"]] == [
        "rian",
        "haru",
        "yuna",
        "miro",
        "quinn",
        "raven",
        "dami",
    ]
    assert snapshot["agents"][0]["status"] == "offline"
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

    assert payload["kpi"]["staff"] == 7
    assert payload["kpi"]["working"] == 6
    assert payload["kpi"]["in_progress"] == 1
    assert agents["rian"]["task"] == "Scan BTC/USDT"
    assert agents["haru"]["task"] == "Bangun signal BTC/USDT"
    assert agents["yuna"]["detail"] == "bias=BULLISH"
    assert agents["miro"]["task"] == "Decide ENTRY"
    assert agents["miro"]["has_alert"] is True
    assert agents["quinn"]["detail"] == "risk=LOW"
    assert agents["raven"]["task"] == "Kelola BTC/USDT"
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
    assert payload["kpi"]["staff"] == 7

    static_dir = Path(__file__).parents[1] / "app" / "dashboard" / "static"
    assert "requestAnimationFrame(loop)" in (
        static_dir / "office.js"
    ).read_text(encoding="utf-8")


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