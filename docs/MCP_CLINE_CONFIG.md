# Ops MCP — Cline / Claude Desktop Config

## Install dependency (one-time)

```bash
cd /opt/crypto-quant-bot
./.venv/bin/pip install 'mcp>=1.27,<2'
```

Package `mcp` is optional for the trading runtime. Only the MCP server entrypoint needs it.

## Run server manually

```bash
cd /opt/crypto-quant-bot
./.venv/bin/python -m app.mcp.server
```

Transport: **stdio** (default for IDE clients).

## Cline / Claude Desktop example

```json
{
  "mcpServers": {
    "crypto-quant-bot": {
      "command": "/opt/crypto-quant-bot/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/opt/crypto-quant-bot"
    }
  }
}
```

## Tools (all read-only)

| Tool | Purpose |
|---|---|
| `get_bot_status` | Health + artifact flags |
| `get_portfolio` | Equity / balance / positions summary |
| `get_pnl` | Analytics report or paper fallback |
| `get_open_positions` | Open paper positions |
| `get_latest_signals` | Scanner output |
| `get_agent_pipeline` | Multi-agent coordinator JSON |
| `get_learning_insights` | LearningAgent insight |
| `get_trade_journal` | Journal JSONL tail |
| `get_chart_observations` | Chart observation tail |

## Safety

- No place/cancel order tools
- Path allowlist: `logs/`, `data/`, `configs/`, `reports/`
- Secrets redacted from payloads
- Live trading path unchanged and still locked by existing gates

See `docs/MCP_MAP.md` for architecture and future phases.

### Market (MCP-2)

| Tool | Purpose |
|---|---|
| `get_candles` | OHLCV via `MarketDataService` |
| `get_ticker` | Ticker via `MarketDataService` |
| `get_data_source` | Source/warning metadata only |

Parameters: symbol (`BTC/USDT` or `BTCUSDT`), timeframe (`1m`…`1d`), limit 1–500,
exchange (`binance`|`bitunix`|`okx`), force_refresh (default false).
