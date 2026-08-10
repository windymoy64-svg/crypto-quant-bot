"""Shared close-reason rules for paper and live execution."""

from __future__ import annotations

from typing import Any


KNOWN_REASONS = {
    "stop_loss", "trailing_stop", "manual_exit", "agent_exit", "liquidation",
    "take_profit_1", "take_profit_2", "take_profit_3",
    "take_profit_timeout", "exchange_closed_without_bot_reason",
}


def classify_close_reason(
    position: dict[str, Any],
    *,
    close_price: float | None = None,
    realized_pnl: float | None = None,
    explicit_reason: str | None = None,
    filled_role: str | None = None,
) -> str:
    """Apply the paper close rules to both paper and exchange closes."""
    pnl = float(realized_pnl if realized_pnl is not None else position.get("realized_pnl") or 0)
    side = str(position.get("side") or "").upper()
    is_short = side in {"SHORT", "SELL"}

    if explicit_reason in {"closed_position", "exchange_order", "position_reduced"}:
        explicit_reason = None
    if explicit_reason:
        if explicit_reason.startswith("take_profit_") and pnl <= 0:
            return _classify_by_price(position, close_price, pnl, is_short)
        return explicit_reason

    if filled_role in {"take_profit_1", "take_profit_2", "take_profit_3"} and pnl > 0:
        return filled_role
    if filled_role in {"stop_loss", "exit"}:
        if filled_role == "stop_loss":
            return "trailing_stop" if _trailing_stop_was_active(position) else "stop_loss"
        return "agent_exit"
    return _classify_by_price(position, close_price, pnl, is_short)


def _classify_by_price(
    position: dict[str, Any], close_price: float | None, pnl: float, is_short: bool,
) -> str:
    price = float(close_price or 0)
    trailing = float(position.get("trailing_stop_loss") or position.get("trailing_stop") or 0)
    static_stop = float(position.get("static_stop_loss") or position.get("stop_loss") or 0)
    if price > 0:
        if _trailing_stop_was_active(position) and trailing > 0:
            if (is_short and price >= trailing) or (not is_short and price <= trailing):
                return "trailing_stop"
        if static_stop > 0 and ((is_short and price >= static_stop) or (not is_short and price <= static_stop)):
            return "stop_loss"

        targets = position.get("take_profit") or position.get("take_profits") or []
        if isinstance(targets, list):
            hit = [index for index, target in enumerate(targets[:3])
                   if ((is_short and price <= float(target)) or (not is_short and price >= float(target)))]
            if hit and pnl > 0:
                return f"take_profit_{hit[-1] + 1}"
    return "exchange_closed_without_bot_reason"


def _trailing_stop_was_active(position: dict[str, Any]) -> bool:
    return bool(
        position.get("trailing_active")
        or position.get("trailing_stop_loss") is not None
        or position.get("trailing_stop") is not None
    )


__all__ = ["KNOWN_REASONS", "classify_close_reason"]
