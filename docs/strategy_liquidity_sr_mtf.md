# Strategy: Liquidity + Support/Resistance + Trend + Multi-Timeframe

Dokumen ini adalah spesifikasi strategi deterministic untuk bot. Dokumen ini
menjadi single source of truth untuk sprint implementasi berikutnya
(indikator, strategi, rule scoring, integrasi realtime). Dokumen ini tidak
mengubah kode; hanya mendefinisikan kontrak logika dan aturan mutlak.

Prinsip proyek tetap berlaku:

- LLM tidak mengambil keputusan buy/sell.
- Semua keputusan keluar sebagai JSON signal yang bisa diaudit.
- Rule engine harus deterministic: input sama menghasilkan output sama.
- Backward compatibility payload dan artifact wajib dijaga.

## 1. Konsep Inti

- **Support**: area tekanan beli muncul, kandidat entry `BUY`.
- **Resistance**: area tekanan jual muncul, kandidat entry `SELL`.
- **Liquidity**: tumpukan order dan stop-loss di atas swing high dan di bawah
  swing low. Harga sering menyapu (sweep / stop hunt) area ini terlebih dahulu
  sebelum bergerak ke arah sebenarnya.
- **Fresh liquidity**: level atau area yang belum pernah disentuh atau disapu
  harga sejak terbentuk. Level fresh punya probabilitas reaksi paling tinggi.
  Level yang sudah dimitigasi (disapu) jauh lebih lemah dan tidak boleh
  dipakai sebagai anchor entry utama.
- **Hubungan S/R dan liquidity**: S/R menjelaskan *di mana* area penting,
  liquidity menjelaskan *kenapa* harga menyentuh area itu terlebih dahulu
  sebelum berbalik.

## 2. Arah Tren

Tren dibaca dari struktur swing, bukan dari indikator tunggal.

- **Uptrend**: Higher High (HH) dan Higher Low (HL). Bias `BUY`.
- **Downtrend**: Lower High (LH) dan Lower Low (LL). Bias `SELL`.
- **Sideways**: swing high/low sejajar. Perlakukan sebagai range,
  tunggu breakout terkonfirmasi.

Alat bantu deterministic:

- **BOS (Break of Structure)**: harga menembus swing terakhir searah tren.
  Konfirmasi tren berlanjut.
- **CHoCH (Change of Character)**: harga menembus swing berlawanan arah tren
  saat itu. Sinyal potensi pembalikan tren.
- **EMA 50 / EMA 200**: alat bantu sekunder. Harga di atas MA dan MA menaik
  memperkuat bias naik. Sebaliknya untuk bias turun. EMA tidak boleh
  membatalkan sinyal struktur swing; hanya menambah bobot.

Aturan tren:

- Entry utama harus searah tren pada timeframe besar.
- Sweep di support saat uptrend jauh lebih valid daripada sweep melawan tren.


## 3. Multi-Timeframe (Tiga Lapis)

Strategi memakai tiga lapis timeframe. Timeframe besar selalu menang.

| Lapis        | Fungsi                                                              | Contoh Swing | Contoh Intraday | Contoh Scalping |
|--------------|---------------------------------------------------------------------|--------------|-----------------|-----------------|
| TF Besar     | Tentukan arah tren, tandai S/R mayor dan liquidity mayor (peta)     | `1d`         | `4h`            | `1h`            |
| TF Menengah  | Tunggu harga mendekati area kunci, awasi liquidity sweep            | `4h` atau `1h` | `1h` atau `15m` | `15m`           |
| TF Kecil     | Cari konfirmasi entry (CHoCH kecil, pin bar, engulfing) untuk timing | `1h`         | `15m`           | `5m` atau `1m`  |

Aturan multi-timeframe:

- Sinyal TF kecil yang melawan bias TF besar dianggap koreksi, bukan entry
  utama. Sinyal seperti ini harus di-skip oleh rule engine.
- Trend alignment lintas TF wajib disimpan di payload signal sebagai bagian
  dari `meta` (kompatibel dengan `MultiTimeframeScanner` yang sudah ada).

## 4. Alur Entry Gabungan

Contoh alur `BUY` pada uptrend intraday (TF Besar `4h`, TF Menengah `1h`,
TF Kecil `5m`):

