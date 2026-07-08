from __future__ import annotations


def net_spread_percent(buy_price: float, sell_price: float, total_fee_percent: float) -> float:
    if buy_price <= 0:
        raise ValueError("buy_price must be positive")
    gross = ((sell_price - buy_price) / buy_price) * 100
    return round(gross - total_fee_percent, 4)


def is_cross_exchange_opportunity(buy_price: float, sell_price: float, total_fee_percent: float, min_net_percent: float) -> bool:
    return net_spread_percent(buy_price, sell_price, total_fee_percent) >= min_net_percent
