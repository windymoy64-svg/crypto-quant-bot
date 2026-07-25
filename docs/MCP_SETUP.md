# Ops MCP Setup (Cline / Claude Desktop)

Read-only operator MCP for `/opt/crypto-quant-bot`.  
Full design map: `docs/MCP_MAP.md`.

## Install SDK (optional for transport)

Tool functions work without the SDK (used by unit tests).  
To run the MCP stdio server for Cline:

```bash
cd /opt/crypto-quant-bot
./.venv/bin/pip install 'mcp>=1.27,<2'
```

## Run server

```bash
cd /opt/crypto-quant-bot
./.venv/bin/python -m app.mcp.server
```

Or:

```bash
./.venv/bin/python -m app.mcp
```

## Cline / Claude Desktop config

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
| `get_pnl` | Analytics or paper PnL fallback |
| `get_open_positions` | Open positions + pending orders |
| `get_latest_signals` | `logs/latest_signals.json` |
| `get_agent_pipeline` | `logs/agent_pipeline.json` |
| `get_learning_insights` | LearningAgent insight |
| `get_trade_journal` | Tail of learning journal |
| `get_chart_observations` | Chart agent observations |

## Safety

- No place/cancel order tools
- Path allowlist: `logs/`, `data/`, `configs/`, `reports/`
- Secret-looking keys redacted in payloads
- Live trading path unchanged and remains locked by existing config

## Test without MCP client

```bash
cd /opt/crypto-quant-bot
./.venv/bin/python -c "from app.mcp.tools import get_bot_status; print(get_bot_status())"
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
```
