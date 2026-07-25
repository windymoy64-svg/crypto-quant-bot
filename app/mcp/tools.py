"""Public re-exports for Ops MCP tool functions."""

from __future__ import annotations

from typing import Any

from app.mcp.tools_journal import (
    get_chart_observations,
    get_learning_insights,
    get_trade_journal,
)
from app.mcp.tools_market import get_candles, get_data_source, get_ticker
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
}

__all__ = [
    "TOOL_FUNCS",
    "get_agent_pipeline",
    "get_bot_status",
    "get_candles",
    "get_chart_observations",
    "get_data_source",
    "get_latest_signals",
    "get_learning_insights",
    "get_open_positions",
    "get_pnl",
    "get_portfolio",
    "get_ticker",
    "get_trade_journal",
]
