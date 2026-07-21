"""Strategy version stamping for clean baseline attribution.

Every entry must record which configuration produced it so performance can be
split between baselines (old vs new) instead of attributing old trades to the
current config. ``strategy_version`` is a short hash of the settings that
actually change entry behaviour, plus a human-readable label.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StrategyVersion:
    label: str
    config_hash: str

    def to_dict(self) -> dict[str, object]:
        return {"label": self.label, "config_hash": self.config_hash}


def _stable_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def compute_strategy_version(
    *,
    rules_path: str = "configs/rules.json",
    short_rules_path: str = "configs/short_rules.json",
    realtime_path: str = "configs/realtime.json",
    paper_path: str = "configs/paper_trading.json",
    label: str = "v2",
) -> StrategyVersion:
    """Hash the config files that change entry/risk behaviour.

    Missing files are represented as empty strings so the hash is stable on a
    fresh checkout. The hash intentionally excludes learning journal and logs.
    """

    parts: list[str] = []
    for path in (rules_path, short_rules_path, realtime_path, paper_path):
        try:
            parts.append(Path(path).read_text(encoding="utf-8-sig"))
        except OSError:
            parts.append("")
    digest = hashlib.sha256(_stable_json(parts).encode("utf-8")).hexdigest()[:12]
    return StrategyVersion(label=label, config_hash=digest)


__all__ = ["StrategyVersion", "compute_strategy_version"]
