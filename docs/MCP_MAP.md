# MCP Map — Crypto Quant Bot

Dokumen ini memetakan **mana yang jadi MCP server**, **mana yang tetap internal**,
dan **urutan implementasi paling aman** untuk repo `/opt/crypto-quant-bot`.

Status: **MCP-1 Ops MCP read-only DONE** (`app/mcp/`).
Fase berikutnya masih desain; lihat urutan di bawah.

Prinsip tetap berlaku (lihat `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`,
`docs-vibe-trading.md`):

- Bot **deterministic**: LLM **tidak** memilih BUY/SELL.
- Semua keputusan trading keluar sebagai **JSON signal** yang bisa diaudit.
- Live trading default **terkunci**.
- MCP = **lapisan konektor data/aksi**, bukan otak trading.
- Agent existing (`chart_agent`, `decision_agent`, `learning_agent`,
  `executor_agent`) **bukan** MCP server; mereka konsumen internal bot.

---

## 1. Ringkasan arsitektur target

```text
 Operator AI (Cline / Claude)          Runtime bot (otoritas trading)
            │                                    │
            ▼                                    ▼
   ┌─────────────────┐                 Scanner → Score → Signal
   │  MCP LAYER      │                 Risk → Paper / Live
   │  (ops + data)   │                 Agent pipeline (advisory)
   └────────┬────────┘                           │
            │                                    │
            └──────────── shared services ───────┘
                 (MarketDataService, paper state,
                  journal, dashboard services)
```

**Aturan keras:**

| Boleh lewat MCP | Tidak boleh lewat MCP |
|---|---|
| Baca status, portfolio, signal, journal | Mengganti `ScoreEngine` / rule engine |
| Baca candle/ticker (wrap existing) | LLM place order langsung ke exchange |
| Trigger backtest offline / research | Bypass safety gate / risk module |
| Notifikasi ops (setelah Fase 2+) | Mutasi credentials / kill live tanpa guard |

AI agent **tidak** bicara langsung ke Binance/Bitunix.
Kalau butuh data/aksi eksternal: **AI → MCP → service internal / exchange adapter**.
Runtime bot boleh tetap panggil service internal **tanpa** MCP (lebih cepat,
tanpa hop ekstra untuk hot path).


---

## 2. Peta per folder `app/`

### 2.1 TETAP INTERNAL (core engine — jangan di-MCP-kan)

| Folder / modul | Alasan |
|---|---|
| `app/indicators/` | Pure function, deterministic, hot path |
| `app/features/` | Feature builder dari candle |
| `app/strategies/` | Strategy decision (Liquidity S/R MTF, dll.) |
| `app/scoring/` | `ScoreEngine`, dynamic weights |
| `app/signals/` | Signal JSON builder |
| `app/risk/` | Position size, SL/TP, exposure, drawdown |
| `app/market/regime.py` | Market regime engine |
| `app/market/multi_timeframe.py` | Agregasi MTF |
| `app/market/scanner.py` | Scanner logic (bukan fetch mentah) |
| `app/chart_agent/` | Chart reading deterministic |
| `app/decision_agent/` | Keputusan advisory rule-based |
| `app/learning_agent/` | Insight dari journal (compute lokal) |
| `app/executor_agent/` | Dry-run / live adapter + safety gate |
| `app/agent_pipeline/` | Coordinator pipeline |
| `app/paper/` | Paper engine state machine |
| `app/live/` | Live lifecycle, intent, gates |
| `app/execution/` | Live execution path (terkunci default) |

**Intinya:** otak trading + safety path **lokal, cepat, auditable**.
MCP tidak boleh berisi logika BUY/SELL.

### 2.2 WRAP / EXPOSE VIA MCP (konektor & ops)

