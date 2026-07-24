# Scanner backup — pre momentum prefilter (2026-07-24)

Restore if needed:

```bash
cp backups/scanner_pre_momentum_20260724/scanner.py app/market/scanner.py
cp backups/scanner_pre_momentum_20260724/public_http_client.py app/exchange/public_http_client.py
cp backups/scanner_pre_momentum_20260724/market_scan.json configs/market_scan.json
cp backups/scanner_pre_momentum_20260724/test_market_scanner.py tests/test_market_scanner.py
cp backups/scanner_pre_momentum_20260724/run_realtime.py run_realtime.py
```

New features after this backup:
- TickerSnapshot + min_quote_volume_usdt
- symbol_mode: top_volume | top_gainer | top_loser | momentum_liquid
- market_breadth + move_alerts in ScanRankings / latest_signals.json
- meta: change_24h_pct, vol_usdt_24h, liquidity_quality, rs_vs_market
