"""Build ``OfficeSnapshot`` from live bot artefacts.

Terjemahkan file JSON runtime bot (signals, paper state, agent pipeline
output) menjadi state 7 agent pixel di layar kantor. Modul ini murni baca,
tidak pernah menulis, dan selalu mengembalikan snapshot yang valid meski
file belum ada supaya frontend selalu bisa render sesuatu.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal


AgentStatus = Literal["working", "idle", "break", "offline", "alert"]


AGENT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "rian",
        "name": "Rian",
        "role": "Lead",
        "room": "pre_production",
        "room_label": "Pre-production",
        "job": "Market Scanner",
        "color": "#f472b6",
    },
    {
        "id": "haru",
        "name": "Haru",
        "role": "Senior",
        "room": "pre_production",
        "room_label": "Pre-production",
        "job": "Signal Builder",
        "color": "#fb7185",
    },
    {
        "id": "yuna",
        "name": "Yuna",
        "role": "Lead",
        "room": "scene_engine",
        "room_label": "Scene Engine",
        "job": "Chart Reader Agent",
        "color": "#a78bfa",
    },
    {
        "id": "miro",
        "name": "Miro",
        "role": "Junior",
        "room": "art_camera",
        "room_label": "Art & Camera",
        "job": "Decision Agent",
        "color": "#fbbf24",
    },
    {
        "id": "quinn",
        "name": "Quinn",
        "role": "Lead",
        "room": "cut_qa",
        "room_label": "Cut QA",
        "job": "Risk Manager",
        "color": "#fca5a5",
    },
    {
        "id": "raven",
        "name": "Raven",
        "role": "Lead",
        "room": "devsecops",
        "room_label": "DevSecOps",
        "job": "Paper Broker",
        "color": "#c084fc",
    },
    {
        "id": "dami",
        "name": "Dami",
        "role": "Lead",
        "room": "operations",
        "room_label": "Operations",
        "job": "Live Executor",
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



def _agent_rian(signals: dict[str, Any]) -> AgentState:
    """Market Scanner. Fresh signal file berarti dia lagi kerja."""

    definition = _def("rian")
    ts = _parse_ts(signals.get("timestamp"))
    if _fresh(ts, window_minutes=5) and signals.get("count", 0) > 0:
        top = signals.get("top") or {}
        symbol = top.get("symbol", "?")
        confidence = _safe_float(top.get("confidence"))
        return _make(
            definition,
            status="working",
            task=f"Scan {symbol}",
            detail=f"{signals.get('count', 0)} signals, top {confidence:.0f}%",
            updated_at=signals.get("timestamp"),
        )
    if signals.get("count", 0) > 0:
        return _make(
            definition,
            status="idle",
            task="Menunggu cycle scan",
            detail=f"{signals.get('count', 0)} signal tersimpan",
            updated_at=signals.get("timestamp"),
        )
    return _make(
        definition,
        status="offline",
        task="Scanner belum jalan",
        detail="logs/latest_signals.json kosong",
        updated_at=None,
    )


def _agent_haru(signals: dict[str, Any]) -> AgentState:
    """Signal Builder. Aktif bareng scanner, fokus ke BUY."""

    definition = _def("haru")
    ts = _parse_ts(signals.get("timestamp"))
    top = signals.get("top") or {}
    if _fresh(ts, window_minutes=5) and top.get("action") == "BUY":
        symbol = top.get("symbol", "?")
        return _make(
            definition,
            status="working",
            task=f"Bangun signal {symbol}",
            detail=f"entry={top.get('entry')} sl={top.get('stop_loss')}",
            updated_at=signals.get("timestamp"),
        )
    if _fresh(ts, window_minutes=5):
        return _make(
            definition,
            status="idle",
            task="Nunggu kandidat BUY",
            detail="Belum ada action=BUY di cycle terakhir",
            updated_at=signals.get("timestamp"),
        )
    return _make(
        definition,
        status="break",
        task="Break",
        detail="Signal builder idle",
        updated_at=signals.get("timestamp"),
    )


def _agent_yuna(pipeline: dict[str, Any]) -> AgentState:
    """Chart Reader Agent. Baca chart HTF/MTF/LTF."""

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
        return _make(
            definition,
            status="working",
            task=f"Baca chart {symbol}",
            detail=f"bias={bias}",
            updated_at=pipeline.get("timestamp"),
        )
    if pipeline.get("available"):
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


def _agent_quinn(signals: dict[str, Any]) -> AgentState:
    """Risk Manager / QA. Alert kalau ada failed_gates."""

    definition = _def("quinn")
    ts = _parse_ts(signals.get("timestamp"))
    top = signals.get("top") or {}
    failed_gates = top.get("failed_gates") if isinstance(top, dict) else None
    if _fresh(ts, window_minutes=5) and isinstance(failed_gates, list) and failed_gates:
        return _make(
            definition,
            status="alert",
            task="Review failed gates",
            detail=", ".join(str(g) for g in failed_gates[:3]),
            updated_at=signals.get("timestamp"),
            has_alert=True,
        )
    if _fresh(ts, window_minutes=5):
        risk = top.get("risk", "?") if isinstance(top, dict) else "?"
        return _make(
            definition,
            status="working",
            task="QA sinyal",
            detail=f"risk={risk}",
            updated_at=signals.get("timestamp"),
        )
    return _make(
        definition,
        status="break",
        task="Break Room",
        detail="Nunggu batch signal berikutnya",
        updated_at=signals.get("timestamp"),
    )


def _agent_raven(paper: dict[str, Any], trades_today: int) -> AgentState:
    """Paper Broker. Working kalau ada posisi terbuka."""

    definition = _def("raven")
    positions = paper.get("open_positions", [])
    balance = paper.get("balance")
    if positions:
        pos = positions[0]
        symbol = pos.get("symbol", "?")
        side = pos.get("side", "?")
        return _make(
            definition,
            status="working",
            task=f"Kelola {symbol}",
            detail=f"{side} @ {pos.get('entry')} | balance {balance}",
            updated_at=paper.get("updated_at"),
        )
    if trades_today > 0:
        return _make(
            definition,
            status="idle",
            task="Post-trade wrap up",
            detail=f"{trades_today} trade hari ini | balance {balance}",
            updated_at=paper.get("updated_at"),
        )
    return _make(
        definition,
        status="idle",
        task="Standby paper broker",
        detail=f"balance {balance}",
        updated_at=paper.get("updated_at"),
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
    paper = _summarize_paper(paper_raw if isinstance(paper_raw, dict) else None)
    trades_today = _count_paper_trades_today(root / "logs" / "paper_trades.jsonl")
    live_flags = _live_trading_flags()

    agents = [
        _agent_rian(signals),
        _agent_haru(signals),
        _agent_yuna(pipeline),
        _agent_miro(pipeline),
        _agent_quinn(signals),
        _agent_raven(paper, trades_today),
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

