"""Build ``OfficeSnapshot`` from live bot artefacts.

Terjemahkan file JSON runtime bot (signals, paper state, agent pipeline
output) menjadi state 4 core agent pixel di layar kantor. Modul ini murni baca,
tidak pernah menulis, dan selalu mengembalikan snapshot yang valid meski
file belum ada supaya frontend selalu bisa render sesuatu.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal


AgentStatus = Literal["working", "idle", "break", "offline", "alert"]


AGENT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "yuna",
        "name": "Yuna",
        "role": "Lead",
        "room": "chart_room",
        "room_label": "Chart Desk",
        "job": "Chart Agent",
        "color": "#a78bfa",
    },
    {
        "id": "nara",
        "name": "Nara",
        "role": "Lead",
        "room": "learning_room",
        "room_label": "Learning Desk",
        "job": "Learning Agent",
        "color": "#34d399",
    },
    {
        "id": "miro",
        "name": "Miro",
        "role": "Lead",
        "room": "decision_room",
        "room_label": "Decision Desk",
        "job": "Decision Agent",
        "color": "#fbbf24",
    },
    {
        "id": "dami",
        "name": "Dami",
        "role": "Lead",
        "room": "executor_room",
        "room_label": "Executor Desk",
        "job": "Executor Agent",
        "color": "#6ee7b7",
    },
)

@dataclass(frozen=True)
class AgentState:
    """State satu agent di kantor virtual."""

    id: str
    name: str
    role: str
    room: str
    room_label: str
    job: str
    color: str
    status: AgentStatus
    task: str
    detail: str
    updated_at: str | None
    has_alert: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OfficeSnapshot:
    """Snapshot penuh: semua agent + ringkasan KPI di header."""

    generated_at: str
    staff_total: int
    working: int
    in_progress: int
    done: int
    agents: list[AgentState] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "kpi": {
                "staff": self.staff_total,
                "working": self.working,
                "in_progress": self.in_progress,
                "done": self.done,
            },
            "agents": [agent.to_dict() for agent in self.agents],
        }


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8-sig") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return None


def _parse_ts(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _fresh(ts: datetime | None, *, window_minutes: int) -> bool:
    if ts is None:
        return False
    return _utc_now() - ts <= timedelta(minutes=window_minutes)


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    """Yield dict rows dari file JSONL; skip baris rusak, aman file belum ada."""

    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8-sig") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    yield item
    except OSError:
        return


def _jsonl_stats(path: Path, *, window_minutes: int = 30) -> dict[str, Any]:
    """Ringkas file JSONL: total baris + baris baru dalam window N menit terakhir.

    Dipakai Learning Agent supaya aktivitas recorder (chart_observations /
    trade journal) memicu kunjungan learning di kantor pixel.
    """

    cutoff = _utc_now() - timedelta(minutes=window_minutes)
    count = 0
    recent = 0
    last_row: dict[str, Any] | None = None
    latest_ts: datetime | None = None
    for row in _iter_jsonl(path):
        count += 1
        ts = _parse_ts(row.get("timestamp"))
        if ts is not None:
            if latest_ts is None or ts > latest_ts:
                latest_ts = ts
            if ts >= cutoff:
                recent += 1
                last_row = row
    return {
        "count": count,
        "recent": recent,
        "latest_ts": latest_ts,
        "last_row": last_row,
    }


def _pipeline_stage_map(payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Kelompokkan entries pipeline per stage terakhir (ENTRY/POSITION_MONITOR)."""

    if not isinstance(payload, dict):
        return {}
    entries = payload.get("entries")
    stages: dict[str, dict[str, Any]] = {}
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
            stage = str(result.get("stage") or "ENTRY")
            stages[stage] = entry
    return stages


def _entry_has_reading(stages: dict[str, dict[str, Any]]) -> bool:
    entry = stages.get("ENTRY")
    if not isinstance(entry, dict):
        return False
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    return bool(result.get("eligible") and result.get("chart_reading"))


def _entry_has_decision(stages: dict[str, dict[str, Any]]) -> bool:
    entry = stages.get("ENTRY")
    if not isinstance(entry, dict):
        return False
    result = entry.get("result") if isinstance(entry.get("result"), dict) else {}
    return bool(result.get("eligible") and result.get("decision"))


def _count_paper_trades_today(trades_path: Path) -> int:
    """Hitung jumlah trade paper yang terjadi hari ini (UTC)."""

    if not trades_path.exists():
        return 0
    today = _utc_now().date()
    count = 0
    try:
        with trades_path.open(encoding="utf-8-sig") as file:
            for line in file:
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(item, dict):
                    continue
                ts = _parse_ts(item.get("timestamp") or item.get("time"))
                if ts is not None and ts.date() == today:
                    count += 1
    except OSError:
        return count
    return count


