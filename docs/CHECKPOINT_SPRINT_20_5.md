# CHECKPOINT SPRINT 20.5 - Binance Exchange Rules Engine

## Architecture

Sprint 20.5 menambahkan read-only Binance Exchange Rules Engine untuk validasi dry run sebelum payload dibuat:

Binance Connector -> ExchangeInfo Loader -> Rule Cache -> Exchange Validator -> Live Validator -> Payload Builder -> DRY RUN.

Endpoint yang didukung hanya `GET /api/v3/exchangeInfo`. Tidak ada order submission, cancel, modify, open position, atau endpoint write lain.

## Files Added

- `app/live/exchange_rules.py`
- `app/live/exchange_cache.py`
- `app/live/exchange_validator.py`
- `tests/test_exchange_rules.py`
- `docs/CHECKPOINT_SPRINT_20_5.md`

## Verification

Commands:

```bash
python -m compileall app
python -m pytest tests/test_exchange_rules.py
```

## Known Limitations

- Validasi exchange rules masih fokus minimal pada `PRICE_FILTER`, `LOT_SIZE`, `MIN_NOTIONAL`, `NOTIONAL`, `MARKET_LOT_SIZE`, dan `MAX_NUM_ORDERS` metadata.
- Cache default TTL 3600 detik dan disimpan lokal di `logs/exchange_info_cache.json` bila loader dipakai.
- `LiveTradingManager` menerima `exchange_validator` opsional agar backward compatibility Sprint 20A tetap aman dan tidak memaksa network call di dry-run test existing.
- Validasi precision lanjut dan rounding otomatis belum dilakukan; engine hanya reject input yang tidak sesuai rules.

## Next Sprint

- Sprint 21 dapat menambahkan quantity/price normalizer yang aman sebelum payload dry run.
- Sprint 21 dapat menambahkan exchange-rule audit output detail ke dry-run logs.
- Sprint 21 dapat menambahkan failover cache stale-read jika Binance read-only endpoint sedang unavailable.