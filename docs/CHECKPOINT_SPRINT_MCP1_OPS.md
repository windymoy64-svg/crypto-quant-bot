# Checkpoint — Sprint MCP-1 Ops MCP Read-Only

## Goal

Menambahkan lapisan **Ops MCP read-only** agar operator AI (Cline/Claude)
bisa membaca status bot, portfolio, signals, agent pipeline, dan journal
tanpa menyentuh scoring, risk, paper/live execution, atau place order.

## Deliverables

- Package `app/mcp/`:
  - `guards.py` — path allowlist, secret scrub, error envelopes
  - `io_utils.py` / `paths.py` — JSON/JSONL helpers
  - `tools_*.py` — pure tool functions (no MCP SDK required for unit tests)
  - `server.py` — FastMCP stdio entry (`python -m app.mcp.server`)
- Tests: `tests/test_mcp_ops.py`
- Docs: `docs/MCP_MAP.md`, `docs/MCP_CLINE_CONFIG.md`
- Dependency optional runtime: `mcp>=1.27,<2` di `requirements.txt`

## Tools

`get_bot_status`, `get_portfolio`, `get_pnl`, `get_open_positions`,
`get_latest_signals`, `get_agent_pipeline`, `get_learning_insights`,
`get_trade_journal`, `get_chart_observations`

## Safety

- Read-only only
- Allowlist: `logs/`, `data/`, `configs/`, `reports/`
- No order / credential mutation tools
- Secrets redacted from payloads
- Live trading gates unchanged

## Out of scope

- Market wrap (`get_candles`) — MCP-2
- Backtest trigger — MCP-3
- Execution MCP — not enabled

## Verify

```bash
./.venv/bin/python -m compileall app/mcp tests/test_mcp_ops.py
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
./.venv/bin/pip install 'mcp>=1.27,<2'   # if not installed
./.venv/bin/python -c "from app.mcp.server import build_mcp_server; build_mcp_server(); print('mcp ok')"
```
