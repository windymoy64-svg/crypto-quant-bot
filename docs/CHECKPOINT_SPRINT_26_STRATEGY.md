# Checkpoint Sprint 26 - Strategy (Liquidity + S/R + Trend + MTF)

## Ruang Lingkup

Sprint ini mengimplementasikan strategi baru
`app/strategies/liquidity_sr_mtf.py` sesuai kontrak section 7.2 dokumen
`docs/strategy_liquidity_sr_mtf.md`. Strategi ini pure dan deterministic,
mengonsumsi indikator dari Sprint 25 (`app/indicators/liquidity_structure.py`)
dan mengemit `StrategyDecision` (BUY / SELL / HOLD). Tidak ada perubahan
pada rule engine, `MultiTimeframeScanner`, signal builder, execution, live
trading, atau strategi lama.

## Files Changed

- `app/strategies/liquidity_sr_mtf.py` (baru, ~530 baris) - strategi
  deterministic. Fungsi publik:
  - `evaluate(ctx: MTFContext, *, zone_tolerance_pct, sl_buffer_pct, min_rr)
    -> StrategyDecision` (mengembalikan BUY / SELL / HOLD).
- Dataclass baru (semua frozen dengan `to_dict()`):
  - `MTFContext` - container tiga TF (big, mid, small) + label TF opsional.
  - `MTFAlignment` - ringkasan tren per TF + flag `aligned`.
  - `StrategyDecision` - action, reasons, mtf_alignment, anchor, entry,
    stop_loss, take_profit_1, take_profit_2, strategy, meta.
- `tests/test_liquidity_sr_mtf_strategy.py` (baru) - 12 unit test.
- `docs/CHECKPOINT_SPRINT_26_STRATEGY.md` (baru) - checkpoint ini.
- `docs/ROADMAP.md` - tambah entri Sprint 26 di daftar "Selesai" +
  update baseline verifikasi.

## Highlight Keputusan Desain

- **Hard-gate sebagai early-return HOLD** (mengimplementasikan aturan
  mutlak section 6 dokumen strategi):
  1. Empty candles => HOLD `empty_candles`.
  2. Big TF trend `SIDE` => HOLD `big_tf_trend_side`.
  3. Harga di luar zone S/R aktif => HOLD `no_active_support_zone` /
     `no_active_resistance_zone`.
  4. Tidak ada sweep terkonfirmasi di mid TF => HOLD
     `no_confirmed_sell_side_sweep` / `no_confirmed_buy_side_sweep`.
  5. Tidak ada fresh liquidity di target => HOLD
     `no_fresh_buy_side_target` / `no_fresh_sell_side_target`.
  6. Tidak ada konfirmasi candle di small TF => HOLD
     `no_small_tf_confirmation`.
  Setiap HOLD menulis alasan veto ke `meta.veto` untuk audit.

- **Anchor deterministic**: BUY hanya valid saat harga saat ini masuk
  zone `SUPPORT` yang belum dimitigasi (dengan toleransi 0.1% default).
  SELL hanya valid saat harga masuk zone `RESISTANCE` yang belum
  dimitigasi. Confidence tinggi tanpa anchor selalu HOLD, sesuai aturan
  section 6.

- **Fresh liquidity prioritas**: strategi memeriksa dua sisi likuiditas:
  (a) sisi yang harus sudah disapu (sell-side untuk BUY, buy-side untuk
  SELL) sebagai konfirmasi liquidity grab, dan (b) sisi berlawanan yang
  masih fresh untuk dijadikan target. Tanpa fresh target => HOLD.

- **Sweep vs breakout**: menggunakan flag `confirmed` dari `SweepEvent`
  Sprint 25. Breakout asli otomatis di-skip di level indikator, jadi
  strategi bebas dari false positive.

- **Konfirmasi small TF**: engulfing atau pin bar sederhana searah bias.
  Body/total ratio <= 0.35 untuk pin bar, wick 2x body dan 2x wick sisi
  lawan. Deterministic, tanpa parameter volatilitas eksternal.

- **Level entry/SL/TP**:
  - Entry: close terakhir di small TF.
  - Stop-loss: di luar wick sweep atau batas zone (mana yang lebih jauh
    dari entry) + buffer 0.1% default (section 4 aturan SL).
  - Take-profit 1: zone S/R berlawanan terdekat, di-clamp minimal 1:2 RR
    (section 8 manajemen risiko).
  - Take-profit 2: fresh pool di sisi target, di-clamp minimal TP1 + 1×
    risk supaya monotonic.

- **Tidak ada I/O**: fungsi murni. Tidak menyentuh disk, network, wall
  clock, atau state global. Aman untuk backtest, research layer, dan
  MTF loop.

- **Backward compatibility 100%**: strategi ini tidak mengubah
  `MultiTimeframeScanner`, `ScoreEngine`, `build_signal`,
  `configs/rules.json`, atau strategi lama. Sprint 27 akan menyambungkan
  strategi ini ke rule engine sebagai gate rule tambahan. Sprint 28 akan
  memasangnya ke `run_realtime.py`.

## Tests

- 12 test baru di `tests/test_liquidity_sr_mtf_strategy.py`:
  - Happy path BUY (semua hard-gate lolos + RR >= 1:2).
  - Determinisme (input sama => `to_dict()` sama).
  - HOLD karena empty candles.
  - HOLD karena big TF SIDE.
  - HOLD karena harga jauh di atas support zone.
  - HOLD karena tidak ada sweep terkonfirmasi di mid TF.
  - HOLD karena tidak ada konfirmasi small TF.
  - JSON serializability payload BUY.
  - JSON serializability payload HOLD + veto reason.
  - MTF alignment melaporkan trend per timeframe.
  - Happy path SELL (mirror BUY).
  - JSON serializability payload SELL.

## Verification

- `./.venv/bin/python -m compileall app tests` - bersih.
- `./.venv/bin/python -m pytest --ignore=tests/test_klines_api.py` -
  hijau, 99/99 (termasuk 12 test baru sprint ini + 87 lama tetap hijau).
- `tests/test_klines_api.py` tetap fail collect karena `httpx2` belum
  terpasang di venv (pre-existing environment issue, bukan regresi
  Sprint 26).

## Follow-up

Sprint 27 (rule scoring): tambah rule di `configs/rules.json`, dukungan
veto di `ScoreEngine`, profil bobot baru di `configs/rule_weights.json`.
Strategy `liquidity_sr_mtf` akan dipakai sebagai sumber sinyal alternatif
yang bisa dibandingkan dengan rule engine existing.
