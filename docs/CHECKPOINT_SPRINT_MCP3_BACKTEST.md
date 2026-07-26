# Checkpoint — Sprint MCP-3 Backtest Tools

## Goal

Expose guarded offline backtest ops to operator AI via MCP:

- list existing artifacts
- read one artifact (truncated)
- run a single-symbol historical backtest into `logs/backtests/`

## Tools

| Tool | Mutasi? | Guard |
|---|---|---|
| `list_backtest_artifacts(limit)` | Read | only `logs/backtests/` |
| `get_backtest_artifact(name)` | Read | filename only, no path traversal |
| `run_backtest(...)` | Write artifact only | exchange/tf allowlist, limit 50–1000, output dir fixed |

## Safety

- No live order placement
- No paper state mutation
- Output locked under `logs/backtests/`
- `use_sample_data=true` for fully offline runs/tests
- Secrets scrubbed from artifact payloads

## Verify

```bash
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
./.venv/bin/python -c "from app.mcp.tools import run_backtest; print(run_backtest(use_sample_data=True, limit=80)['ok'])"
```
