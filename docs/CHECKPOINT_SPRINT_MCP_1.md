# Checkpoint — Sprint MCP-1 (Ops MCP Read-Only)

## Goal

Menambahkan lapisan **Ops MCP read-only** agar operator AI (Cline/Claude) bisa
membaca status bot, portfolio, signals, agent pipeline, dan journal tanpa
mengubah core engine atau membuka live execution.

## Deliverables

| Item | Path |
|---|---|
| Package | `app/mcp/` |
| Guards | `app/mcp/guards.py` |
| Tools | `app/mcp/tools_*.py`, `app/mcp/tools.py` |
| Server | `app/mcp/server.py` (`python -m app.mcp.server`) |
| Tests | `tests/test_mcp_ops.py` |
| Map | `docs/MCP_MAP.md` |
| Setup | `docs/MCP_SETUP.md` |

## Tools

- `get_bot_status`
- `get_portfolio`
- `get_pnl`
- `get_open_positions`
- `get_latest_signals`
- `get_agent_pipeline`
- `get_learning_insights`
- `get_trade_journal`
- `get_chart_observations`

## Safety

- Read-only only; no place/cancel order.
- Path allowlist: `logs/`, `data/`, `configs/`, `reports/`.
- Secret key redaction in payloads.
- Does not change scoring, signals, risk, paper, live gates.
- MCP Python SDK is optional; tools importable without it.

## How to enable MCP transport

```bash
./.venv/bin/pip install 'mcp>=1.27,<2'
./.venv/bin/python -m app.mcp.server
```

Client config: see `docs/MCP_SETUP.md`.

## Verify

```bash
./.venv/bin/python -c "from app.mcp.tools import get_bot_status; print(get_bot_status()['ok'])"
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
```

## Out of scope (later)

- Market wrap, backtest trigger, execution MCP, monorepo split.
