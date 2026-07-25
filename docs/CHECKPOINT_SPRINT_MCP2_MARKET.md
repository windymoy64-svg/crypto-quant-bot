# Checkpoint — Sprint MCP-2 Market Thin Wrap

## Goal

Menambahkan tool market read-only di Ops MCP yang **membungkus**
`MarketDataService` existing — tanpa reimplement client exchange dan tanpa
memindahkan scanner/regime/MTF ke MCP.

## Tools baru

| Tool | Perilaku |
|---|---|
| `get_candles(symbol, timeframe, limit, exchange, force_refresh)` | `MarketDataService.fetch_ohlcv` |
| `get_ticker(symbol, exchange)` | `MarketDataService.fetch_ticker` |
| `get_data_source(...)` | Metadata source/warning saja |

## Guards

- Exchange allowlist: `binance`, `bitunix`, `okx`
- Timeframe allowlist: 1m–1d (set yang sama dengan dashboard)
- Limit max 500
- Symbol dinormalisasi (`BTCUSDT` → `BTC/USDT`)
- Secret keys di ticker di-redact
- `fallback_to_sample_data=True` (sama seperti dashboard klines path)

## Tidak diubah

- Hot path scanner / `run_realtime`
- Fallback chain di dalam `MarketDataService`
- Execution / live gates

## Verify

```bash
./.venv/bin/python -m pytest tests/test_mcp_ops.py -q
./.venv/bin/python -c "from app.mcp.tools import get_candles; print(get_candles('BTC/USDT', limit=3)['source'])"
```
