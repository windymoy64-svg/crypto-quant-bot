# PROJECT_CONTEXT — Crypto Quant Bot

> Konteks teknis tetap untuk agent/programmer.  
> Update bila ada keputusan arsitektur baru yang mengubah cara kerja bot.

**Project path:** `/opt/crypto-quant-bot`  
**Bahasa komunikasi kerja:** Indonesia  

---

## Tujuan project

Membangun **bot quant crypto deterministik** dengan:

1. **Scanner market** (public data) → signal JSON  
2. **Rule engine / multi-agent** (chart, learning, decision, executor)  
3. **Risk management** (size, exposure, drawdown, min RR)  
4. **Paper trading** realtime sebagai validasi  
5. **Dashboard read-only** untuk monitoring  
6. **Live execution** hanya setelah paper + risk stabil (default **OFF**)

Prinsip: **aman dulu** — tidak ada withdrawal key, live default mati, dry-run executor.

---

## Stack teknologi

| Area | Teknologi |
|------|-----------|
| Bahasa | Python 3.11+ (venv di `.venv`) |
| API / dashboard | FastAPI, Uvicorn, Jinja2 templates, static JS/CSS |
| Data market | Binance/OKX public HTTP; opsional `ccxt` |
| Indikator / struktur | Modul internal `app/indicators`, chart agent, ACR+, liquidity/SR MTF |
| Persistensi | JSON / JSONL di `logs/`, `data/` |
| Tes | `pytest` |
| Deploy VPS | systemd unit di `deploy/` |

Dependency utama: lihat `requirements.txt` (FastAPI, Uvicorn, NumPy, dll.).

---

## Struktur folder (ringkas)

```text
/opt/crypto-quant-bot
├── app/
│   ├── agent_pipeline/     # Coordinator + bridge multi-agent
│   ├── chart_agent/        # Chart reading + LLM proposal (opsional)
│   ├── decision_agent/     # ENTRY/HOLD/EXIT/SKIP + EntryPlan
│   ├── learning_agent/     # Journal, insight, policy patch, LLM insights
│   ├── executor_agent/     # Dry-run / live adapters
│   ├── paper/              # Paper engine (batch) + realtime_engine
│   ├── risk/               # RiskManager, RR validator, sizing
│   ├── market/             # Scanner, data service
│   ├── signals/            # build_signal / build_short_signal
│   ├── strategies/         # ACR+, liquidity SR, position manager
│   ├── dashboard/          # FastAPI routes, static, templates
│   ├── exchange/           # Public HTTP + futures helpers
│   └── settings/           # LLM / exchange preferences (non-secret defaults)
├── configs/                # realtime, paper, market_scan, rules, ...
├── deploy/                 # systemd unit files
├── docs/                   # checkpoint & audit notes
├── logs/                   # signals, paper state/trades, agent_pipeline
├── data/                   # journal, observations, llm insights
├── tests/
├── run_realtime.py         # Loop scanner + paper + agent
├── run_api.py              # Dashboard/API
├── TASKS.md
├── PROJECT_CONTEXT.md
├── VPS_CONTEXT.md
└── .clinerules
```

---

## Alur runtime (konseptual)

```text
Market public → Scanner / signals
      → Agent pipeline (chart → learning → decision → executor dry-run)
      → Paper realtime engine (open/partial/close virtual)
      → logs/*.json(l)
      → Dashboard API (read-only) → UI
```

Live path ada tetapi **default disabled** (`live_execution_enabled`, `allow_live_orders`).

---

## Keputusan teknis penting

### Trading & risk
- **Min RR desain = 1:2** (`RiskManager.min_risk_reward`, strategi ACR/liquidity, Decision `TP1_R=2`).
- **Celan arsitektur:** `RealtimePaperTradingEngine` historis **tidak** memanggil `RiskManager` → open bisa RR &lt; 2.  
  Arah perbaikan: normalisasi TP ke 2R dan/atau gate di pintu open (lihat `TASKS.md`).
- SL struktural + batas `MIN_SL_PCT` / `MAX_SL_PCT` di decision agent.
- TP ladder partial (default fraksi ~30/30/40) + trailing setelah partial **profitable**.
- TP **harus** di sisi profit (LONG di atas entry; SHORT di bawah) — disanitasi di paper realtime.

### Multi-agent
- Chart: reading only (bias, confluence, regime, levels).  
- Learning: statistik + optional LLM policy patch (bounded/clamped).  
- Decision: satu-satunya yang mengeluarkan action trading.  
- Executor: default dry-run; live butuh adapter + flag eksplisit.
- Pipeline config: `configs/realtime.json` → blok `agent_pipeline`.

### Paper
- State: `logs/paper_state.json`  
- Events: `logs/paper_trades.jsonl`  
- Config path: `configs/paper_trading.json` (diacu realtime)

### Dashboard
- FastAPI + static `dashboard.js` / `dashboard.css`  
- Cache-bust asset via `asset_version` (mtime)  
- LLM Insight History: output dinormalisasi dari `policy_patch.human_summary`; payload di-slim (tanpa journal snapshot).

### Keamanan
- Secret hanya di `.env` (tidak di-commit, tidak ditulis ke markdown konteks).  
- API default `127.0.0.1`; akses luar butuh key + firewall / tunnel.  
- Exchange API: withdrawal OFF; mulai read-only.

---

## File “sumber kebenaran” per domain

| Domain | File utama |
|--------|------------|
| Loop realtime | `run_realtime.py`, `configs/realtime.json` |
| Paper open/exit | `app/paper/realtime_engine.py` |
| Risk formal | `app/risk/manager.py`, `app/risk/takeprofit.py` |
| Decision / RR plan | `app/decision_agent/agent.py` |
| Agent wire | `app/agent_pipeline/coordinator.py`, `bridge.py` |
| Scanner | `app/market/scanner.py`, `configs/market_scan.json` |
| Dashboard agent | `app/dashboard/routes/agent.py`, `static/dashboard.js` |
| Status kerja | `TASKS.md`, `STATUS.md` |

---

## Konvensi pengembangan

- Tes: `.venv/bin/python -m pytest …`  
- Jangan ubah layout mobile kecuali diminta (CSS desktop hanya di `min-width: 641px`).  
- Setelah ubah kode runtime Python → restart proses/service terkait.  
- Setelah ubah static JS/CSS → hard refresh browser.  
- Jangan commit secret; jangan log API key.

---

## Referensi dokumen lain

- `STATUS.md` — history batch pengerjaan  
- `DEPLOY_VPS.md` — panduan deploy  
- `TASKS.md` — todo & next step operasional  
- `VPS_CONTEXT.md` — path & command server  
- `.clinerules` — aturan agent
