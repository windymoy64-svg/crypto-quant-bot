# Checkpoint Sprint 27 - Multi-Agent Trading Pipeline

## Ruang Lingkup

Sprint ini menambahkan empat specialist agent yang bekerja sama sebagai
pipeline advisory di samping paper/live engine yang sudah ada, tanpa
mengubah alur eksekusi existing. Semua fitur baru default `enabled=false`
sehingga tidak ada perubahan perilaku sampai operator mengaktifkannya secara
eksplisit.

Setiap agent punya satu tanggung jawab tunggal, deterministic, dan menulis
output berbentuk dataclass yang bisa di-`to_dict()` untuk audit trail.
Pipeline **tidak** memanggil LLM eksternal; semua "kecerdasan" berasal dari
rule engine deterministic dan statistik dari trade history.

## Files Changed

### Chart Agent (Agent 1 — pembaca chart)

- `app/chart_agent/__init__.py` (baru)
- `app/chart_agent/models.py` (baru) — `ChartReading`, `CandlePatternDetection`,
  `StructureBreak`, `OrderBlock`, `BreakerBlock`, `KeyLevel`, `TechniqueSignal`
- `app/chart_agent/candle_patterns.py` (baru, ~600 baris) — 22 pattern
  detector: doji varian, hammer, shooting star, marubozu, engulfing, harami,
  tweezer, piercing line, dark cloud cover, morning/evening star, three
  soldiers/crows, three inside up/down
- `app/chart_agent/structure_reader.py` (baru) — BOS/CHoCH detection,
  order block, breaker block
- `app/chart_agent/confluence_engine.py` (baru) — regime-adaptive weighting
- `app/chart_agent/agent.py` (baru, ~800 baris) — `ChartReaderAgent`
  orchestrator yang menjalankan 7 teknik (regime, momentum, structure,
  ACR+, candle patterns, liquidity S/R MTF, liquidity pools)

### Learning Agent (Agent 4 — memori & analitik)

- `app/learning_agent/__init__.py` (baru)
- `app/learning_agent/models.py` (baru) — `TradeRecord`, `ChartObservation`,
  `PatternInsight`, `RegimeInsight`, `SymbolInsight`, `LearningInsight`
- `app/learning_agent/store.py` (baru) — `TradeStore` + `ChartObservationStore`
  JSONL persistence
- `app/learning_agent/agent.py` (baru) — `LearningAgent` dengan `learn()`,
  `record_trade()`, `record_chart_reading()`
- `app/learning_agent/feedback.py` (baru) — `build_trade_record()` dan
  `build_trade_record_from_dicts()` (klasifikasi outcome TP/SL/TRAILING/
  BREAKEVEN/INVALIDATION/MANUAL)
- `app/learning_agent/recorder.py` (baru) — `TradeFeedbackRecorder`
  idempotent yang membaca `paper_trades.jsonl` + observations lalu
  menulis ke `learning_journal.jsonl`
- `app/learning_agent/runtime.py` (baru) — `LearningRecorderConfig` +
  `build_recorder_if_enabled()` factory

### Decision Agent (Agent 2 — pengambil keputusan)

- `app/decision_agent/__init__.py` (baru)
- `app/decision_agent/models.py` (baru) — `Decision`, `EntryPlan`, `ExitPlan`
- `app/decision_agent/agent.py` (baru) — `DecisionMakerAgent` dengan
  `decide_entry()` dan `decide_hold()`. Menerapkan 7 gate untuk entry,
  3 trigger untuk exit (bias flip, CHoCH counter, confluence degradation)

### Executor Agent (Agent 3 — eksekusi order)

- `app/executor_agent/__init__.py` (baru)
- `app/executor_agent/models.py` (baru) — `OrderRequest`, `ExecutionResult`,
  `ExecutionPlan`, `ExecutionReport`, `PositionContext`
- `app/executor_agent/agent.py` (baru) — `ExecutorAgent` dengan mode
  dry-run default; live mode wajib adapter, tidak pernah fallback ke
  simulate