| Folder existing | Peran MCP | Catatan |
|---|---|---|
| `app/market/data_service.py` | **Market MCP** (thin wrap) | Pintu OHLCV/ticker yang sudah ada |
| `app/exchange/` | **Market MCP** + nanti **Execution MCP** | Connector Binance/Bitunix/public HTTP |
| `app/portfolio/` | **Portfolio / Ops MCP** | Equity, exposure, sync |
| `app/paper/` (state files) | **Ops MCP** read-only | `logs/paper_state.json` |
| `app/analytics/` | **Ops MCP** | PnL, performance |
| `app/backtest/` | **Backtest MCP** (Fase 2) | Trigger run + baca artifact |
| `app/research/` | **Research MCP** (opsional) | Bridge riset, bukan decision |
| `app/dashboard/services.py` | **Ops MCP** reuse | Banyak endpoint read-only sudah siap |
| `app/dashboard/routes/agent.py` | **Ops MCP** | pipeline / learning / observations |
| `app/telegram/` | **Notification MCP** (Fase 3) | Reporter + control center |
| `app/monitoring/` | **Monitoring MCP** (Fase 3) | Health, latency |
| `app/database/` / `data/*.jsonl` | **Data MCP** (ringan) | Journal, observations — mulai file-based |
| `logs/*.json` | **Ops MCP resources** | `latest_signals`, `agent_pipeline`, paper state |

### 2.3 JANGAN dipecah jadi monorepo 10 package dulu

Usulan “`crypto-quant-platform/` + 10 MCP package terpisah + k8s” **terlalu besar**
untuk tahap sekarang. Repo ini production single-bot di VPS.

**Rekomendasi layout di dalam repo yang sama:**

```text
crypto-quant-bot/                    # tetap satu repo
  app/                               # core (tidak diubah peran)
    mcp/                             # BARU — satu package MCP dulu
      __init__.py
      server.py                      # entry: python -m app.mcp.server
      guards.py                      # no live order, path allowlist
      tools/
        status.py
        portfolio.py
        positions.py
        signals.py
        journal.py
        pipeline.py
        market_readonly.py           # Fase 1b
      resources/
        paper_state.py
        latest_signals.py
  docs/MCP_MAP.md                    # dokumen ini
```

Split multi-server (`market-mcp`, `execution-mcp`, …) **hanya** jika:

1. Satu server jadi terlalu besar / permission boundary beda, **atau**
2. Client MCP beda-beda butuh subset tools, **atau**
3. Tim/process isolation memang dibutuhkan.

Sampai itu terjadi: **satu MCP server read-only** sudah cukup.


---

## 3. Katalog MCP server (target jangka menengah)

### A. Ops MCP ⭐⭐⭐⭐⭐ (implement dulu)

**Tujuan:** AI operator (Cline) bisa debug & monitor tanpa copy-paste log.

| Tool | Sumber existing | Mutasi? |
|---|---|---|
| `get_bot_status` | health / realtime state | Read |
| `get_portfolio` | portfolio + multi-portfolio routes | Read |
| `get_pnl` | analytics | Read |
| `get_open_positions` | paper state / portfolio sync | Read |
| `get_latest_signals` | `logs/latest_signals.json` | Read |
| `get_agent_pipeline` | `logs/agent_pipeline.json` | Read |
| `get_learning_insights` | learning agent + journal | Read |
| `get_chart_observations` | `data/chart_observations.jsonl` | Read |
| `get_trade_journal` | `data/learning_journal.jsonl` / analytics journal | Read |

**Resources (opsional):** `paper://state`, `signals://latest`, `pipeline://latest`.

### B. Market MCP ⭐⭐⭐⭐ (thin wrap, setelah Ops stabil)

| Tool | Sumber | Mutasi? |
|---|---|---|
| `get_candles(symbol, tf, limit)` | `MarketDataService.fetch_ohlcv` | Read |
| `get_ticker(symbol)` | `MarketDataService.fetch_ticker` | Read |
| `get_data_source(symbol, tf)` | field `source` di `MarketDataResult` | Read |

**Jangan** reimplement client Binance/Bitunix di MCP.
**Jangan** pindahkan scanner/regime/MTF ke MCP.

Nanti (bukan sekarang): orderbook, funding, OI — hanya jika ada adapter
internal dulu, baru di-expose.

### C. Portfolio / Paper MCP

Bisa digabung ke Ops MCP Fase 1. Split terpisah hanya jika permission beda.

| Tool | Sumber |
|---|---|
| `equity`, `balance`, `exposure` | portfolio + paper |
| `open_positions`, `closed_summary` | paper / live sync |
| `daily_pnl`, `drawdown` | analytics |