1. `4h`: konfirmasi tren `UPTREND` via struktur swing (HH + HL) dan/atau BOS
   searah naik. Tandai support terdekat dan area liquidity fresh di bawahnya.
2. `1h`: tunggu harga turun ke support. Awasi sweep di bawah swing low
   terdekat (wick menembus level lalu ditolak, close kembali di dalam range).
3. `5m`: setelah sweep terkonfirmasi, tunggu CHoCH kecil atau candle
   penolakan (pin bar / bullish engulfing). Baru emit `BUY`.
4. **Stop-loss**: di bawah wick sweep (bukan tepat di garis support). Beri
   buffer volatilitas kecil untuk menghindari re-sweep.
5. **Take-profit**: resistance berikutnya atau area liquidity di atas.

Alur `SELL` pada downtrend adalah mirror-nya: sweep di atas resistance,
CHoCH bearish di TF kecil, SL di atas wick sweep, TP ke support / liquidity
di bawah.

## 5. Konfirmasi dan Filter

- Jangan entry langsung saat sweep terjadi. Wajib tunggu konfirmasi
  pembalikan (CHoCH kecil di TF entry, atau candle penolakan yang close di
  dalam range).
- Bedakan sweep dan breakout asli: jika harga menembus level dan close kuat
  di luar level dengan momentum, itu breakout, bukan liquidity grab.
  Rule engine harus mengevaluasi close-position relatif terhadap level, bukan
  hanya wick.
- Tiga lapis pembenaran wajib untuk tiap entry:
  1. Searah tren TF besar.
  2. Berada di area kunci S/R (support untuk `BUY`, resistance untuk `SELL`).
  3. Setelah likuiditas fresh disapu dan ada konfirmasi pembalikan.

## 6. Aturan Mutlak (Tidak Bisa Ditawar)

Aturan ini adalah hard-gate. Rule engine wajib menolak sinyal yang melanggar,
tanpa peduli seberapa tinggi confidence numerik.

- **Anchor wajib**: entry hanya boleh terjadi di area
  Liquidity / Support / Resistance. Tidak ada entry di tengah range atau area
  kosong, walaupun confidence tampak >= 90%.
- **Fresh liquidity prioritas**: utamakan area yang belum disentuh atau
  disapu. Area yang sudah dimitigasi tidak boleh menjadi anchor entry utama;
  boleh dipakai hanya sebagai target / referensi.
- **Confidence tanpa anchor = bukan setup**: jika confidence tinggi tetapi
  tidak ada area kunci yang valid, sinyal harus di-skip (action `HOLD`).
  Rule ini memiliki prioritas lebih tinggi daripada agregasi skor.

## 7. Kontrak Data untuk Sprint Berikutnya

Sprint implementasi harus menghasilkan artefak deterministic berikut. Nama
field bersifat normatif untuk menjaga kompatibilitas payload JSON.

### 7.1 Indikator baru (`app/indicators/`)

- `swing_points(candles, left, right) -> list[SwingPoint]`
  - `SwingPoint`: `{ index, timestamp, price, kind: "HH"|"HL"|"LH"|"LL" }`.
- `structure_state(swings) -> { trend: "UP"|"DOWN"|"SIDE", last_bos, last_choch }`
- `sr_zones(candles, swings) -> list[Zone]`
  - `Zone`: `{ kind: "SUPPORT"|"RESISTANCE", price_low, price_high, touches, mitigated: bool }`.
- `liquidity_pools(candles, swings) -> list[LiquidityPool]`
  - `LiquidityPool`: `{ side: "BUY_SIDE"|"SELL_SIDE", price, created_at, swept: bool, fresh: bool }`.
- `sweep_events(candles, pools) -> list[SweepEvent]`
  - `SweepEvent`: `{ pool_ref, wick_price, close_price, confirmed: bool }`.

Semua fungsi harus pure (tanpa I/O), deterministic, dan mengembalikan
struktur serializable JSON.

### 7.2 Strategi baru (`app/strategies/liquidity_sr_mtf.py`)

Fungsi utama:

```text
evaluate(mtf_context) -> StrategyDecision
```

