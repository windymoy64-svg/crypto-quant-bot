from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class BaseEvent:
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=utc_now_iso)

    @property
    def event_type(self) -> str:
        return self.__class__.__name__

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_type"] = self.event_type
        return payload


@dataclass(frozen=True)
class PriceUpdated(BaseEvent):
    symbol: str = ""
    price: float = 0.0
    source: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class SignalCreated(BaseEvent):
    symbol: str = ""
    action: str = ""
    score: float = 0.0
    confidence: float = 0.0
    timestamp: str = ""
    signal: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskApproved(BaseEvent):
    symbol: str = ""
    timestamp: str = ""
    quantity: float = 0.0
    notional: float = 0.0
    reason: str = "approved"
    decision: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskRejected(BaseEvent):
    symbol: str = ""
    timestamp: str = ""
    reason: str = ""
    decision: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderCreated(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    quantity: float = 0.0
    requested_price: float = 0.0
    timestamp: str = ""


@dataclass(frozen=True)
class OrderFilled(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    notional: float = 0.0
    fee: float = 0.0
    status: str = ""
    timestamp: str = ""


@dataclass(frozen=True)
class PositionOpened(BaseEvent):
    symbol: str = ""
    quantity: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    timestamp: str = ""


@dataclass(frozen=True)
class PositionClosed(BaseEvent):
    symbol: str = ""
    quantity: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    realized_pnl: float = 0.0
    timestamp: str = ""


@dataclass(frozen=True)
class PortfolioUpdated(BaseEvent):
    equity: float = 0.0
    available_balance: float = 0.0
    used_capital: float = 0.0
    open_positions_count: int = 0
    timestamp: str = ""
    portfolio: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BacktestFinished(BaseEvent):
    symbol: str = ""
    timeframe: str = ""
    candles: int = 0
    signals_seen: int = 0
    trades_count: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    timestamp: str = ""


@dataclass(frozen=True)
class PaperOrderCreated(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    order_type: str = ""
    quantity: float = 0.0
    requested_price: float = 0.0
    timestamp: str = ""
    order: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperOrderFilled(BaseEvent):
    order_id: str = ""
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    notional: float = 0.0
    fee: float = 0.0
    status: str = ""
    timestamp: str = ""
    fill: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperPositionOpened(BaseEvent):
    symbol: str = ""
    quantity: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    timestamp: str = ""
    position: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperPositionClosed(BaseEvent):
    symbol: str = ""
    quantity: float = 0.0
    price: float = 0.0
    fee: float = 0.0
    realized_pnl: float = 0.0
    timestamp: str = ""
    position: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperBalanceUpdated(BaseEvent):
    balance: float = 0.0
    equity: float = 0.0
    available_balance: float = 0.0
    used_capital: float = 0.0
    timestamp: str = ""
    account: dict[str, Any] = field(default_factory=dict)