### D. Backtest / Research MCP (Fase 2)

| Tool | Sumber | Guard |
|---|---|---|
| `run_backtest(config)` | `app/backtest`, `run_backtest.py` | Offline only, timeout, no live |
| `list_backtest_artifacts` | `logs/backtests/` | Read |
| `get_research_report` | `app/research` | Read |

### E. Execution MCP ⚠️ (Fase paling akhir / mungkin tidak pernah untuk AI)

| Tool | Guard wajib |
|---|---|
| `place_order` / `cancel` / `close` | Default **disabled** |
| `set_leverage` | Explicit env + config + audit log |
| `get_balance` / `get_positions` (live) | Read OK lebih dulu |

**Kebijakan project:**

```text
AI  ──X──>  Exchange place_order
AI  ──✓──>  Ops MCP (read)
Bot engine ──✓──>  executor_agent + safety gate ──> Exchange
```

Kalau suatu hari Execution MCP ada: tool write harus memanggil
**jalur yang sama** dengan `executor_agent` + risk gate, bukan API exchange
langsung. Default: `LIVE_TRADING_ENABLED=false`.

### F. Research / News MCP (opsional, belakangan)

Hanya jika benar-benar ada sumber (Fear&Greed, CryptoPanic, dll.).
Jangan scrap TradingView untuk decision path.

### G. Memory / Vector MCP (opsional, belakangan)

Learning journal JSONL dulu sudah cukup. Vector store hanya jika ada
kebutuhan similarity search yang terukur.

### H. Monitoring + Notification MCP (Fase 3)

Wrap `app/monitoring` + `app/telegram` yang sudah ada.
Alert tetap **read-only terhadap eksekusi** (selaras kandidat roadmap
Operational Alerting).

---

## 4. Matriks: Agent existing vs MCP

| Agent / komponen | Peran | Pakai MCP? |
|---|---|---|
| Chart Agent | Baca OHLCV → `ChartReading` | **Tidak** di hot path; data dari `MarketDataService` langsung |
| Learning Agent | Journal + insight | Compute lokal; MCP hanya **expose** insight ke operator AI |
| Decision Agent | ENTRY/HOLD/SKIP dari reading+insight | Internal |
| Executor Agent | Dry-run / live via adapter | Internal + safety gate |
| Operator AI (Cline) | Tanya status, debug, riset | **Ya** — konsumen utama Ops MCP |
| Dashboard UI | Operator manusia | Tetap FastAPI; MCP bukan pengganti UI |
| Telegram | Notifikasi + control center | Bisa di-wrap Notification MCP nanti |

---

## 5. Urutan implementasi (sprint-safe)

Ikuti prinsip roadmap: **satu area utama per sprint**, backward compatible.

### Sprint MCP-1 — Ops MCP read-only (WAJIB dulu)

**Scope:**

- Package `app/mcp/` + Python MCP SDK di `.venv`
- Tools: status, portfolio, pnl, positions, signals, pipeline, journal, learning
- Guards: tidak ada write, tidak ada order, path allowlist di bawah project root
- Config Cline/Claude Desktop contoh di docs
- Unit test: tool return shape + file missing degrade graceful

**Out of scope:** execution, news, monorepo split, ubah scanner.

**Done when:**

- `./.venv/bin/python -m app.mcp.server` start via stdio
- Cline bisa panggil `get_bot_status` / `get_latest_signals` dengan data nyata
- Pytest MCP hijau; suite existing tidak regres

### Sprint MCP-2 — Market MCP thin wrap

**Scope:**

- `get_candles` / `get_ticker` wrap `MarketDataService`
- Hormati cache TTL existing; opsi `force_refresh` terbatas
- Tidak mengubah fallback chain Binance → ccxt → public HTTP → sample

**Out of scope:** funding/OI/orderbook baru, pindah hot path scanner ke MCP.

### Sprint MCP-3 — Backtest / Research trigger

**Scope:**

- `run_backtest` + list/read artifacts
- Timeout + working directory lock + no network live trading

### Sprint MCP-4 — Monitoring + Notification (ops)

**Scope:**

