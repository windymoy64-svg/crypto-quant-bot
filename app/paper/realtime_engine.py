from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.risk.manager import calculate_position_size


@dataclass(frozen=True)
class AutoExitConfig:
    enabled: bool = True
    tp_fractions: tuple[float, ...] = (0.30, 0.30, 0.40)
    trailing_activation_atr_multiple: float = 1.0
    trailing_distance_atr_multiple: float = 1.5

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> "AutoExitConfig":
        data = data or {}
        fractions = data.get("tp_fractions") or [0.30, 0.30, 0.40]
        if not isinstance(fractions, (list, tuple)) or len(fractions) != 3:
            fractions = [0.30, 0.30, 0.40]
        return cls(
            enabled=bool(data.get("enabled", True)),
            tp_fractions=tuple(float(x) for x in fractions),
            trailing_activation_atr_multiple=float(data.get("trailing_activation_atr_multiple", 1.0)),
            trailing_distance_atr_multiple=float(data.get("trailing_distance_atr_multiple", 1.5)),
        )


@dataclass(frozen=True)
class PaperTradingConfig:
    enabled: bool
    starting_balance: float
    risk_percent: float
    max_open_positions: int
    state_path: str
    trades_path: str
    auto_exit: AutoExitConfig = field(default_factory=AutoExitConfig)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PaperTradingConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            starting_balance=float(data.get("starting_balance", 10_000)),
            risk_percent=float(data.get("risk_percent", 1)),
            max_open_positions=int(data.get("max_open_positions", 3)),
            state_path=str(data.get("state_path", "logs/paper_state.json")),
            trades_path=str(data.get("trades_path", "logs/paper_trades.jsonl")),
            auto_exit=AutoExitConfig.from_dict(data.get("auto_exit") if isinstance(data.get("auto_exit"), dict) else None),
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
        if entry <= stop_loss:
            return self._event("ignored", symbol, "stop_loss_equals_or_above_entry", signal)
        size = calculate_position_size(
            account_balance=float(state["balance"]),
            risk_percent=self.config.risk_percent,
            entry=entry,
            stop_loss=stop_loss,
        )
        if size <= 0:
            return self._event("ignored", symbol, "invalid_position_size", signal)

        # Hitung ATR dari SL awal: entry - 1.5*ATR = stop_loss → ATR = (entry-SL)/1.5
        atr_at_entry = (entry - stop_loss) / 1.5 if entry > stop_loss else 0.0

        position = {
            "symbol": symbol,
            "side": "BUY",
            "entry": entry,
            "size": size,
            "remaining_size": size,
            "stop_loss": stop_loss,
            "static_stop_loss": stop_loss,
            "trailing_stop_loss": None,
            "trailing_active": False,
            "highest_price": entry,
            "atr_at_entry": atr_at_entry,
            "take_profit": list(signal["take_profit"]),
            "tp_hit": [False, False, False],
            "realized_pnl_partial": 0.0,
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

        # Track harga tertinggi (untuk trailing)
        if current_price > float(position.get("highest_price", position["entry"])):
            position["highest_price"] = current_price

        # Update unrealized PnL untuk sisa posisi
        position["unrealized_pnl"] = self._pnl(position, current_price)

        events: list[dict[str, object]] = []

        # Kalau auto_exit dimatikan, pakai perilaku lama (close semua di SL/TP1)
        if not self.config.auto_exit.enabled:
            if current_price <= float(position["stop_loss"]):
                events.append(self._close_position_full(state, symbol, current_price, "stop_loss", signal))
                return events
            tp_list = position.get("take_profit", [])
            if isinstance(tp_list, list) and tp_list and current_price >= float(tp_list[0]):
                events.append(self._close_position_full(state, symbol, current_price, "take_profit_1", signal))
            return events

        # --- Mode auto_exit aktif ---

        # 1. Cek trailing stop aktivasi
        atr = float(position.get("atr_at_entry", 0.0))
        entry_price = float(position["entry"])
        if atr > 0 and not position.get("trailing_active", False):
            activation_threshold = entry_price + atr * self.config.auto_exit.trailing_activation_atr_multiple
            if current_price >= activation_threshold:
                position["trailing_active"] = True

        # 2. Update trailing SL kalau aktif
        if position.get("trailing_active", False) and atr > 0:
            new_trailing = float(position["highest_price"]) - atr * self.config.auto_exit.trailing_distance_atr_multiple
            prev_trailing = position.get("trailing_stop_loss")
            if prev_trailing is None or new_trailing > float(prev_trailing):
                position["trailing_stop_loss"] = round(new_trailing, 6)

        # 3. SL efektif = max(statis, trailing)
        effective_sl = float(position["static_stop_loss"])
        trailing_sl = position.get("trailing_stop_loss")
        if trailing_sl is not None and float(trailing_sl) > effective_sl:
            effective_sl = float(trailing_sl)
        position["stop_loss"] = round(effective_sl, 6)

        # 4. Cek stop loss dulu (sebelum TP)
        if current_price <= effective_sl:
            reason = "trailing_stop" if position.get("trailing_active") else "stop_loss"
            events.append(self._close_position_full(state, symbol, current_price, reason, signal))
            return events

        # 5. Cek TP bertingkat
        tp_list = position.get("take_profit", [])
        tp_hit = position.get("tp_hit", [False, False, False])
        fractions = self.config.auto_exit.tp_fractions

        for i in range(min(3, len(tp_list))):
            if tp_hit[i]:
                continue
            if current_price >= float(tp_list[i]):
                fraction = fractions[i]
                # Kalau TP3 (i=2), tutup semua sisanya
                is_last = (i == 2) or (i == len(tp_list) - 1)
                if is_last:
                    events.append(self._close_position_full(state, symbol, current_price, f"take_profit_{i+1}", signal))
                    return events
                # Partial close
                event = self._close_position_partial(state, symbol, current_price, fraction, f"take_profit_{i+1}", signal)
                if event:
                    events.append(event)
                    tp_hit[i] = True
                    position["tp_hit"] = tp_hit
                    # Aktifkan trailing setelah TP1 pertama kena (kalau belum aktif)
                    if not position.get("trailing_active", False):
                        position["trailing_active"] = True

        return events

    def _close_position_partial(
        self,
        state: dict[str, object],
        symbol: str,
        exit_price: float,
        fraction: float,
        reason: str,
        signal: dict[str, object],
    ) -> dict[str, object] | None:
        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")
        position = open_positions.get(symbol)
        if not isinstance(position, dict):
            return None

        remaining = float(position.get("remaining_size", position["size"]))
        size_to_close = remaining * fraction
        if size_to_close <= 0:
            return None

        pnl_partial = (exit_price - float(position["entry"])) * size_to_close
        state["balance"] = float(state["balance"]) + pnl_partial
        position["remaining_size"] = round(remaining - size_to_close, 8)
        position["realized_pnl_partial"] = round(float(position.get("realized_pnl_partial", 0.0)) + pnl_partial, 6)
        position["unrealized_pnl"] = self._pnl(position, exit_price)

        snapshot = {
            **position,
            "partial_exit_price": exit_price,
            "partial_size_closed": round(size_to_close, 8),
            "partial_realized_pnl": round(pnl_partial, 2),
            "partial_reason": reason,
        }
        return self._event("partial_close", symbol, reason, signal, position=snapshot)

    def _close_position_full(
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

        remaining = float(position.get("remaining_size", position["size"]))
        pnl_final = (exit_price - float(position["entry"])) * remaining
        total_pnl = round(float(position.get("realized_pnl_partial", 0.0)) + pnl_final, 2)
        state["balance"] = float(state["balance"]) + pnl_final

        closed_position = {
            **position,
            "exit": exit_price,
            "closed_at": self._now(),
            "final_size_closed": round(remaining, 8),
            "final_realized_pnl": round(pnl_final, 2),
            "realized_pnl": total_pnl,
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
                price = latest_prices.get(symbol, float(position.get("last_price", position["entry"])))
                equity += self._pnl(position, price)
        return equity

    def _pnl(self, position: dict[str, object], price: float) -> float:
        remaining = float(position.get("remaining_size", position["size"]))
        return (price - float(position["entry"])) * remaining

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