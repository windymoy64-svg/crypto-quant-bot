from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.risk.manager import calculate_position_size


@dataclass(frozen=True)
class PaperTradingConfig:
    enabled: bool
    starting_balance: float
    risk_percent: float
    max_open_positions: int
    state_path: str
    trades_path: str

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PaperTradingConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            starting_balance=float(data.get("starting_balance", 10_000)),
            risk_percent=float(data.get("risk_percent", 1)),
            max_open_positions=int(data.get("max_open_positions", 3)),
            state_path=str(data.get("state_path", "logs/paper_state.json")),
            trades_path=str(data.get("trades_path", "logs/paper_trades.jsonl")),
        )


class RealtimePaperTradingEngine:
    def __init__(self, config: PaperTradingConfig) -> None:
        self.config = config

    def process_signals(self, signals: list[dict[str, object]]) -> dict[str, object]:
        state = self._load_state()
        events: list[dict[str, object]] = []

        for signal in signals:
            events.extend(self._update_position(state, signal))

        for signal in signals:
            event = self._maybe_open_position(state, signal)
            if event is not None:
                events.append(event)

        state["updated_at"] = self._now()
        self._save_state(state)
        for event in events:
            self._append_trade_event(event)

        return {
            "enabled": self.config.enabled,
            "balance": round(float(state["balance"]), 2),
            "equity": round(self._calculate_equity(state, signals), 2),
            "open_positions": list(state["open_positions"].values()),
            "events": events,
            "state_path": self.config.state_path,
            "trades_path": self.config.trades_path,
        }

    def _maybe_open_position(
        self,
        state: dict[str, object],
        signal: dict[str, object],
    ) -> dict[str, object] | None:
        if not self.config.enabled:
            return None
        if signal.get("action") != "BUY":
            return None

        symbol = str(signal["symbol"])
        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")
        if symbol in open_positions:
            return None
        if len(open_positions) >= self.config.max_open_positions:
            return self._event("ignored", symbol, "max_open_positions_reached", signal)

        entry = float(signal["entry"])
        stop_loss = float(signal["stop_loss"])
        size = calculate_position_size(
            account_balance=float(state["balance"]),
            risk_percent=self.config.risk_percent,
            entry=entry,
            stop_loss=stop_loss,
        )
        if size <= 0:
            return self._event("ignored", symbol, "invalid_position_size", signal)

        position = {
            "symbol": symbol,
            "side": "BUY",
            "entry": entry,
            "size": size,
            "stop_loss": stop_loss,
            "take_profit": list(signal["take_profit"]),
            "opened_at": self._now(),
            "last_price": entry,
            "unrealized_pnl": 0.0,
            "confidence": float(signal["confidence"]),
        }
        open_positions[symbol] = position
        return self._event("opened", symbol, "signal_buy", signal, position=position)

    def _update_position(
        self,
        state: dict[str, object],
        signal: dict[str, object],
    ) -> list[dict[str, object]]:
        symbol = str(signal["symbol"])
        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")
        if symbol not in open_positions:
            return []

        position = open_positions[symbol]
        if not isinstance(position, dict):
            raise TypeError("position must be a dict")

        current_price = float(signal["entry"])
        position["last_price"] = current_price
        position["unrealized_pnl"] = self._pnl(position, current_price)

        if current_price <= float(position["stop_loss"]):
            return [self._close_position(state, symbol, current_price, "stop_loss", signal)]

        take_profit = position.get("take_profit", [])
        if isinstance(take_profit, list) and take_profit and current_price >= float(take_profit[0]):
            return [self._close_position(state, symbol, current_price, "take_profit_1", signal)]

        return []

    def _close_position(
        self,
        state: dict[str, object],
        symbol: str,
        exit_price: float,
        reason: str,
        signal: dict[str, object],
    ) -> dict[str, object]:
        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")
        position = open_positions.pop(symbol)
        if not isinstance(position, dict):
            raise TypeError("position must be a dict")

        pnl = self._pnl(position, exit_price)
        state["balance"] = float(state["balance"]) + pnl
        closed_position = {
            **position,
            "exit": exit_price,
            "closed_at": self._now(),
            "realized_pnl": round(pnl, 2),
            "close_reason": reason,
        }
        return self._event("closed", symbol, reason, signal, position=closed_position)

    def _load_state(self) -> dict[str, object]:
        path = Path(self.config.state_path)
        if not path.exists():
            return {
                "created_at": self._now(),
                "updated_at": self._now(),
                "starting_balance": self.config.starting_balance,
                "balance": self.config.starting_balance,
                "open_positions": {},
            }
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _save_state(self, state: dict[str, object]) -> None:
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def _append_trade_event(self, event: dict[str, object]) -> None:
        path = Path(self.config.trades_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event) + "\n")

    def _calculate_equity(self, state: dict[str, object], signals: list[dict[str, object]]) -> float:
        latest_prices = {str(signal["symbol"]): float(signal["entry"]) for signal in signals}
        equity = float(state["balance"])
        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            return equity
        for symbol, position in open_positions.items():
            if isinstance(position, dict):
                equity += self._pnl(position, latest_prices.get(symbol, float(position["last_price"])))
        return equity

    def _pnl(self, position: dict[str, object], price: float) -> float:
        return (price - float(position["entry"])) * float(position["size"])

    def _event(
        self,
        event_type: str,
        symbol: str,
        reason: str,
        signal: dict[str, object],
        *,
        position: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "timestamp": self._now(),
            "type": event_type,
            "symbol": symbol,
            "reason": reason,
            "price": signal.get("entry"),
            "action": signal.get("action"),
            "confidence": signal.get("confidence"),
            "position": position,
        }

    def _now(self) -> str:
        return datetime.now(tz=UTC).isoformat()
