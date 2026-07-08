from __future__ import annotations

from typing import Protocol

from app.exchange.binance.client import BinanceConnector
from app.live.config import LiveConfig
from app.live.response import OrderSubmissionResult
from app.live.safety import LiveSafetyGate


class OrderSubmitConnector(Protocol):
    def private_post(self, path: str, params: dict[str, object] | None = None) -> object:
        ...


class BinanceOrderSubmissionEngine:
    def __init__(
        self,
        config: LiveConfig | None = None,
        *,
        connector: OrderSubmitConnector | None = None,
        operator: str = "unknown",
    ) -> None:
        self.config = config or LiveConfig()
        self.connector = connector or BinanceConnector()
        self.operator = operator

    def submit_order(self, payload: dict[str, object]) -> OrderSubmissionResult:
        gate = LiveSafetyGate.from_config(self.config, operator=self.operator)
        decision = gate.evaluate()
        if not decision.approved:
            return OrderSubmissionResult.blocked(decision.reason, {"safety": decision.to_dict()})
        response = self.connector.private_post("/api/v3/order", payload)
        if not isinstance(response, dict):
            return OrderSubmissionResult(success=False, status="INVALID_RESPONSE", raw={"response": response})
        return OrderSubmissionResult.from_binance(response)