# Checkpoint Sprint 25 - Indicators (Liquidity + Structure)

## Ruang Lingkup

Sprint ini mengimplementasikan lapisan indikator baru untuk strategi
Liquidity + S/R + Trend + Multi-Timeframe sesuai kontrak
`docs/strategy_liquidity_sr_mtf.md` section 7.1. Semua fungsi bersifat pure
(tanpa I/O), deterministic, dan mengembalikan struktur JSON-serializable.
Tidak ada perubahan pada rule engine, signal builder, execution, live
trading, atau modul indikator lama.

## Files Changed

- `app/indicators/liquidity_structure.py` (baru) - lima fungsi indikator
  + lima dataclass frozen:
  - `SwingPoint`, `StructureState`, `Zone`, `LiquidityPool`, `SweepEvent`
    (semua punya `to_dict()`).
  - `swing_points(candles, left=2, right=2)` - deteksi fractal swing high
    dan low, klasifikasi `HH`/`HL`/`LH`/`LL` relatif ke swing sesamanya.
  - `structure_state(swings)` - trend `UP`/`DOWN`/`SIDE`, plus `last_bos`
    dan `last_choch`.
  - `sr_zones(candles, swings)` - support dan resistance dari swing anchor,
    zone body candle, merge overlap, deteksi `mitigated`.
  - `liquidity_pools(candles, swings)` - BUY_SIDE dan SELL_SIDE pool di
    setiap swing dengan flag `swept` dan `fresh`.
  - `sweep_events(candles, pools)` - satu event per pool yang disapu,
    dengan flag `confirmed` untuk membedakan liquidity grab dari breakout
    (sesuai spec section 5).
- `tests/test_liquidity_structure.py` (baru) - 18 unit test.
- `docs/CHECKPOINT_SPRINT_25_INDICATORS.md` (baru) - checkpoint ini.
- `docs/ROADMAP.md` - tambah entri Sprint 25 di daftar "Selesai".

## Summary

- **Deterministic dan pure**: setiap fungsi bergantung hanya pada input
  candles/swings; tidak ada state global, tidak ada I/O, tidak ada waktu
  wall-clock. Cocok untuk backtest, research layer, dan MTF scanner.
- **Backward compatibility**: `app/indicators/structure.py` (helper skalar
  legacy `find_swing_high`/`find_swing_low`/`find_nearest_support`/
  `find_nearest_resistance`) tidak diubah. `app/indicators/technical.py`
  juga tidak diubah. Semua rule dan strategi yang sudah ada tetap
  berjalan tanpa modifikasi.
- **JSON-serializable**: semua dataclass punya `to_dict()` yang
  mengembalikan struktur `json.dumps`-friendly (tuple `anchor_indices`
  dikonversi ke list). Verifikasi via test khusus.
- **Sweep vs breakout**: `SweepEvent.confirmed = True` hanya ketika candle
  yang menyapu close kembali ke sisi awal (untuk BUY_SIDE: close di bawah
  pool price). Ini persis mengimplementasikan aturan mutlak section 5
  dokumen strategi. Breakout asli (close melewati level) menghasilkan
  `confirmed=False`, siap dipakai `rule_not_breakout` di Sprint 27.
- **Fresh liquidity**: `LiquidityPool.fresh = not swept`. Sprint 27 akan
  memakai flag ini sebagai veto (`rule_fresh_liquidity_present`).

## Tests

- 18 test baru di `tests/test_liquidity_structure.py`:
  - swing_points: deteksi symmetric fractal, determinisme, edge case data
    pendek, validasi window.
  - structure_state: UP + BOS, DOWN + BOS + CHoCH, mixed SIDE, empty.
  - sr_zones: build support + resistance dari swing, deteksi mitigasi.
  - liquidity_pools: swept + fresh, all-fresh case.
  - sweep_events: confirmed liquidity grab, non-confirmed breakout,
    skip fresh pools.
  - JSON serializability lintas seluruh dataclass.
  - Backward compatibility legacy `app/indicators/structure.py`.
  - Exposure semua tipe dataclass.

## Verification

- `./.venv/bin/python -m compileall app tests` - bersih.
- `./.venv/bin/python -m pytest --ignore=tests/test_klines_api.py` -
  hijau, 87/87 (termasuk 18 test baru sprint ini).
- `tests/test_klines_api.py` gagal collect karena environment VPS ini
  tidak punya `httpx2` (dependency starlette TestClient); ini pre-existing
  issue di lingkungan, bukan regresi Sprint 25. Kode dan test Sprint 25
  tidak menyentuh FastAPI/starlette. Silakan install `httpx2` pada VPS
  produksi untuk memulihkan test itu terpisah dari sprint ini.

## Follow-up

Sprint 26 (strategi `app/strategies/liquidity_sr_mtf.py`) akan mengonsumsi
lima fungsi ini melalui `MultiTimeframeScanner` dan mengemit
`StrategyDecision` sesuai kontrak section 7.2 dokumen strategi.
