# CHECKPOINT SPRINT 22 - Order Lifecycle Manager

## Architecture Review

Sprint 22 menambahkan lifecycle layer setelah order submission:

Order Submission -> Order Lifecycle -> Order State -> Portfolio Sync -> Dashboard -> Analytics.

Implementasi bersifat backward compatible dan tidak mengubah Rule Engine, Scanner, Risk Engine, Strategy, atau Paper Trading.

## Summary

- `OrderState` mendukung `NEW`, `PARTIALLY_FILLED`, `FILLED`, `CANCELED`, `EXPIRED`, dan `REJECTED`.
- `OrderStore` menyimpan `order_id`, `client_order_id`, `symbol`, `status`, `filled_qty`, `remaining_qty`, `average_price`, `create_time`, dan `update_time`.
- `LiveOrderLifecycleManager` menerima `OrderSubmissionResult`, menyimpan record, refresh via monitor read-only, update state, dan publish event.
- Event bus publish `OrderCreated`, `OrderPartiallyFilled`, `OrderFilled`, `OrderCanceled`, `OrderRejected`, dan `OrderExpired`.
- Portfolio sync opsional hanya membuka posisi saat `FILLED`; `PARTIALLY_FILLED` hanya update qty di order store; `CANCELED` tidak membuka posisi.
- Dashboard dapat membaca `open_orders`, `filled_orders`, `rejected_orders`, dan `order_history` dari `OrderStore.dashboard_snapshot()`.
- Analytics journal opsional menerima `OrderFilled` melalui entry source `live_order_filled`.

## Files Created

- `app/live/lifecycle.py`
- `app/live/order_state.py`
- `app/live/order_store.py`
- `app/live/order_events.py`
- `tests/test_order_lifecycle.py`
- `docs/CHECKPOINT_SPRINT_22.md`

## Files Modified

- `app/live/__init__.py`
- `app/dashboard/services.py`
- `app/dashboard/routes/portfolio.py`
- `app/dashboard/static/dashboard.js`
- `app/dashboard/templates/index.html`

## Compile Result

Passed:

```bash
python -m compileall app
```

Result: app modules compiled successfully, including lifecycle, order store, and dashboard read-only order view.

## Pytest Result

Passed:

```bash
python -m pytest tests/test_order_lifecycle.py
```

Result: 5 passed.

Backward compatibility check:

```bash
python -m pytest tests/test_live_submission.py tests/test_order_lifecycle.py
```

Result: 10 passed.

## Remaining TODO

- Persist `OrderStore` to durable storage.
- Add analytics subscriber that records `OrderFilled` events automatically.
- Add polling scheduler for order monitor in a later sprint.