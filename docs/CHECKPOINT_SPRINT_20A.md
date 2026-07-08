# CHECKPOINT SPRINT 20A - Live Trading Dry Run Engine

## Architecture

Sprint 20A menambahkan live trading dry run layer yang berhenti sebelum network/order submission:

Signal -> Risk Manager -> Live Trading Manager -> Order Validator -> Binance Payload Builder -> DRY RUN -> Log JSON -> STOP.

Semua path live order dibuat fail-safe. `LiveExecutor` dengan `dry_run=true` hanya mengembalikan payload dan tidak melakukan network call. Path non-dry-run juga tetap ditolak untuk Sprint 20A.

## Files Added

- `app/live/__init__.py`
- `app/live/config.py`
- `app/live/models.py`
- `app/live/validator.py`
- `app/live/payload.py`
- `app/live/executor.py`
- `app/live/manager.py`
- `configs/live.json`
- `run_live.py`
- `tests/test_live_dry_run.py`
- `docs/CHECKPOINT_SPRINT_20A.md`

## Verification

Commands:

```bash
python -m compileall app
python -m pytest tests/test_live_dry_run.py
```

## Known Limitations

- Sprint 20A hanya mendukung `MARKET BUY` dry run payload untuk Binance.
- Tidak ada endpoint `POST /api/v3/order`, `POST /order`, cancel order, open position, atau modify position yang dipanggil.
- `max_daily_orders` masih in-memory per instance `LiveTradingManager`.
- `run_live.py` memakai latest local signal jika tersedia dan fallback sample signal bila artifact belum ada.

## Next Sprint

- Sprint 20B dapat menambahkan exchange filter validation seperti min notional, step size, dan quote precision.
- Sprint 20B dapat menambahkan audit log rotation untuk `logs/live_dry_run.jsonl`.
- Sprint 20B dapat menambahkan explicit operator confirmation gate sebelum mode non-dry-run pernah dipertimbangkan.
