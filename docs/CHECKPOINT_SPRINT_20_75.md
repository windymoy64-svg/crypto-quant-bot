# CHECKPOINT SPRINT 20.75 - Binance Account Preflight Engine

## Architecture

Sprint 20.75 menambahkan account preflight read-only sebelum live dry run payload dibuat:

Signal -> Risk Manager -> Exchange Validator -> Account Preflight -> Payload Builder -> Live Executor (DRY RUN) -> STOP.

Preflight memakai connector Binance yang sudah ada dan hanya membaca endpoint `GET /api/v3/account`, `GET /api/v3/openOrders`, dan helper `GET /api/v3/myTrades` bila dibutuhkan oleh caller.

## Files Added

- `app/live/account.py`
- `app/live/preflight.py`
- `app/live/account_validator.py`
- `tests/test_account_preflight.py`
- `docs/CHECKPOINT_SPRINT_20_75.md`

## Verification

Commands:

```bash
python -m compileall app
python -m pytest tests/test_account_preflight.py
```

## Known Limitations

- Account preflight bersifat opsional di `LiveTradingManager` untuk menjaga backward compatibility dan mencegah network call otomatis pada dry-run lama.
- `myTrades` tersedia sebagai read-only reader helper, tetapi validasi Sprint 20.75 belum memakai trade history.
- Balance check saat ini fokus pada USDT karena payload dry-run menggunakan quote amount USDT.
- Duplicate order check memakai open order side dan symbol yang sama.

## Next Sprint

- Tambahkan wiring eksplisit dari CLI/config untuk membuat `AccountPreflightEngine` dengan credential operator.
- Tambahkan warning non-blocking untuk stale account update time atau locked balance tinggi.
- Tambahkan audit log preflight yang bisa di-redact untuk operasi live-readiness.