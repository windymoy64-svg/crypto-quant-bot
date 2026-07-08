from __future__ import annotations

from app.core.models import Candle, TradingSignal
from app.paper.broker import PaperBroker


def run_demo_backtest(candles: list[Candle], signal: TradingSignal) -> dict[str, object]:
    broker = PaperBroker(balance=10_000.0, risk_percent=1.0)
    order = broker.execute(signal)
    return {
        "candles": len(candles),
        "mode": "paper_demo",
        "order": order,
        "open_positions": broker.positions,
    }