def _summarize_signals(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"count": 0, "top": None, "timestamp": None}
    signals = payload.get("signals")
    if not isinstance(signals, list) or not signals:
        return {"count": 0, "top": None, "timestamp": payload.get("timestamp")}
    buys = [s for s in signals if isinstance(s, dict) and s.get("action") == "BUY"]
    pool = buys if buys else [s for s in signals if isinstance(s, dict)]
    top = max(
        pool,
        key=lambda s: _safe_float(s.get("confidence")),
        default=None,
    )
    return {
        "count": len(signals),
        "top": top,
        "timestamp": payload.get("timestamp"),
    }


def _summarize_pipeline(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {
            "available": False,
            "top": None,
            "timestamp": None,
            "enabled": False,
            "execute_decisions": False,
        }
    entries = payload.get("entries")
    top = None
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result = entry.get("result")
            if isinstance(result, dict) and result.get("eligible"):
                top = entry
                break
        if top is None:
            for entry in entries:
                if isinstance(entry, dict):
                    top = entry
                    break
    return {
        "available": True,
        "top": top,
        "timestamp": payload.get("generated_at"),
        "enabled": bool(payload.get("enabled")),
        "execute_decisions": bool(payload.get("execute_decisions")),
    }


def _summarize_paper(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"balance": None, "open_positions": [], "updated_at": None}
    open_positions = payload.get("open_positions")
    positions: list[dict[str, Any]] = []
    if isinstance(open_positions, dict):
        for symbol, data in open_positions.items():
            if isinstance(data, dict):
                positions.append({"symbol": symbol, **data})
    elif isinstance(open_positions, list):
        positions = [p for p in open_positions if isinstance(p, dict)]
    return {
        "balance": payload.get("balance"),
        "open_positions": positions,
        "updated_at": payload.get("updated_at"),
    }


def _live_trading_flags() -> dict[str, bool]:
    enabled = os.getenv("LIVE_TRADING_ENABLED", "false").lower() == "true"
    dry_run = os.getenv("LIVE_TRADING_DRY_RUN", "true").lower() == "true"
    return {"enabled": enabled, "dry_run": dry_run}


def _def(agent_id: str) -> dict[str, Any]:
    return next(d for d in AGENT_DEFINITIONS if d["id"] == agent_id)


def _make(
    definition: dict[str, Any],
    *,
    status: AgentStatus,
    task: str,
    detail: str,
    updated_at: str | None,
    has_alert: bool = False,
) -> AgentState:
    return AgentState(
        id=definition["id"],
        name=definition["name"],
        role=definition["role"],
        room=definition["room"],
        room_label=definition["room_label"],
        job=definition["job"],
        color=definition["color"],
        status=status,
        task=task,
        detail=detail,
        updated_at=updated_at,
        has_alert=has_alert,
    )



def _agent_nara(
    observation_stats: dict[str, Any],
    journal_stats: dict[str, Any],
) -> AgentState:
    """Learning Agent. Working saat recorder menulis observasi/jurnal baru."""

    definition = _def("nara")
    observations = int(observation_stats.get("count", 0))
    journal = int(journal_stats.get("count", 0))
    recent = int(observation_stats.get("recent", 0)) + int(journal_stats.get("recent", 0))
    latest = max(
        (t for t in (observation_stats.get("latest_ts"), journal_stats.get("latest_ts")) if t),
        default=None,
    )
    updated_at = latest.isoformat() if latest else None

    if recent > 0:
        return _make(
            definition,
            status="working",
            task="Olah insight baru",
            detail=f"+{recent} record 30m | {observations} obs / {journal} journal",
            updated_at=updated_at,
        )
    if observations or journal:
        return _make(
            definition,
            status="idle",
            task="Insight tersimpan",
            detail=f"{observations} obs / {journal} journal",
            updated_at=updated_at,
        )
    return _make(
        definition,
        status="offline",
        task="Journal kosong",
        detail="data/learning_journal.jsonl belum ada",
        updated_at=None,
    )


def _agent_yuna(
    pipeline: dict[str, Any],
    stages: dict[str, dict[str, Any]],
    signals: dict[str, Any],
) -> AgentState:
    """Chart Reader Agent. Tahu apakah reading berasal dari entry atau monitor."""

    definition = _def("yuna")
    ts = _parse_ts(pipeline.get("timestamp"))
    top = pipeline.get("top")
    if _fresh(ts, window_minutes=10) and isinstance(top, dict):
        result = top.get("result") if isinstance(top.get("result"), dict) else {}
        reading = result.get("chart_reading") if isinstance(result, dict) else None
        symbol = top.get("symbol", "?")
        bias = "?"
        if isinstance(reading, dict):
            bias = str(reading.get("bias", "?"))
        if _entry_has_reading(stages):
            source = "sinyal scanner"
        elif "POSITION_MONITOR" in stages:
            source = "posisi open"
        else:
            source = "scan pasar"
        return _make(
            definition,
            status="working",
            task=f"Baca chart {symbol}",
            detail=f"bias={bias} | {source}",
            updated_at=pipeline.get("timestamp"),
        )
    if pipeline.get("available"):
        sig_ts = _parse_ts(signals.get("timestamp"))
        if _fresh(sig_ts, window_minutes=5) and signals.get("count", 0) > 0:
            return _make(
                definition,
                status="idle",
                task="Antri sinyal baru",
                detail="Belum ada kandidat eligible (gates/conf)",
                updated_at=pipeline.get("timestamp"),
            )
        return _make(
            definition,
            status="idle",
            task="Chart clean",
            detail="Pipeline belum ada entry baru",
            updated_at=pipeline.get("timestamp"),
        )
    return _make(
        definition,
        status="offline",
        task="Agent pipeline belum jalan",
        detail="logs/agent_pipeline.json belum ada",
        updated_at=None,
    )


def _agent_miro(pipeline: dict[str, Any]) -> AgentState:
    """Decision Agent. Ambil keputusan ENTRY/HOLD/EXIT."""

    definition = _def("miro")
    ts = _parse_ts(pipeline.get("timestamp"))
    top = pipeline.get("top")
    if _fresh(ts, window_minutes=10) and isinstance(top, dict):
        result = top.get("result") if isinstance(top.get("result"), dict) else {}
        decision = result.get("decision") if isinstance(result, dict) else None
        action = "?"
        conf = 0.0
        if isinstance(decision, dict):
            action = str(decision.get("action", "?"))
            conf = _safe_float(decision.get("confidence"))
        return _make(
            definition,
            status="working",
            task=f"Decide {action}",
            detail=f"confidence {conf:.0f}%",
            updated_at=pipeline.get("timestamp"),
            has_alert=action in {"ENTRY", "EXIT"},
        )
    return _make(
        definition,
        status="idle",
        task="Nunggu chart reading",
        detail="Decision agent standby",
        updated_at=pipeline.get("timestamp"),
    )


def _agent_dami(live_flags: dict[str, bool], pipeline: dict[str, Any]) -> AgentState:
    """Live Executor. Aktif hanya bila LIVE_TRADING_ENABLED=true."""

    definition = _def("dami")
    if not live_flags["enabled"]:
        return _make(
            definition,
            status="offline",
            task="Live trading terkunci",
            detail="LIVE_TRADING_ENABLED=false",
            updated_at=None,
        )
    if live_flags["dry_run"]:
        return _make(
            definition,
            status="idle",
            task="Live dry-run",
            detail="LIVE_TRADING_DRY_RUN=true",
            updated_at=pipeline.get("timestamp"),
        )
    if pipeline.get("execute_decisions"):
        return _make(
            definition,
            status="working",
            task="Eksekusi order live",
            detail="Pipeline execute_decisions=true",
            updated_at=pipeline.get("timestamp"),
            has_alert=True,
        )
    return _make(
        definition,
        status="idle",
        task="Live siap",
        detail="Menunggu decision eligible",
        updated_at=pipeline.get("timestamp"),
    )


def build_office_snapshot(
    *,
    base_dir: Path | str | None = None,
) -> OfficeSnapshot:
    """Rakit ``OfficeSnapshot`` dari file runtime bot.

    Args:
        base_dir: Root project. Default ``Path.cwd()`` supaya konsisten
            dengan modul services dashboard lainnya yang juga baca
            ``logs/*.json`` relatif terhadap current working dir.
    """

    root = Path(base_dir) if base_dir is not None else Path.cwd()

    signals_raw = _read_json(root / "logs" / "latest_signals.json")
    pipeline_raw = _read_json(root / "logs" / "agent_pipeline.json")
    paper_raw = _read_json(root / "logs" / "paper_state.json")

    signals = _summarize_signals(signals_raw if isinstance(signals_raw, dict) else None)
    pipeline = _summarize_pipeline(
        pipeline_raw if isinstance(pipeline_raw, dict) else None
    )
    stages = _pipeline_stage_map(pipeline_raw if isinstance(pipeline_raw, dict) else None)
    paper = _summarize_paper(paper_raw if isinstance(paper_raw, dict) else None)
    trades_today = _count_paper_trades_today(root / "logs" / "paper_trades.jsonl")
    live_flags = _live_trading_flags()
    observation_stats = _jsonl_stats(root / "data" / "chart_observations.jsonl")
    journal_stats = _jsonl_stats(root / "data" / "learning_journal.jsonl")

    agents = [
        _agent_yuna(pipeline, stages, signals),
        _agent_nara(observation_stats, journal_stats),
        _agent_miro(pipeline),
        _agent_dami(live_flags, pipeline),
    ]

    working = sum(1 for a in agents if a.status == "working")
    open_positions = len(paper.get("open_positions", []))

    return OfficeSnapshot(
        generated_at=_utc_now().isoformat(),
        staff_total=len(agents),
        working=working,
        in_progress=open_positions,
        done=trades_today,
        agents=agents,
    )


__all__ = [
    "AGENT_DEFINITIONS",
    "AgentState",
    "OfficeSnapshot",
    "build_office_snapshot",
]

