"""Runtime configuration for the trade feedback recorder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LearningRecorderConfig:
    """Config for periodic trade feedback recording.

    The recorder is disabled by default. When enabled, it scans the paper
    trades event log at the end of each cycle and pushes new closures into
    the Learning Agent journal so ``LearningAgent.learn()`` can produce
    increasingly accurate insights.
    """

    enabled: bool = False
    trades_path: str = ""  # inherit from paper config when empty
    trade_store_path: str = "data/learning_journal.jsonl"
    observation_store_path: str = "data/chart_observations.jsonl"
    checkpoint_path: str = "data/learning_recorder_checkpoint.json"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "LearningRecorderConfig":
        data = data or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            trades_path=str(data.get("trades_path", "")),
            trade_store_path=str(
                data.get("trade_store_path", "data/learning_journal.jsonl")
            ),
            observation_store_path=str(
                data.get(
                    "observation_store_path",
                    "data/chart_observations.jsonl",
                )
            ),
            checkpoint_path=str(
                data.get(
                    "checkpoint_path",
                    "data/learning_recorder_checkpoint.json",
                )
            ),
        )

    def resolve_trades_path(self, fallback: str | None) -> str:
        """Return an explicit trades_path if set, else the paper config path."""
        return self.trades_path or (fallback or "")


def build_recorder_if_enabled(
    config: LearningRecorderConfig,
    *,
    paper_trades_path: str | None,
):
    """Instantiate a TradeFeedbackRecorder or return None when disabled.

    Imported lazily so ``run_realtime.py`` module import stays cheap even when
    the feature is turned off.
    """
    if not config.enabled:
        return None

    resolved = config.resolve_trades_path(paper_trades_path)
    if not resolved or not Path(resolved).exists():
        return None

    from app.learning_agent.agent import LearningAgent
    from app.learning_agent.recorder import TradeFeedbackRecorder
    from app.learning_agent.store import ChartObservationStore, TradeStore
    from app.llm.factory import build_agent_llm

    trade_store = TradeStore(config.trade_store_path)
    observation_store = ChartObservationStore(config.observation_store_path)
    llm_client, llm_model, llm_base_url = build_agent_llm("learning")
    return TradeFeedbackRecorder(
        trades_path=resolved,
        learning_agent=LearningAgent(
            store=trade_store,
            observation_store=observation_store,
            llm_client=llm_client,
            llm_model=llm_model,
            llm_base_url=llm_base_url,
        ),
        observation_store=observation_store,
        checkpoint_path=config.checkpoint_path,
    )
