# Architecture

Dokumen ini menjelaskan arsitektur setelah Sprint 08. Fokus sistem adalah signal generation yang deterministic, explainable, dan aman sebelum live trading.

## Alur Utama

```text
market data -> features -> regime -> dynamic weights -> scoring -> signal -> output/log/API/paper
```

Tahapan:

1. Market data diambil dari exchange publik jika tersedia.
2. Jika koneksi atau dependency gagal, scanner memakai sample data agar pipeline tetap bisa diuji.
3. Feature builder menghitung input teknikal dari candle.
4. Market regime engine mengklasifikasikan kondisi pasar.
5. Dynamic weight engine memilih bobot rule sesuai regime.
6. Score engine mengevaluasi rule deterministic.
7. Signal builder membuat action, confidence, entry, stop loss, dan take profit.
8. Output disimpan atau dibaca oleh realtime runner, API, dan paper engine.

## Komponen

### `app/market`

- Mengelola load candle, public exchange data, scanner, regime, dan multi-timeframe scan.
- `MarketDataService` menjadi pintu utama untuk data live atau fallback.
- `MultiTimeframeScanner` menggabungkan beberapa timeframe menjadi satu keputusan agregat.

### `app/features`

- Mengubah candle mentah menjadi feature teknikal.
- Feature dipakai oleh scoring dan market regime.

### `app/scoring`

- `ScoreEngine` mengevaluasi rule dari config.
- `DynamicWeightEngine` mengganti bobot rule berdasarkan market regime.
- `FeatureImportanceEngine` merangkum kontribusi rule ke kelompok feature.
- Ranking lintas symbol sudah tersedia sebagai dasar untuk sprint berikutnya.

### `app/signals`

- Membuat payload signal JSON-ready.
- Payload berisi action, confidence, score, entry, stop loss, take profit, dan meta rule.

### `app/paper`

- Menjalankan simulasi order tanpa uang asli.
- State virtual disimpan di log agar bisa dilanjutkan antar run.

### `app/execution`

- Area live execution.
- Default tetap terkunci oleh config dan environment variable.

### `app/research`

- Bridge opsional ke workflow riset eksternal.
- Tidak boleh menjadi pengambil keputusan buy/sell.

## Config Dan Artifact

- `configs/rules.json` menyimpan rule deterministic.
- `configs/rule_weights.json` menyimpan profil bobot per market regime.
- `configs/market_scan.json` menyimpan parameter scan publik.
- `configs/realtime.json` menyimpan parameter realtime runner.
- `configs/paper_trading.json` menyimpan parameter paper trading.
- `configs/live_trading.json` mengunci live trading secara default.
- `logs/latest_signals.json` menyimpan signal terbaru.
- `logs/signals.jsonl` menyimpan riwayat signal.
- `logs/paper_state.json` menyimpan state paper trading.

## Safety Boundary

- Scanner tidak membutuhkan API key.
- Paper trading tidak membuat order asli.
- Live trading membutuhkan config, environment variable, dan mode dry-run yang disengaja.
- Execution engine hanya membaca signal; engine tidak boleh membuat keputusan baru sendiri.

## Data Contract

Payload utama harus JSON-ready dan audit-friendly:

- Symbol dan exchange/timeframe jelas.
- Score dan confidence numerik.
- Action berasal dari rule deterministic.
- Rule result menyimpan pass/fail, weight, score, dan reason.
- Feature importance menyimpan kontribusi feature terhadap total score.
- Multi-timeframe result menyimpan score per timeframe, final score, trend alignment, dan overall action.