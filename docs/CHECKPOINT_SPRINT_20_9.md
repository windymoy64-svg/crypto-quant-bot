# CHECKPOINT SPRINT 20.9 - Order Intent Engine

## Architecture

Sprint 20.9 menambahkan Order Intent Engine sebelum payload dry run dibuat:

Signal -> Risk -> Exchange Validator -> Account Preflight -> Order Intent -> Payload Builder -> Dry Run.

Engine ini hanya memutuskan intent lokal untuk mencegah duplicate order, overtrading, dan signal spam. Tidak ada order submission.

## Files Added

- `app/live/intent.py`
- `app/live/order_history.py`
- `app/live/cooldown.py`
- `tests/test_order_intent.py`
- `docs/CHECKPOINT_SPRINT_20_9.md`

## Verification

Commands:

```bash
python -m compileall app
python -m pytest tests/test_order_intent.py
```

## Known Limitations

- Order history masih in-memory dan belum dipersist ke disk.
- Existing position source diinject sebagai `position_symbols`; belum otomatis membaca portfolio/live position karena Sprint 20.9 tidak mengubah portfolio.
- Duplicate payload dicegah lewat kombinasi same symbol, same side, active history/open order, dan cooldown intent.
- Intent engine bersifat opsional di `LiveTradingManager` agar backward compatibility tetap aman.

## Next Sprint

- Persist order intent history ke JSONL/SQLite ringan.
- Tambahkan payload fingerprint eksplisit jika format payload bertambah.
- Tambahkan wiring CLI/config untuk mengaktifkan intent engine bersama account preflight.