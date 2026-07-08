# CHECKPOINT SPRINT 21 - Live Order Submission Engine

## Architecture Review

Sprint 21 menambahkan jalur live submission yang tetap melewati safety gate:

Signal -> Risk -> Exchange Validator -> Account Preflight -> Order Intent -> Payload Builder -> Safety Gate -> Binance Order Submission -> Order Response -> Order Monitor.

Live trading tidak aktif secara default. Order hanya bisa dikirim jika operator mengubah `enabled=true`, `dry_run=false`, dan `confirm_live=true`.

## Summary

- `LiveSafetyGate` memblokir submission saat `enabled=false`, `dry_run=true`, atau `confirm_live=false`.
- `BinanceOrderSubmissionEngine.submit_order()` adalah satu-satunya jalur yang memanggil `POST /api/v3/order`.
- `OrderSubmissionResult` memodelkan response Binance Spot order.
- `BinanceOrderMonitor` menambahkan wrapper read-only untuk order status, open orders, dan trade history.
- `LiveTradingManager` mendukung submission engine opsional setelah payload builder.

## Files Created

- `app/live/submission.py`
- `app/live/safety.py`
- `app/live/response.py`
- `app/live/order_monitor.py`
- `tests/test_live_submission.py`
- `docs/CHECKPOINT_SPRINT_21.md`

## Files Modified

- `app/exchange/binance/client.py`
- `app/live/config.py`
- `configs/live.json`
- `app/live/__init__.py`
- `app/live/manager.py`

## Compile Result

Passed:

```bash
python -m compileall app
```

Result: app modules compiled successfully, including Binance connector and Sprint 21 live modules.

## Pytest Result

Passed:

```bash
python -m pytest tests/test_live_submission.py
```

Result: 5 passed.

Backward compatibility check:

```bash
python -m pytest tests/test_live_dry_run.py tests/test_exchange_rules.py tests/test_account_preflight.py tests/test_order_intent.py tests/test_live_submission.py
```

Result: 31 passed.

## Remaining TODO

- Wire explicit operator confirmation flow outside config file edits.
- Add durable order response journal.
- Add richer monitor polling in a later sprint.