from __future__ import annotations

from enum import StrEnum


class OrderState(StrEnum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


TERMINAL_ORDER_STATES = {
    OrderState.FILLED,
    OrderState.CANCELED,
    OrderState.EXPIRED,
    OrderState.REJECTED,
}


def normalize_order_state(status: str) -> OrderState:
    value = str(status or "").upper()
    if value in OrderState.__members__:
        return OrderState[value]
    if value in {state.value for state in OrderState}:
        return OrderState(value)
    return OrderState.REJECTED