- `app/executor_agent/binance_futures_adapter.py` (baru) —
  `BinanceFuturesExecutorAdapter` translate ke Binance Futures via
  `FuturesOrderSubmissionEngine` yang sudah punya safety gate 3 toggle

### Coordinator & Bridge

- `app/agent_pipeline/__init__.py` (baru)
- `app/agent_pipeline/models.py` (baru) — `ScannerCandidate`, `PipelineResult`
- `app/agent_pipeline/coordinator.py` (baru) — `AgentPipelineCoordinator`
- `app/agent_pipeline/bridge.py` (baru) — `run_pipeline_bridge()` untuk
  dipanggil dari `run_realtime.py`

### Dashboard

- `app/dashboard/routes/agent.py` (baru) — 3 endpoint read-only:
  `/api/agent/pipeline`, `/api/agent/learning`, `/api/agent/observations`
- `app/dashboard/routes/__init__.py` — tambah `agent` ke `__all__`
- `app/dashboard/app.py` — daftarkan router `agent` di `create_app()`

### Runtime integration

- `run_realtime.py` — tambah dua hook opsional di akhir `run_once()`:
  1. `run_pipeline_bridge()` bila `agent_pipeline.enabled=true`
  2. `TradeFeedbackRecorder.process_new_closures()` bila
     `learning_recorder.enabled=true`
  Kedua hook default OFF; tidak mengubah return schema existing (hanya
  menambah field `agent_pipeline` dan `learning_recorder`).

### Tests

100 test baru dibagi ke 10 file: `test_chart_agent.py` (22),
`test_learning_agent.py` (8), `test_learning_feedback.py` (9),
`test_learning_runtime.py` (8), `test_decision_agent.py` (11),
`test_executor_agent.py` (11), `test_agent_pipeline.py` (6),
`test_agent_pipeline_bridge.py` (7), `test_dashboard_agent_routes.py` (9),
`test_binance_futures_adapter.py` (9). **Total suite: 372 tests hijau.**

## Highlight Keputusan Desain

### Prinsip pemisahan tanggung jawab

- **Chart Agent** tidak menghasilkan BUY/SELL. Ia hanya menerbitkan
  `ChartReading` (data mentah + statistik). Bahkan bila confluence 100%
  bullish, agent tetap tidak memutuskan; keputusan menjadi tugas
  Decision Agent.
- **Learning Agent** tidak menghasilkan action. Ia mengumpulkan observation
  dari Chart Agent + hasil trade dari paper engine, lalu memproduksi
  `LearningInsight` statistik (hot/cold pattern, best/worst regime,
  kalibrasi confluence).
- **Decision Agent** adalah satu-satunya yang boleh mengeluarkan
  `ENTRY_BUY/ENTRY_SELL/HOLD/EXIT/SKIP`. Ia menerima `ChartReading` +
  `LearningInsight`, tapi tidak menyentuh exchange.
- **Executor Agent** tidak berpikir. Ia hanya menerjemahkan `Decision`
  ke `OrderRequest` dan mengirim via adapter. Tanpa `Decision` yang valid,
  tidak ada order yang keluar.

### Safety guardrails yang tetap dijaga

- Executor `live=True` tanpa adapter → semua order REJECTED. Tidak ada
  fallback ke simulasi supaya operator sadar konfigurasi belum lengkap.
- Coordinator `execute_decisions=False` default. Pipeline murni advisory
  sampai operator eksplisit menyalakan enforcement.
- Bridge `enabled=False` default. `run_realtime.py` tidak berubah
  perilakunya sampai block `agent_pipeline` di `configs/realtime.json`
  ditambahkan.
- Trade recorder `enabled=False` default dan idempotent via checkpoint
  file. Rerun tidak duplikasi record.
- Binance Futures adapter tetap lewat `FuturesLiveSafetyGate` 3-toggle
  (`enabled` + `dry_run` + `confirm_live`). Sprint ini tidak melonggarkan
  safety gate yang sudah ada.

### Kalibrasi Decision Agent oleh Learning Agent

Decision Agent menggunakan `LearningInsight` untuk tiga penyesuaian
deterministic:

