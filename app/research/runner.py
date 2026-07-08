from __future__ import annotations

from pathlib import Path

from app.research.artifacts import load_research_dataset
from app.research.engine import StrategyResearchEngine
from app.research.reports import StrategyReportWriter


def generate_strategy_report(logs_dir: str | Path = "logs", output_dir: str | Path = "reports") -> dict[str, str]:
    dataset = load_research_dataset(logs_dir)
    report = StrategyResearchEngine().analyze(dataset)
    return StrategyReportWriter(output_dir).write(report)