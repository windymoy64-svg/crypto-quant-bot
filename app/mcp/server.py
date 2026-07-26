"""Ops MCP server entrypoint (stdio).

Run:

    /opt/crypto-quant-bot/.venv/bin/python -m app.mcp.server

Requires the official ``mcp`` package (v1.x recommended):

    ./.venv/bin/pip install 'mcp>=1.27,<2'
"""

from __future__ import annotations

import json
from typing import Any

from app.mcp import tools as ops_tools


def _json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)


def build_mcp_server() -> Any:
    """Build FastMCP server with all Ops + Market tools registered."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "mcp package is not installed. Install with:\n"
            "  ./.venv/bin/pip install 'mcp>=1.27,<2'\n"
            f"Original error: {exc}"
        ) from exc

    mcp = FastMCP(
        "crypto-quant-bot-ops",
        instructions=(
            "Read-only Ops + Market MCP for crypto-quant-bot. "
            "Inspect status, portfolio, signals, pipeline, journals, and "
            "public OHLCV/ticker via MarketDataService, and offline backtests. "
            "Never place orders. Live trading stays locked."
        ),
    )

    @mcp.tool()
    def get_bot_status() -> str:
        """Bot / system health and artifact presence flags."""
        return _json(ops_tools.get_bot_status())

    @mcp.tool()
    def get_portfolio() -> str:
        """Paper portfolio equity, balance, and open positions summary."""
        return _json(ops_tools.get_portfolio())

    @mcp.tool()
    def get_pnl() -> str:
        """PnL / performance from analytics report or paper fallback."""
        return _json(ops_tools.get_pnl())

    @mcp.tool()
    def get_open_positions() -> str:
        """List open paper positions and pending orders."""
        return _json(ops_tools.get_open_positions())

    @mcp.tool()
    def get_latest_signals(limit: int = 50) -> str:
        """Latest scanner signals (long/short) from logs/latest_signals.json."""
        return _json(ops_tools.get_latest_signals(limit=limit))

    @mcp.tool()
    def get_agent_pipeline() -> str:
        """Latest multi-agent pipeline coordinator output."""
        return _json(ops_tools.get_agent_pipeline())

    @mcp.tool()
    def get_learning_insights() -> str:
        """LearningAgent insight (hot/cold patterns, regime calibration)."""
        return _json(ops_tools.get_learning_insights())

    @mcp.tool()
    def get_trade_journal(limit: int = 20, symbol: str | None = None) -> str:
        """Tail of trade / learning journal JSONL."""
        return _json(ops_tools.get_trade_journal(limit=limit, symbol=symbol))

    @mcp.tool()
    def get_chart_observations(
        limit: int = 20,
        symbol: str | None = None,
        stage: str | None = None,
    ) -> str:
        """Recent Chart Agent observations."""
        return _json(
            ops_tools.get_chart_observations(limit=limit, symbol=symbol, stage=stage)
        )

    @mcp.tool()
    def get_candles(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 100,
        exchange: str = "binance",
        force_refresh: bool = False,
    ) -> str:
        """OHLCV candles via MarketDataService (cache + public exchange fallback)."""
        return _json(
            ops_tools.get_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                exchange=exchange,
                force_refresh=force_refresh,
            )
        )

    @mcp.tool()
    def get_ticker(symbol: str, exchange: str = "binance") -> str:
        """Latest ticker via MarketDataService."""
        return _json(ops_tools.get_ticker(symbol=symbol, exchange=exchange))

    @mcp.tool()
    def get_data_source(
        symbol: str,
        timeframe: str = "1h",
        limit: int = 5,
        exchange: str = "binance",
    ) -> str:
        """Candle fetch metadata only (source/warning) for debugging data path."""
        return _json(
            ops_tools.get_data_source(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                exchange=exchange,
            )
        )


    @mcp.tool()
    def list_backtest_artifacts(limit: int = 20) -> str:
        """List recent backtest JSON artifacts under logs/backtests/."""
        return _json(ops_tools.list_backtest_artifacts(limit=limit))

    @mcp.tool()
    def get_backtest_artifact(name: str) -> str:
        """Read one backtest artifact by filename (no path traversal)."""
        return _json(ops_tools.get_backtest_artifact(name=name))

    @mcp.tool()
    def run_backtest(
        symbol: str = "BTC/USDT",
        timeframe: str = "1h",
        limit: int = 300,
        exchange: str = "binance",
        initial_cash: float = 10000.0,
        use_sample_data: bool = False,
    ) -> str:
        """Run guarded historical backtest; writes only to logs/backtests/."""
        return _json(
            ops_tools.run_backtest(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                exchange=exchange,
                initial_cash=initial_cash,
                use_sample_data=use_sample_data,
            )
        )

    @mcp.tool()
    def get_system_health() -> str:
        """System health snapshot + artifact flags (read-only)."""
        return _json(ops_tools.get_system_health())

    @mcp.tool()
    def send_ops_notification(
        message: str, live: bool = False, prefix: str = "[ops-mcp]"
    ) -> str:
        """Send ops Telegram notification. Default dry-run; live needs env creds."""
        return _json(
            ops_tools.send_ops_notification(
                message=message, live=live, prefix=prefix
            )
        )

    return mcp



def main() -> None:
    mcp = build_mcp_server()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