1. `min_confluence_recommended` menaikkan threshold minimum confluence
   berdasarkan winrate historis di regime yang sama.
2. `hot_patterns` (winrate >= 65%, minimal 5 sampel) memberi boost +8
   pada confidence score.
3. `cold_patterns` (winrate < 40%) memberi penalty -12; kombinasi
   dengan worst regime menambah -10 lagi.

Semua adjustment tercatat di `Decision.learning_reasons` untuk audit.

### Klasifikasi outcome oleh trade recorder

`TradeFeedbackRecorder.process_new_closures()` mencocokkan setiap
`type=closed` di `paper_trades.jsonl` dengan observation ENTRY_CANDIDATE
terbaru sebelum `opened_at` position (dan POSITION_MONITOR terbaru
sebelum `closed_at`). Klasifikasi outcome berdasarkan `close_reason`:

| Substring di close_reason | Outcome |
|---|---|
| `TRAIL` | `TRAILING` |
| `STOP`, `SL`, `STOP_LOSS` | `SL` |
| `TAKE_PROFIT`, prefix `TP` | `TP` |
| `INVALID`, `CISD`, `CHOCH` | `INVALIDATION` |
| lainnya + PnL ~0 | `BREAKEVEN` |
| lainnya | `MANUAL` |

## Konfigurasi

Tambahkan ke `configs/realtime.json` untuk mengaktifkan pipeline dalam
mode advisory (tidak ada order yang benar-benar dikirim):

```json
{
  "agent_pipeline": {
    "enabled": true,
    "execute_decisions": false,
    "min_scanner_confidence": 90.0,
    "htf_timeframe": "4h",
    "mtf_timeframe": "1h",
    "ltf_timeframe": "15m",
    "htf_limit": 200,
    "mtf_limit": 200,
    "ltf_limit": 200,
    "output_path": "logs/agent_pipeline.json",
    "max_entry_symbols": 5,
    "monitor_positions": true
  },
  "learning_recorder": {
    "enabled": true,
    "trade_store_path": "data/learning_journal.jsonl",
    "observation_store_path": "data/chart_observations.jsonl",
    "checkpoint_path": "data/learning_recorder_checkpoint.json"
  }
}
```

## Dashboard endpoints

Setelah pipeline aktif, endpoint berikut tersedia (semua di belakang
`require_api_key`):

- `GET /api/agent/pipeline` — snapshot terakhir dari
  `logs/agent_pipeline.json`
- `GET /api/agent/learning` — hasil `LearningAgent.learn()` real-time
  (total_trades, hot/cold patterns, per-regime insight, kalibrasi
  confluence)
- `GET /api/agent/observations?limit=20&stage=ENTRY_CANDIDATE&symbol=BTC/USDT`
  — recent observations Chart Agent dengan filter opsional

## Verification

- `.venv/bin/python -m compileall app tests` — clean
- `.venv/bin/python -m pytest --ignore=tests/test_dashboard_futures_route.py
  --ignore=tests/test_klines_api.py --ignore=tests/test_settings_api.py`
  — **372 passed** (3 file di-ignore karena membutuhkan `httpx2` yang
  tidak terpasang di environment ini; baseline yang sama seperti sprint
  sebelumnya)

## Yang tidak dilakukan (sengaja)

- Tidak menyentuh `scoring/engine.py`, `signals/builder.py`, atau modul
  strategi existing. Pipeline berjalan sebagai layer terpisah, tidak
  menggantikan.
- Tidak mengubah paper trading engine (`app/paper/realtime_engine.py`).
  Trade feedback recorder membaca event log yang sudah ditulis paper
  engine.
- Tidak mengubah safety gate Binance Futures. Adapter hanya membungkus
  `FuturesOrderSubmissionEngine` yang sudah punya 3-toggle gate.
- Tidak menambahkan LLM inference. Semua "learning" murni statistik
  frekuensi dari trade history.
- Tidak mengaktifkan pipeline di config default. Operator harus opt-in
  eksplisit setelah review dokumen ini.
