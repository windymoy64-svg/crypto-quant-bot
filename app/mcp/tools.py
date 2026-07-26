"""Public re-exports for Ops MCP tool functions."""

from __future__ import annotations

from typing import Any

from app.mcp.tools_backtest import list_backtest_artifacts
from app.mcp.tools_backtest_get import get_backtest_artifact
from app.mcp.tools_backtest_run import run_backtest
from app.mcp.tools_journal import (
    get_chart_observations,
    get_learning_insights,
    get_trade_journal,
)
from app.mcp.tools_market import get_candles, get_data_source, get_ticker
from app.mcp.tools_ops_notify import get_system_health, send_ops_notification
from app.mcp.tools_positions import get_open_positions, get_pnl
from app.mcp.tools_signals import get_agent_pipeline, get_latest_signals
from app.mcp.tools_status import get_bot_status, get_portfolio

TOOL_FUNCS: dict[str, Any] = {
    "get_bot_status": get_bot_status,
    "get_portfolio": get_portfolio,
    "get_pnl": get_pnl,
    "get_open_positions": get_open_positions,
    "get_latest_signals": get_latest_signals,
    "get_agent_pipeline": get_agent_pipeline,
    "get_learning_insights": get_learning_insights,
    "get_trade_journal": get_trade_journal,
    "get_chart_observations": get_chart_observations,
    "get_candles": get_candles,
    "get_ticker": get_ticker,
    "get_data_source": get_data_source,
    "list_backtest_artifacts": list_backtest_artifacts,
    "get_backtest_artifact": get_backtest_artifact,
    "run_backtest": run_backtest,
    "get_system_health": get_system_health,
    "send_ops_notification": send_ops_notification,
}

__all__ = list(TOOL_FUNCS) + ["TOOL_FUNCS"]

