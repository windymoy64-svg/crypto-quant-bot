# Checkpoint — Premature Break-Even Exit Fix

## Problem (from Order History)

Many closes showed:

- reason: `structure_invalidation` / `acr_invalidation_counter_cisd`
- PnL ≈ `+0.00` / `-0.01` (break-even spam)
- exits within minutes of entry

This hurt winrate: winners never developed, losers/flat were flattened by noise.

## Root causes

1. **Decision agent** treated *any* historical CHoCH in `structure_breaks` as EXIT with urgency **IMMEDIATE**.
2. **`close_from_decision`** always closed on IMMEDIATE — even at break-even / micro-PnL.
3. **ACR invalidation** scanned full-history counter CISD, including levels from before entry.

## Fixes

### `app/decision_agent/agent.py`

- Added `_recent_counter_choch()` — only CHoCH within last ~3 bars of the newest break index.
- EXIT on CHoCH only if **recent** + (bias against **or** weak confluence).
- Urgency changed from **IMMEDIATE** → **NEXT_CANDLE** so PnL/min-hold gates apply.
- Stale CHoCH no longer forces EXIT or TP1-on.

### `app/paper/realtime_engine.py` — `close_from_decision`

- IMMEDIATE no longer always-close.
- Suppress close when `-0.15R < pnl_ratio ≤ 0.35R` (BE / micro-PnL noise).
- Min-hold still applies in that band for fresh entries.
- Real losses (≤ -0.15R) or solid profits (> 0.35R) still close on IMMEDIATE.

### `app/strategies/acr_engine_bridge.py` — `check_acr_invalidation`

- Counter CISD only if `break_index` is near series edge (last 4 bars), else newest only.
- Avoids pre-entry CISD invalidating an open trade.

## Tests

```bash
./.venv/bin/python -m pytest \
  tests/test_decision_agent.py \
  tests/test_realtime_paper_engine.py \
  tests/test_acr_engine_bridge.py -q
```

Expected: all green (includes `test_hold_ignores_stale_choch`, soft CHoCH exit, IMMEDIATE BE suppress).

## Ops note

Restart realtime bot so the new exit logic loads:

```bash
systemctl restart crypto-quant-bot
# or your usual process manager
```

Live trading gates and scoring engine were not changed — only hold/exit noise filters.
