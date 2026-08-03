from __future__ import annotations

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "app/dashboard/static/dashboard.js"


def test_http_requests_use_same_meta_token_as_websocket() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert "function dashboardAuthHeaders()" in javascript
    assert "Authorization:`Bearer ${token}`" in javascript
    assert 'headers:dashboardAuthHeaders()' in javascript
    assert '...dashboardAuthHeaders()' in javascript


def test_llm_errors_distinguish_dashboard_and_provider_auth() -> None:
    javascript = SCRIPT.read_text(encoding="utf-8")

    assert 'raw==="invalid api key"' in javascript
    assert "Sesi dashboard tidak valid" in javascript
    assert "API key ditolak oleh provider LLM" in javascript
    assert "new_api_key_required_when_provider_changes" in javascript