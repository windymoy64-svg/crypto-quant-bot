from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.live.order_state import OrderState, normalize_order_state
from app.portfolio.reconciliation import PortfolioReconciler
from app.portfolio.storage import PortfolioStorage


class PortfolioSynchronizer:
    def __init__(self, storage: PortfolioStorage | None = None, reconciler: PortfolioReconciler | None = None) -> None:
        self.storage = storage or PortfolioStorage()
        self.reconciler = reconciler or PortfolioReconciler()

    def recover(self, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        state = self.storage.load()
        if state:
            state["recovered"] = True
            return state
        return fallback or {"open_positions": [], "open_positions_count": 0, "equity": 0.0, "available_balance": 0.0, "recovered": False}

    def sync_from_lifecycle(self, portfolio: dict[str, Any], order_snapshot: dict[str, Any]) -> dict[str, Any]:
        positions = {str(item.get("symbol")): dict(item) for item in portfolio.get("open_positions", []) if isinstance(item, dict) and item.get("symbol")}
        for order in order_snapshot.get("filled_orders", []) if isinstance(order_snapshot, dict) else []:
            if not isinstance(order, dict) or normalize_order_state(str(order.get("status", ""))) != OrderState.FILLED:
                continue
            symbol = str(order.get("symbol", ""))
            if not symbol:
                continue
            positions.setdefault(symbol, {"symbol": symbol, "quantity": 0.0, "average_entry_price": 0.0})
            qty = _to_float(order.get("filled_qty"), 0.0)
            price = _to_float(order.get("average_price"), 0.0)
            current_qty = _to_float(positions[symbol].get("quantity"), 0.0)
            current_price = _to_float(positions[symbol].get("average_entry_price", positions[symbol].get("price")), 0.0)
            positions[symbol]["quantity"] = max(current_qty, qty)
            positions[symbol]["average_entry_price"] = price or current_price
            positions[symbol]["source"] = "order_lifecycle"
        synced = dict(portfolio)
        synced["open_positions"] = list(positions.values())
        synced["open_positions_count"] = len(positions)
        synced["synced_at"] = datetime.now(UTC).isoformat()
        synced["reconciliation"] = self.reconciler.reconcile(synced, order_snapshot).to_dict()
        self.storage.save(synced)
        return synced


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