- Health tools + Telegram notify wrap (rate limit)
- Tetap tidak membuka live order dari AI

### Sprint MCP-N — Execution (hanya jika disetujui eksplisit)

**Scope minimal:**

- Read live balance/positions dulu
- Write tools default off + dual confirmation + audit JSONL
- Wajib lewat `executor_agent` + existing safety gates

---

## 6. Yang tidak dilakukan (anti-pattern)

| Anti-pattern | Kenapa ditolak |
|---|---|
| LLM → Binance `place_order` via MCP | Langgar determinism + safety |
| Pindah `scoring` / `risk` ke MCP | Hot path jadi lambat & non-auditable |
| 10 MCP package + k8s di awal | Over-engineering; VPS single bot |
| Clone “trading MCP” random GitHub | Coupling & security tak terkontrol |
| Chart Agent scrap TradingView | Bukan sumber data bot; data = exchange OHLCV |
| MCP sebagai pengganti FastAPI dashboard | Dashboard untuk manusia; MCP untuk AI client |

---

## 7. Kontrak teknis minimal (Fase 1)

### Entry point

```bash
/opt/crypto-quant-bot/.venv/bin/python -m app.mcp.server
```

### Contoh config client (Cline / Claude Desktop)

```json
{
  "mcpServers": {
    "crypto-quant-bot": {
      "command": "/opt/crypto-quant-bot/.venv/bin/python",
      "args": ["-m", "app.mcp.server"],
      "cwd": "/opt/crypto-quant-bot"
    }
  }
}
```

### Guards (`app/mcp/guards.py`)

1. **Write deny-list default:** tidak ada tool yang menulis order/credentials.
2. **Path allowlist:** hanya `logs/`, `data/`, `configs/` (read), artifact backtest.
3. **Exchange write:** selalu false di Fase 1–3.
4. **Error shape:** tool gagal → JSON `{ "ok": false, "error": "..." }`, jangan crash server.
5. **Secrets:** jangan return API key / secret di response tool.

### Dependency

- Pakai official Python SDK: package `mcp`
- Install hanya di project venv: `./.venv/bin/pip install mcp`
- Jangan jadikan MCP required untuk `run_realtime.py` / paper / live

---

## 8. Mapping usulan “AI Quant Platform” → realitas repo

| Usulan vision | Keputusan di repo ini |
|---|---|
| 10 MCP terpisah sekarang | **Tidak** — 1 Ops MCP dulu |
| Market Agents bicara MCP | Runtime agents tetap internal; MCP untuk operator AI |
| Database MCP wajib | Mulai **file/JSONL + SQLite existing**; Postgres MCP nanti jika DB real dipakai luas |
| Learning MCP | Logic tetap di `learning_agent`; expose insight via Ops tools |
| Memory MCP | Deferred; journal JSONL dulu |
| Rename monorepo `crypto-quant-platform` | **Tidak** di sprint MCP; rename terpisah & mahal |
| `MarketDataService` → only via MCP | **Tidak** untuk hot path; optional dual-path nanti |

---

## 9. Checklist keputusan (untuk approve sprint)

Sebelum coding MCP-1, pastikan disetujui:

- [ ] MCP **read-only ops** dulu, bukan execution
- [ ] Satu package `app/mcp/` di repo existing
- [ ] Core `scoring/signals/risk/paper/live` tidak diubah peran
- [ ] Agent pipeline tetap advisory / internal
- [ ] Live trading tetap terkunci
- [ ] Test + docs checkpoint setelah implementasi

---

## 10. Next step yang disarankan

1. **Approve Sprint MCP-1** (Ops MCP read-only) dari checklist di atas.
2. Implement `app/mcp/server.py` + tools status/portfolio/signals/pipeline/journal.
3. Daftarkan di Cline, verifikasi end-to-end di VPS.
4. Baru pertimbangkan MCP-2 (market readonly wrap).

Dokumen terkait:

- `docs/ARCHITECTURE.md` — alur deterministic
- `docs/ROADMAP.md` — prinsip sprint
- `docs-vibe-trading.md` — LLM tidak pilih BUY/SELL
- `docs/CHECKPOINT_SPRINT_27_MULTI_AGENT.md` — agent advisory existing


