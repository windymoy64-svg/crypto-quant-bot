from __future__ import annotations

import json
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.models import TradingSignal
from app.live import LiveConfig, LiveTradingManager
from app.risk.manager import RiskDecision, RiskManager, RiskSettings
from app.core.models import Candle


def _read_json(path: str | Path, default: Any) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def _load_signal() -> TradingSignal:
    latest = _read_json("logs/latest_signals.json", {})
    rows = latest.get("signals", []) if isinstance(latest, dict) else []
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("action") == "BUY":
                return _signal_from_dict(row)
    return TradingSignal(
        symbol="BTC/USDT",
        action="BUY",
        score=100.0,
        confidence=95.0,
        entry=100000.0,
        stop_loss=99000.0,
        take_profit=[101500.0, 102500.0, 103500.0],
        risk_reward=2.5,
        risk="LOW",
        strategy="Dry Run Sample",
        meta={"source": "run_live_fallback"},
    )


def _signal_from_dict(data: dict[str, Any]) -> TradingSignal:
    allowed = {field.name for field in fields(TradingSignal)}
    values = {key: value for key, value in data.items() if key in allowed}
    values.setdefault("take_profit", [])
    values.setdefault("meta", {})
    return TradingSignal(**values)


def _risk_decision(signal: TradingSignal) -> RiskDecision:
    timestamp = datetime.now(UTC).isoformat()
    candles = _synthetic_candles(signal.symbol, signal.entry, timestamp)
    return RiskManager(settings=RiskSettings(max_open_positions=3)).evaluate_entry(
        symbol=signal.symbol,
        timestamp=timestamp,
        candles=candles,
        cash=1000.0,
        equity=1000.0,
        entry=signal.entry,
        stop_loss=signal.stop_loss,
        take_profit=signal.take_profit[0] if signal.take_profit else signal.entry,
        open_positions=0,
        current_exposure=0.0,
    )


def _synthetic_candles(symbol: str, entry: float, timestamp: str) -> list[Candle]:
    candles: list[Candle] = []
    for index in range(20):
        close = entry * (1 + (index - 10) * 0.0005)
        candles.append(
            Candle(
                symbol=symbol,
                timestamp=timestamp,
                open=round(close * 0.999, 8),
                high=round(close * 1.002, 8),
                low=round(close * 0.998, 8),
                close=round(close, 8),
                volume=1000.0 + index,
            )
        )
    return candles


def main() -> None:
    config = LiveConfig.from_json("configs/live.json")
    signal = _load_signal()
    decision = _risk_decision(signal)
    result = LiveTradingManager(config).execute(signal, decision)
    print(json.dumps(result.to_dict(), indent=2))


if __name__ == "__main__":
    main()
