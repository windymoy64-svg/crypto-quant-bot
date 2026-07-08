from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class PositionSizeRequest:
    equity: float
    cash: float
    risk_percent: float
    entry: float
    stop_loss: float
    max_notional: float


@dataclass(frozen=True)
class PositionSizeResult:
    quantity: float
    notional: float
    risk_amount: float
    risk_per_unit: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PositionSizer:
    def size(self, request: PositionSizeRequest) -> PositionSizeResult:
        risk_per_unit = abs(request.entry - request.stop_loss)
        risk_amount = max(request.equity, 0.0) * (max(request.risk_percent, 0.0) / 100)
        if request.entry <= 0 or risk_per_unit <= 0 or risk_amount <= 0:
            return PositionSizeResult(0.0, 0.0, round(risk_amount, 8), round(risk_per_unit, 8))

        risk_quantity = risk_amount / risk_per_unit
        max_cash_notional = min(max(request.cash, 0.0), max(request.max_notional, 0.0))
        max_quantity = max_cash_notional / request.entry
        quantity = min(risk_quantity, max_quantity)
        notional = quantity * request.entry
        return PositionSizeResult(
            quantity=round(quantity, 8),
            notional=round(notional, 8),
            risk_amount=round(risk_amount, 8),
            risk_per_unit=round(risk_per_unit, 8),
        )