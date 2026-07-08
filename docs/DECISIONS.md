# Decisions

Dokumen ini mencatat keputusan arsitektur yang sudah berlaku sampai Sprint 08.

## ADR-001 - Rule Engine Deterministic

Status: accepted.

Keputusan:

- Keputusan buy/sell/watch/skip dibuat oleh rule engine deterministic.
- Input yang sama harus menghasilkan output yang sama.
- LLM tidak dipakai sebagai decision maker trading.

Alasan:

- Trading membutuhkan audit trail dan reproducibility.
- Rule deterministic lebih mudah diuji dan dijelaskan.

Konsekuensi:

- Semua rule harus ditulis eksplisit.
- ML atau LLM hanya boleh membantu riset, optimasi, dan report.

## ADR-002 - JSON Signal Sebagai Boundary

Status: accepted.

Keputusan:

- Semua keputusan keluar sebagai JSON signal.
- Paper engine, API, dan live execution membaca signal, bukan menghitung ulang keputusan sendiri.

Alasan:

- Memisahkan analysis engine dan execution engine.
- Memudahkan audit, replay, dan debugging.

Konsekuensi:

- Schema signal harus dijaga backward compatible.
- Field penting seperti action, confidence, score, risk, dan rule meta harus tetap tersedia.

## ADR-003 - Fallback Data Wajib Ada

Status: accepted.

Keputusan:

- Scanner boleh memakai data exchange publik.
- Jika dependency atau koneksi gagal, pipeline memakai sample data.

Alasan:

- Development dan test tidak boleh berhenti hanya karena network/exchange gagal.
- Command dasar tetap bisa dipakai di mesin lokal dan VPS baru.

Konsekuensi:

- Output harus menyimpan `data_source` dan warning jika fallback terjadi.
- Signal fallback tidak boleh dianggap valid untuk live trading.

## ADR-004 - Live Trading Locked By Default

Status: accepted.

Keputusan:

- Live trading default disabled.
- Perlu config dan environment variable eksplisit untuk membuka live order.
- Dry-run harus dimatikan secara sengaja sebelum order asli.

Alasan:

- Mencegah order tidak sengaja saat development.
- Memberi waktu untuk validasi paper trading, backtest, dan risk guard.

Konsekuensi:

- Deployment produksi harus menyertakan checklist safety.
- Setiap perubahan execution perlu test guard.

## ADR-005 - Dynamic Weights Berdasarkan Market Regime

Status: accepted.

Keputusan:

- Bobot rule dapat berubah berdasarkan market regime.
- Base rule tetap sama; perubahan bobot dicatat di rule result.

Alasan:

- Kondisi trending, mixed, dan high volatility tidak cocok memakai bobot yang sama.
- Explainability tetap terjaga karena applied weight dicatat.

Konsekuensi:

- Score harus menyimpan base weight, applied weight, dan nama profile.
- Config bobot harus mudah diaudit.

## ADR-006 - Multi-Timeframe Aggregation

Status: accepted.

Keputusan:

- Scanner mendukung beberapa timeframe dan menghasilkan final score berbobot.
- Timeframe besar mendapat bobot lebih tinggi untuk konteks trend.

Alasan:

- Signal satu timeframe rawan noise.
- Alignment antar timeframe membantu filter kandidat.

Konsekuensi:

- Result harus menyimpan score per timeframe dan final aggregate.
- Sprint berikutnya dapat memakai aggregate untuk ranking lintas symbol.

## ADR-007 - Documentation Checkpoint Setelah Sprint 08

Status: accepted.

Keputusan:

- Setelah Sprint 08, roadmap, arsitektur, keputusan, dan checkpoint ditulis ke folder `docs/`.
- Dokumentasi tidak mengubah source code dan tidak menjalankan test.

Alasan:

- Checkpoint dibutuhkan agar sprint berikutnya tidak restart dari awal.
- Task saat ini recovery mode khusus dokumentasi.

Konsekuensi:

- Verifikasi kode tidak dilakukan pada task dokumentasi ini sesuai instruksi terbaru.
- Sprint 09 belum dimulai otomatis.