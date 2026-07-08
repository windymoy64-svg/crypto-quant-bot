from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.paper.account import PaperAccountSnapshot
from app.paper.fills import PaperFill
from app.paper.orders import PaperOrder
from app.paper.positions import PaperPositionSnapshot
from app.portfolio.manager import PortfolioManager


@dataclass
class PaperState:
    account: PaperAccountSnapshot
    positions: dict[str, PaperPositionSnapshot] = field(default_factory=dict)
    orders: list[dict[str, object]] = field(default_factory=list)
    fills: list[dict[str, object]] = field(default_factory=list)
    updated_at: str = ""

    def to_portfolio(self) -> PortfolioManager:
        portfolio = PortfolioManager(account=self.account.to_portfolio_account())
        portfolio.positions = {symbol: position.to_portfolio_position() for symbol, position in self.positions.items()}
        portfolio.prices = {symbol: position.average_entry_price for symbol, position in self.positions.items()}
        return portfolio

    @classmethod
    def from_portfolio(
        cls,
        portfolio: PortfolioManager,
        *,
        orders: list[dict[str, object]],
        fills: list[dict[str, object]],
        updated_at: str,
    ) -> "PaperState":
        return cls(
            account=PaperAccountSnapshot.from_portfolio(portfolio.account),
            positions={
                symbol: PaperPositionSnapshot.from_portfolio(position)
                for symbol, position in portfolio.positions.items()
            },
            orders=orders,
            fills=fills,
            updated_at=updated_at,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "account": self.account.to_dict(),
            "positions": {symbol: position.to_dict() for symbol, position in self.positions.items()},
            "orders": self.orders,
            "fills": self.fills,
            "updated_at": self.updated_at,
        }


class PaperPersistence:
    def __init__(self, state_path: str, events_path: str) -> None:
        self.state_path = Path(state_path)
        self.events_path = Path(events_path)

    def load_state(self, starting_balance: float) -> PaperState:
        if not self.state_path.exists():
            return PaperState(account=PaperAccountSnapshot(starting_balance, starting_balance))
        data = json.loads(self.state_path.read_text(encoding="utf-8-sig"))
        account_data = data.get("account", {})
        if not isinstance(account_data, dict):
            account_data = {}
        positions_data = data.get("positions", {})
        if not isinstance(positions_data, dict):
            positions_data = {}
        return PaperState(
            account=PaperAccountSnapshot.from_dict(account_data, starting_balance),
            positions={
                str(symbol): PaperPositionSnapshot.from_dict(position)
                for symbol, position in positions_data.items()
                if isinstance(position, dict)
            },
            orders=self._list(data.get("orders")),
            fills=self._list(data.get("fills")),
            updated_at=str(data.get("updated_at", "")),
        )

    def save_state(self, state: PaperState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")

    def record_order(self, order: PaperOrder) -> None:
        self._append_event({"type": "order", "payload": order.to_dict()})

    def record_fill(self, fill: PaperFill) -> None:
        self._append_event({"type": "fill", "payload": fill.to_dict()})

    def _append_event(self, event: dict[str, object]) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event) + "\n")

    def _list(self, value: Any) -> list[dict[str, object]]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]