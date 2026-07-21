"""Tests for strategy version stamping (config hash attribution)."""

from __future__ import annotations

from app.config.strategy_version import StrategyVersion, compute_strategy_version


def test_strategy_version_produces_stable_hash_on_same_files() -> None:
    v1 = compute_strategy_version()
    v2 = compute_strategy_version()
    assert v1.config_hash == v2.config_hash
    assert v1.label == v2.label


def test_strategy_version_hash_is_12_chars() -> None:
    v = compute_strategy_version()
    assert len(v.config_hash) == 12


def test_strategy_version_to_dict() -> None:
    v = StrategyVersion(label="v2", config_hash="abc123def456")
    d = v.to_dict()
    assert d["label"] == "v2"
    assert d["config_hash"] == "abc123def456"


def test_compute_strategy_version_with_missing_file() -> None:
    # Should not raise; missing files represented as empty string.
    v = compute_strategy_version(
        rules_path="configs/nonexistent.json",
        short_rules_path="configs/rules.json",
        realtime_path="configs/realtime.json",
        paper_path="configs/paper_trading.json",
    )
    assert v.config_hash
    assert v.label == "v2"
