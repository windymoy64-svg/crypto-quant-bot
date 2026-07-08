# Sprint 23 - Strategy Validation Research Layer

Status: Selesai.

Boundary: research layer bersifat read-only terhadap artifact yang sudah ada. Tidak menyentuh eksekusi trading, scanner, rule engine, risk engine, portfolio, atau dashboard. Hanya menambahkan modul `app/research/*`, entrypoint `run_research.py`, dan test `tests/test_research.py`. Tidak ada perubahan pada payload signal, business logic, ataupun public API yang sudah stabil di Sprint 22 dan Final Release.

## Ruang Lingkup

- Loader artifact tunggal (`app/research/artifacts.py`) yang membaca:
  - `logs/backtests/*.json` untuk trade history, equity curve, feature importance, dan metadata symbol/timeframe/regime.
  - `logs/paper_state.json` untuk fills dan trades paper trading.
  - `logs/paper_trades.jsonl` untuk stream trade paper jika tersedia.
  - `logs/*feature*importance*.json` untuk artifact feature importance eksternal.
- Loader toleran terhadap artifact yang hilang: mengembalikan section kosong, tidak melempar exception.
- Engine analisis (`app/research/engine.py`) menghasilkan report deterministic untuk:
  - Overall performance: net profit, gross profit, gross loss, win rate, profit factor, Sharpe, Sortino, Calmar, recovery factor, expectancy, average win, average loss, max drawdown.
  - Pair analysis ranked by net profit, win rate, profit factor, dan trade count.
  - Timeframe analysis untuk `5m`, `15m`, `1h`, `4h`, `1d` bila datanya ada.
  - Market regime analysis untuk Bull, Bear, Sideways, High Volatility, Low Volatility.
  - Rule attribution berdasarkan kontribusi, win rate, average score, dan trigger frequency.
  - Feature importance summary dari artifact yang sudah ada.
  - Time-of-day dan day-of-week analysis.
  - Longest winning streak dan longest losing streak.
  - Trade duration analysis.
  - Equity curve summary.
- Report writer (`app/research/reports.py`) mengeluarkan tiga format:
  - `reports/strategy_report.json`
  - `reports/strategy_report.html` (ECharts, statis, tanpa backend baru)
  - `reports/strategy_report.csv`
- Entrypoint `run_research.py` menjalankan runner tanpa argumen kompleks.
- Dokumentasi pengguna: `docs/STRATEGY_VALIDATION.md`.

## Kontrak Data

- Trade record dinormalkan ke `ResearchTrade` dengan field lengkap (`symbol`, `timeframe`, `entry_time`, `exit_time`, `net_pnl`, `gross_pnl`, `fees`, `return_percent`, `score`, `market_regime`, `rules`, `features`, `source`).
- Equity point dinormalkan ke `ResearchEquityPoint` (`timestamp`, `equity`, `drawdown_percent`, `source`).
- Regime dibersihkan ke lima kategori standar plus `unknown` untuk nilai tidak dikenali.
- Semua angka melewati `_float()` untuk menghindari `TypeError` dari input JSON yang kotor.

## Safety Gates

- Tidak ada koneksi jaringan.
- Tidak ada state yang diubah pada `logs/paper_state.json` atau file backtest.
- Tidak ada write ke luar `reports/` yang dibuat oleh writer.
- Tidak ada dependency runtime baru; report HTML memakai ECharts via CDN, di-embed sebagai static asset.

## Verifikasi

```bash
python -m compileall app tests
python -m pytest
```

Snapshot verifikasi Sprint 23:

- `python -m compileall app tests` bersih.
- `python -m pytest` hijau, 66/66.
- Test yang menutupi sprint ini: `tests/test_research.py`
  - `test_strategy_research_generates_required_sections`
  - `test_strategy_report_writer_outputs_all_formats`

## Files Changed Pada Sprint 23

- `app/research/__init__.py`
- `app/research/artifacts.py`
- `app/research/engine.py`
- `app/research/reports.py`
- `app/research/runner.py`
- `run_research.py`
- `tests/test_research.py`
- `docs/STRATEGY_VALIDATION.md`

## Catatan Untuk Sprint Berikutnya

- Report ini deliberately read-only. Jika ingin dipakai untuk mengubah rule weight atau seleksi symbol otomatis, itu harus jadi sprint terpisah dengan review manual, bukan side effect Sprint 23.
- Batch backtest lintas pair/timeframe tetap menjadi kandidat di backlog. Sprint 23 hanya membaca artifact yang sudah dihasilkan runner backtest existing.
- Alerting drawdown dan consecutive loss belum di-scope di sini; itu masuk ke sprint alerting terpisah.
