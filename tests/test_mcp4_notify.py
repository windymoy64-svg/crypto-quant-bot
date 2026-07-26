"""MCP-4 monitoring / notification tool tests."""

from __future__ import annotations

from app.mcp import tools as ops_tools


def test_system_health_and_notify_dry_run() -> None:
    health = ops_tools.get_system_health()
    assert health["ok"] is True
    assert health["read_only"] is True
    assert "system" in health
    assert "artifacts" in health

    empty = ops_tools.send_ops_notification("")
    assert empty["ok"] is False

    dry = ops_tools.send_ops_notification("mcp4 test", live=False)
    assert dry["ok"] is True
    assert dry.get("sent") is True
    assert dry.get("live") is False
    assert dry.get("note") == "dry_run_outbox_only"


def test_registry_includes_mcp4_tools() -> None:
    assert "get_system_health" in ops_tools.TOOL_FUNCS
    assert "send_ops_notification" in ops_tools.TOOL_FUNCS
