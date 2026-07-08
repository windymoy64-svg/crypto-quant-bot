from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class ReconciliationIssue:
    level: str
    code: str
    message: str
    symbol: str = ""
    expected: Any = None
    actual: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "symbol": self.symbol,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass
class ReconciliationReport:
    status: str
    checked_at: str
    issues: list[ReconciliationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "checked_at": self.checked_at, "issues": [issue.to_dict() for issue in self.issues]}


class PortfolioReconciler:
    def reconcile(self, portfolio: dict[str, Any], orders: dict[str, Any], tolerance: float = 1e-8) -> ReconciliationReport:
        issues: list[ReconciliationIssue] = []
        positions = _positions_by_symbol(portfolio.get("open_positions", []))
        filled_orders = orders.get("filled_orders", []) if isinstance(orders, dict) else []
        expected_qty: dict[str, float] = {}
        if isinstance(filled_orders, list):
            for order in filled_orders:
                if not isinstance(order, dict):
                    continue
                symbol = str(order.get("symbol", ""))
                if symbol:
                    expected_qty[symbol] = expected_qty.get(symbol, 0.0) + _to_float(order.get("filled_qty"), 0.0)
        for symbol, expected in expected_qty.items():
            actual = _to_float(positions.get(symbol, {}).get("quantity"), 0.0)
            if abs(expected - actual) > tolerance:
                issues.append(ReconciliationIssue("warning", "position_qty_mismatch", "Filled order quantity differs from portfolio position", symbol, expected, actual))
        status = "ok" if not issues else "needs_review"
        return ReconciliationReport(status=status, checked_at=datetime.now(UTC).isoformat(), issues=issues)


def _positions_by_symbol(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        return {}
    return {str(item["symbol"]): item for item in value if isinstance(item, dict) and item.get("symbol")}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
