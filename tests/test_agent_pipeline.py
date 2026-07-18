"""Tests for the end-to-end multi-agent coordinator."""

from __future__ import annotations

from pathlib import Path

from app.agent_pipeline.coordinator import AgentPipelineConfig, AgentPipelineCoordinator
from app.agent_pipeline.models import ScannerCandidate
from app.core.models import Candle
from app.executor_agent.agent import ExecutorAgent
from app.executor_agent.models import PositionContext
from app.learning_agent.agent import LearningAgent
from app.learning_agent.store import ChartObservationStore, TradeStore


def _c(i: int, o: float, h: float, l: float, c: float) -> Candle:
    return Candle(
        symbol="BTC/USDT", timestamp=f"2024-01-01T{i:02d}:00:00Z",
        open=o, high=h, low=l, close=c, volume=1000.0,
    )


def _candles(n: int = 30) -> list[Candle]:
    """Trend with small pullbacks to give all readers enough data."""
    result: list[Candle] = []
    base = 100.0
    for i in range(n):
        trend = i * 0.5
        pullback = -0.8 if i % 5 == 0 else 0.0
        open_price = base + trend + pullback
        close = open_price + 0.35
        result.append(_c(i, open_price, close + 0.25, open_price - 0.3, close))
    return result


def _coordinator(tmp_path: Path, *, execute: bool = False) -> AgentPipelineCoordinator:
    learning = LearningAgent(
        store=TradeStore(str(tmp_path / "trades.jsonl")),
        observation_store=ChartObservationStore(str(tmp_path / "observations.jsonl")),
    )
    return AgentPipelineCoordinator(
        learning_agent=learning,
        executor_agent=ExecutorAgent(balance=10_000),
        config=AgentPipelineConfig(execute_decisions=execute),
    )


def test_entry_rejects_candidate_below_scanner_confidence(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result = coordinator.process_entry_candidate(
        ScannerCandidate(
            symbol="BTC/USDT", action="BUY", confidence=89.9,
            failed_gates=[], meta={},
        ),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )

    assert result.eligible is False
    assert result.chart_reading is None
    assert result.decision is None
    assert "scanner_confidence" in result.eligibility_reason


def test_entry_rejects_candidate_with_failed_gate(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result = coordinator.process_entry_candidate(
        ScannerCandidate(
            symbol="BTC/USDT", action="BUY", confidence=95.0,
            failed_gates=["volume"], meta={},
        ),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )

    assert result.eligible is False
    assert result.chart_reading is None
    assert result.eligibility_reason == "scanner_gates_failed"


def test_qualified_entry_reads_chart_and_records_observation(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result = coordinator.process_entry_candidate(
        ScannerCandidate(
            symbol="BTC/USDT", action="BUY", confidence=95.0,
            failed_gates=[], meta={},
        ),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )

    assert result.eligible is True
    assert result.chart_reading is not None
    assert result.decision is not None
    assert result.execution is None  # execution opt-in only

    store = ChartObservationStore(str(tmp_path / "observations.jsonl"))
    observed = store.load_all()
    assert len(observed) == 1
    assert observed[0].stage == "ENTRY_CANDIDATE"
    assert observed[0].scanner_gates_passed is True
    assert observed[0].scanner_confidence == 95.0


def test_position_monitor_always_reads_chart_and_records(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result = coordinator.monitor_position(
        symbol="BTC/USDT",
        position=PositionContext(side="BUY", quantity=1.0, current_price=105.0),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )

    assert result.eligible is True
    assert result.eligibility_reason == "open_position_monitoring"
    assert result.chart_reading is not None
    assert result.decision is not None

    observed = ChartObservationStore(str(tmp_path / "observations.jsonl")).load_all()
    assert len(observed) == 1
    assert observed[0].stage == "POSITION_MONITOR"


def test_execution_remains_opt_in(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path, execute=False)
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )
    assert result.execution is None


def test_pipeline_result_serializes(tmp_path: Path) -> None:
    coordinator = _coordinator(tmp_path)
    result = coordinator.process_entry_candidate(
        ScannerCandidate("BTC/USDT", "BUY", 95.0, [], {}),
        htf_candles=_candles(), mtf_candles=_candles(), ltf_candles=_candles(),
    )
    payload = result.to_dict()
    assert payload["stage"] == "ENTRY"
    assert payload["chart_reading"] is not None
    assert payload["decision"] is not None