from pathlib import Path

path = Path("/opt/crypto-quant-bot/STATUS.md")
text = path.read_text(encoding="utf-8")

if "### [2026-07-25] — Soft-entry WATCH" not in text:
    entry = """## Log batch terbaru

### [2026-07-25] — Soft-entry WATCH (agent P1)
- **Siapa:** agent
- **Apa:**
  - Soft-entry: top WATCH (conf ≥ `min_watch_confidence`, default 75) dievaluasi Chart/Decision
  - Hard BUY/SELL tetap prioritas; max soft slot `max_watch_soft_entry` (default 3)
  - Input agent menggabungkan raw scanner WATCH (ACR sering rewrite ke SKIP)
  - Counters: `watch_soft_evaluated`, `watch_low_confidence`, `max_watch_soft_entry_cap`
- **Config prod:** `allow_watch_soft_entry=true`, `min_watch_confidence=75`, `max_watch_soft_entry=3`
- **File utama:** `app/agent_pipeline/bridge.py`, `coordinator.py`, `run_realtime.py`, `configs/realtime.json`, tests
- **Verifikasi:** service active; log `watch_soft=N`; tests soft-entry + coordinator eligibility
- **Catatan:** Decision tetap bisa SKIP/HOLD — soft-entry ≠ auto buy

"""
    text = text.replace("## Log batch terbaru\n\n", entry, 1)

text = text.replace(
    "- [ ] (Opsional) Review gate agent vs scanner confidence (banyak `action_SKIP` / low conf)\n",
    "- [x] Soft-entry WATCH (top conf ≥ 75, max 3) lewat Chart/Decision\n"
    "- [ ] (Opsional) Tuning `min_watch_confidence` / `max_watch_soft_entry` dari hasil paper 1–2 minggu\n",
    1,
)

if "allow_watch_soft_entry" not in text.split("### Observability")[1][:800] if "### Observability" in text else True:
    text = text.replace(
        "- Log baris `agent_pipeline in=... filters=...`\n",
        "- Log baris `agent_pipeline in=... filters=...`\n"
        "- Soft-entry WATCH: `allow_watch_soft_entry`, `min_watch_confidence`, `max_watch_soft_entry`\n",
        1,
    )

path.write_text(text, encoding="utf-8")
print("STATUS soft-entry updated")
