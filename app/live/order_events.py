from __future__ import annotations

from dataclasses import dataclass

from app.live.order_store import LiveOrderRecord


@dataclass(frozen=True)
class OrderCreated:
    order: LiveOrderRecord


@dataclass(frozen=True)
class OrderPartiallyFilled:
    order: LiveOrderRecord


@dataclass(frozen=True)
class OrderFilled:
    order: LiveOrderRecord


@dataclass(frozen=True)
class OrderCanceled:
    order: LiveOrderRecord


@dataclass(frozen=True)
class OrderRejected:
    order: LiveOrderRecord


@dataclass(frozen=True)
class OrderExpired:
    order: LiveOrderRecord