`mtf_context` berisi hasil scan tiga timeframe (`big`, `mid`, `small`) yang
dihasilkan `MultiTimeframeScanner`. `StrategyDecision` mengembalikan:

- `action`: `"BUY" | "SELL" | "HOLD"`.
- `anchor`: referensi zone / pool yang dipakai (`null` jika `HOLD`).
- `entry`, `stop_loss`, `take_profit_1`, `take_profit_2`.
- `reasons`: list alasan deterministic (searah tren, di area S/R, sweep
  terkonfirmasi, konfirmasi TF kecil).
- `mtf_alignment`: ringkasan tren per timeframe.

### 7.3 Rule scoring (`configs/rules.json` + `app/scoring/`)

Rule baru yang wajib ada:

- `rule_trend_alignment_big_tf` (bobot tinggi).
- `rule_price_at_sr_zone` (hard-gate, lihat 7.4).
- `rule_fresh_liquidity_present` (hard-gate, lihat 7.4).
- `rule_sweep_confirmed`.
- `rule_confirmation_small_tf` (CHoCH kecil / candle penolakan).
- `rule_not_breakout` (filter breakout vs sweep).

Bobot per market regime memakai mekanisme `DynamicWeightEngine` yang sudah
ada; profil baru ditambahkan di `configs/rule_weights.json` tanpa mengubah
profil lama.

### 7.4 Hard-gate di Score Engine

`ScoreEngine` harus mendukung konsep rule *veto*: jika rule veto gagal,
`action` dipaksa `HOLD` walaupun total skor tinggi. Aturan mutlak di bagian 6
diimplementasikan sebagai veto:

- `rule_price_at_sr_zone` fail => veto.
- `rule_fresh_liquidity_present` fail => veto.

Veto tidak menghapus skor mentah; hanya mengunci `action` menjadi `HOLD` dan
menulis alasan veto ke `meta.veto`. Ini menjaga auditabilitas.

## 8. Manajemen Risiko

Selaras dengan modul `app/risk/` yang sudah ada:

- Risiko per posisi: 1 sampai 2 persen dari modal.
- Rasio risk:reward minimal 1:2.
- Position size dihitung dari jarak entry ke stop-loss, bukan dari nominal
  tetap.
- Wajib diuji di backtest dan paper trading sebelum dipertimbangkan untuk
  live. Live trading tetap terkunci default (`LIVE_TRADING_ENABLED=false`).

## 9. Safety Boundary

- Strategi ini tidak melakukan live order. Output hanya JSON signal.
- Tidak ada perubahan pada `app/execution/`, `app/live/`, atau safety gate
  Sprint 20.x sampai 22.
- Dokumen ini tidak mengubah kode; hanya mendefinisikan kontrak.
- Fresh liquidity dan status mitigasi harus dihitung dari data candle
  historis yang tersedia, bukan dari sumber eksternal.

## 10. Rencana Implementasi (Bertahap)

Sprint dijalankan satu per satu. Setiap sprint berhenti untuk verifikasi
sesuai `CLAUDE.md` dan `CLINE_RULES.md`
(`./.venv/bin/python -m compileall app tests` dan
`./.venv/bin/python -m pytest`).

1. **Sprint dokumen (selesai)**: dokumen ini + checkpoint.
2. **Sprint indikator**: implement `swing_points`, `structure_state`,
   `sr_zones`, `liquidity_pools`, `sweep_events` + unit test deterministic.
3. **Sprint strategi**: `app/strategies/liquidity_sr_mtf.py` yang emit
   `StrategyDecision` sesuai kontrak 7.2 + unit test.
4. **Sprint rule scoring**: tambah rule di `configs/rules.json`, dukungan
   veto di `ScoreEngine`, profil bobot baru di `configs/rule_weights.json`,
   unit test veto dan agregasi.
5. **Sprint integrasi realtime**: sambungkan strategi ke `run_realtime.py`
   memakai `MultiTimeframeScanner`; simpan hasil ke `logs/latest_signals.json`
   dan `logs/signals.jsonl` dengan payload backward-compatible.

## 11. Catatan

Dokumen ini adalah kerangka edukasi dan spesifikasi teknis. Bukan saran
finansial. Tidak menggantikan validasi backtest dan paper trading sebelum
setup diaktifkan pada modal nyata.

