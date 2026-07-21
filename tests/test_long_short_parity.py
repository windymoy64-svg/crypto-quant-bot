"""Long/short rule parity contract tests.

Ensures that for every quality gate category, the short engine applies the same
minimum score threshold as the long engine. This is a structural invariant: if
the two configs diverge, short entries will be harder or easier to pass than
long entries without a deliberate decision.

If you intentionally want asymmetry (e.g. tighter short gates), update the
reference dict in this test and document the reason.
"""

from __future__ import annotations

import json
from pathlib import Path


def _load_gates(rules_path: str) -> dict[str, float]:
    data = json.loads(Path(rules_path).read_text(encoding="utf-8-sig"))
    gates = data.get("quality_gates", {})
    return {k: float(v.get("min_score", 0)) for k, v in gates.items()}


def test_short_gates_equal_long_gates() -> None:
    long_gates = _load_gates("configs/rules.json")
    short_gates = _load_gates("configs/short_rules.json")

    for category, long_min in long_gates.items():
        short_min = short_gates.get(category)
        assert short_min is not None, (
            f"Category '{category}' exists in rules.json but missing in short_rules.json"
        )
        assert short_min == long_min, (
            f"Gate '{category}': long min={long_min}, short min={short_min}. "
            "Short and long quality gates must be equal. "
            "Update this test with a documented reason if asymmetry is intentional."
        )


def test_long_and_short_confidence_thresholds_pinned() -> None:
    """Pin short/long confidence thresholds to catch silent drift.

    As of v2 long and short configs use identical thresholds (buy=80, watch=70).
    The invariant this test enforces is: both configs must keep these exact
    values unless an operator explicitly edits this test.
    """

    def _load(path: str) -> dict[str, float]:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return {
            "buy_confidence": float(data.get("buy_confidence", 90.0)),
            "watch_confidence": float(data.get("watch_confidence", 80.0)),
        }

    expected = {"buy_confidence": 80.0, "watch_confidence": 70.0}
    assert _load("configs/rules.json") == expected
    assert _load("configs/short_rules.json") == expected


def test_short_rules_have_all_gate_categories_covered() -> None:
    long_data = json.loads(
        Path("configs/rules.json").read_text(encoding="utf-8-sig")
    )
    short_data = json.loads(
        Path("configs/short_rules.json").read_text(encoding="utf-8-sig")
    )
    long_categories = {
        str(r.get("category", "")) for r in long_data.get("rules", [])
    }
    short_categories = {
        str(r.get("category", "")) for r in short_data.get("rules", [])
    }
    # Every non-empty category in long must exist in short.
    for cat in long_categories:
        if not cat:
            continue
        assert cat in short_categories, (
            f"Category '{cat}' used in rules.json (LONG) has no rules in short_rules.json. "
            "Add at least one rule for this category to the short engine."
        )
