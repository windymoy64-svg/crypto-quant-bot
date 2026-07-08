# Roadmap

Dokumen ini menjadi pegangan sprint berikutnya. Status saat ini: Sprint 23 (Strategy Validation Research Layer) selesai. Final Release (Sprint 22 + hardening) sudah live sebagai baseline production. Tidak ada sprint yang dijalankan otomatis; setiap sprint berikut harus di-scope dan disetujui manual sebelum diimplementasikan.

## Prinsip Roadmap

- Bot tetap deterministic: LLM tidak mengambil keputusan buy/sell.
- Semua keputusan trading keluar sebagai JSON signal yang bisa diaudit.
- Live trading default terkunci (`LIVE_TRADING_ENABLED=false`, `LIVE_TRADING_DRY_RUN=true`) sampai paper trading, risk guard, exchange, dan account preflight tervalidasi ulang di lingkungan target.
- Fitur baru harus menjaga backward compatibility untuk command, artifact, dan payload JSON yang sudah ada.
- Setiap sprint hanya menyelesaikan satu area utama.
- Sprint dokumentasi/housekeeping tidak menambah kode baru; hanya sinkronisasi checkpoint dan roadmap.

## Selesai

1. Sprint 01 - fondasi project, struktur folder, config awal, dan sample data.
2. Sprint 02 - indicator dasar, strategy deterministic, rule engine, signal builder, dan risk sizing awal.
3. Sprint 03 - market scanner publik dengan fallback sample data.
4. Sprint 04 - realtime scanner, log signal terbaru, dan riwayat JSONL.
5. Sprint 05 - paper trading realtime dengan state virtual dan event log.
6. Sprint 06 - API internal untuk health, status, latest signals, dan paper state.
7. Sprint 07 - guard live trading, konfigurasi VPS, dan dry-run execution lock.
8. Sprint 08 - market regime, dynamic rule weights, multi-timeframe scan, rule explanation, dan feature importance.
9. Sprint 09 - ranking portofolio dan kandidat trade lintas symbol.
10. Sprint 10 - backtest engine deterministic dengan trade log, equity curve, metric, dan report.
11. Sprint 11 - execution model realistic (order type, fee, slippage, latency, fill).
12. Sprint 12 - risk management module (position size, SL, TP, exposure, drawdown, volatility).
13. Sprint 13 - portfolio module (balance, position, exposure, performance, account).
14. Sprint 14 - Binance private API client (auth, signer, market/account endpoints).
15. Sprint 15 - Binance websocket stream (subscription, heartbeat, reconnect).
16. Sprint 16 - event bus, publisher, subscriber, dan integrasi backtest/paper/live simulator.
17. Sprint 17 - paper trading engine end-to-end (account, orders, fills, positions, persistence).
18. Sprint 18 - analytics dan reports (statistics, journal, equity, performance, attribution).
19. Sprint 19 - dashboard API untuk operator dan portfolio view.
20. Sprint 20.5 / 20.75 / 20.9 - exchange rules, account preflight, order intent, safety gates.
21. Sprint 21 - live order submission engine, monitor, dan konfigurasi live.
22. Sprint 22 - order lifecycle store, portfolio reconciliation, portfolio sync, telegram control center read-only, monitoring health.
23. Final Release - hardening production (Dockerfile, docker-compose, nginx, logging, `.env`, guide `docs/PRODUCTION_READY.md`, audit `docs/PRODUCTION_AUDIT.md`).
24. Sprint 23 - strategy validation research layer (`app/research/*`, `run_research.py`, laporan JSON/HTML/CSV, dokumentasi `docs/STRATEGY_VALIDATION.md`, checkpoint `docs/CHECKPOINT_SPRINT_23_RESEARCH.md`).

## Baseline Verifikasi Terkini

- `python -m compileall app tests` bersih.
- `python -m pytest` hijau, 66/66.
- Live trading tetap terkunci; research layer bersifat read-only.

## Kandidat Sprint Berikutnya

Setiap kandidat berikut hanya untuk brainstorm. Tidak boleh diimplementasikan tanpa scope dan persetujuan eksplisit.

### Kandidat A - Batch Backtest Runner

Ruang lingkup:

- CLI batch backtest lintas symbol dan timeframe.
- Simpan metric ringkas (return, drawdown, win rate, exposure, jumlah trade) per kombinasi.
- Artifact hasil kompatibel dengan Sprint 23 `logs/backtests/*.json` supaya bisa langsung dianalisa research layer.
- Tidak menyentuh live execution atau paper engine.

Kriteria selesai:

- Runner deterministic dengan seed dan config file.
- Artifact JSON per kombinasi + satu ringkasan agregat.
- Test coverage untuk config parsing, runner orchestration, dan agregasi.

### Kandidat B - Operational Alerting

Ruang lingkup:

- Alert Telegram untuk drawdown melewati threshold, consecutive losses, stale data feed, dan gagal reconnect websocket.
- Tetap read-only terhadap eksekusi. Alerting hanya membaca artifact dan event bus yang sudah ada.
- Rate limit dan dedup alert supaya tidak spam.

Kriteria selesai:

- Config threshold di `configs/alerting.json`.
- Test unit untuk aturan alert, dedup, dan formatter pesan.
- Dokumentasi command Telegram tidak berubah (hanya notifikasi outbound).

### Kandidat C - Unified CLI Entrypoint

Ruang lingkup:

- Satu entrypoint (mis. `python -m app` atau `bot`) untuk `scan`, `paper`, `backtest`, `research`, `api`, `realtime`.
- `run_*.py` yang ada tetap bisa dipanggil untuk backward compatibility.
- Tidak mengubah business logic; hanya orchestrator argparse/typer.

Kriteria selesai:

- Test coverage untuk dispatch tiap sub-command.
- Dokumentasi `docs/CLI.md` yang menjelaskan sub-command dan opsi.
- Tidak ada perubahan pada payload, artifact, atau signal.

### Kandidat D - Reproducible Build Lock

Ruang lingkup:

- Regenerasi `requirements-lock.txt` versi terbaru.
- Pin base image Docker via digest.
- Tambah `pip-tools` atau workflow serupa untuk lock deterministic di CI/dokumentasi lokal.

Kriteria selesai:

- Dokumentasi `docs/DEPENDENCY_LOCK.md` menjelaskan cara refresh lock.
- Tidak ada perubahan versi dependency runtime yang belum diuji manual.

## Backlog

- Tambahkan coverage rule sampai 100+ rule.
- Tambahkan lebih banyak exchange publik dengan fallback yang seragam.
- Tambahkan Shadow Account untuk membandingkan ideal signal dan eksekusi nyata.
- Tambahkan report harian untuk signal, paper PnL, dan anomali data.
- Tambahkan tail-style bounded reader untuk JSONL dashboard (dari PRODUCTION_AUDIT medium priority).
- Tambahkan retry/backoff terpusat untuk `app/exchange/public_http_client.py`.
- Tambahkan websocket auth query token dan nginx hardening tambahan.
- Tambahkan CI pipeline dengan `python -m compileall app tests` dan `pytest` sebagai gate wajib.
- Review kembali daftar `CHECKPOINT_*.md`: rapikan atau pindah ke `docs/history/` bila terlalu banyak noise.
