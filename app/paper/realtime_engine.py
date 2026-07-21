from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.risk.manager import calculate_position_size


def _optional_positive_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(value)
    if parsed <= 0:
        raise ValueError("percentage overrides must be positive")
    return parsed


def _optional_positive_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    parsed = int(value)
    if parsed <= 0:
        raise ValueError("leverage must be positive")
    return parsed


@dataclass(frozen=True)
class AutoExitConfig:
    enabled: bool = True
    tp_fractions: tuple[float, ...] = (0.30, 0.30, 0.40)
    # FIXED: Aktif lebih cepat (0.5 ATR) dan jarak lebih ketat (1.0 ATR)
    trailing_activation_atr_multiple: float = 0.5
    trailing_distance_atr_multiple: float = 1.0
    # ACR+ bridge (Opsi C - filter/enhancement). Bila True, engine memanggil
    # apply_acr_breakeven/apply_acr_trailing/check_acr_invalidation dari
    # ``app.strategies.acr_engine_bridge`` bila signal menyediakan
    # ``ltf_candles``. Fallback ke ATR-based logic bila candles tidak ada.
    use_acr_position_manager: bool = False
    acr_trail_buffer_pct: float = 0.002

    @classmethod
    def from_dict(
        cls,
        data: dict[str, object] | None,
    ) -> "AutoExitConfig":
        data = data or {}
        fractions = data.get("tp_fractions") or [0.30, 0.30, 0.40]

        if not isinstance(fractions, (list, tuple)) or len(fractions) != 3:
            fractions = [0.30, 0.30, 0.40]

        return cls(
            enabled=bool(data.get("enabled", True)),
            tp_fractions=tuple(float(value) for value in fractions),
            trailing_activation_atr_multiple=float(
                data.get("trailing_activation_atr_multiple", 0.5)
            ),
            trailing_distance_atr_multiple=float(
                data.get("trailing_distance_atr_multiple", 1.0)
            ),
            use_acr_position_manager=bool(
                data.get("use_acr_position_manager", False)
            ),
            acr_trail_buffer_pct=float(
                data.get("acr_trail_buffer_pct", 0.002)
            ),
        )


@dataclass(frozen=True)
class PaperTradingConfig:
    enabled: bool
    starting_balance: float
    risk_percent: float
    max_open_positions: int
    state_path: str
    trades_path: str
    max_position_size_percent: float = 15.0  # Tambah field: satu posisi max 15% balance
    auto_exit: AutoExitConfig = field(default_factory=AutoExitConfig)
    take_profit_percent: float | None = None
    stop_loss_percent: float | None = None
    trailing_stop_percent: float | None = None
    leverage: int | None = None
    max_leverage: int = 5  # Cap effective leverage during validation/live.

    @classmethod
    def from_dict(
        cls,
        data: dict[str, object],
    ) -> "PaperTradingConfig":
        auto_exit_data = (
            data.get("auto_exit")
            if isinstance(data.get("auto_exit"), dict)
            else None
        )

        return cls(
            enabled=bool(data.get("enabled", True)),
            starting_balance=float(
                data.get("starting_balance", 10_000)
            ),
            risk_percent=float(data.get("risk_percent", 1)),
            max_open_positions=int(
                data.get("max_open_positions", 20)
            ),
            state_path=str(
                data.get("state_path", "logs/paper_state.json")
            ),
            trades_path=str(
                data.get("trades_path", "logs/paper_trades.jsonl")
            ),
            max_position_size_percent=float(
                data.get("max_position_size_percent", 15.0)
            ),
            auto_exit=AutoExitConfig.from_dict(auto_exit_data),
            take_profit_percent=_optional_positive_float(
                data.get("take_profit_percent")
            ),
            stop_loss_percent=_optional_positive_float(
                data.get("stop_loss_percent")
            ),
            trailing_stop_percent=_optional_positive_float(
                data.get("trailing_stop_percent")
            ),
            leverage=_optional_positive_int(data.get("leverage")),
            max_leverage=int(data.get("max_leverage", 5)),
        )


class RealtimePaperTradingEngine:
    def __init__(self, config: PaperTradingConfig, telegram_notifier: Any = None) -> None:
        self.config = config
        self.telegram_notifier = telegram_notifier

    def process_signals(
        self,
        signals: list[dict[str, object]],
    ) -> dict[str, object]:
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
            # Pass signal for detailed reasoning in telegram report
            for sig in signals:
                if sig.get("symbol") == event.get("symbol"):
                    self._send_telegram_report(event, sig)
                    break
            else:
                self._send_telegram_report(event, None)

        return {
            "enabled": self.config.enabled,
            "balance": round(float(state["balance"]), 2),
            "equity": round(
                self._calculate_equity(state, signals),
                2,
            ),
            "open_positions": list(
                state["open_positions"].values()
            ),
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

        action = str(signal.get("action", "")).upper()
        if action not in {"BUY", "SELL"}:
            return None

        side = "BUY" if action == "BUY" else "SHORT"
        symbol = str(signal["symbol"])

        open_positions = state["open_positions"]
        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")

        if symbol in open_positions:
            return None

        if len(open_positions) >= self.config.max_open_positions:
            return self._event(
                "ignored",
                symbol,
                "max_open_positions_reached",
                signal,
            )

        entry = float(signal["entry"])
        stop_loss = self._entry_stop_loss(signal, side, entry)
        take_profit = self._entry_take_profit(signal, side, entry)

        if side == "BUY" and entry <= stop_loss:
            return self._event(
                "ignored",
                symbol,
                "long_stop_loss_must_be_below_entry",
                signal,
            )

        if side == "SHORT" and stop_loss <= entry:
            return self._event(
                "ignored",
                symbol,
                "short_stop_loss_must_be_above_entry",
                signal,
            )

        # Calculate available balance (total balance - margin committed by
        # open positions). Existing positions without leverage remain 1x.
        used_capital = sum(
            (
                float(pos.get("entry", 0))
                * float(pos.get("remaining_size", 0))
                / max(float(pos.get("leverage", 1) or 1), 1.0)
            )
            for pos in open_positions.values()
        )
        available = float(state["balance"]) - used_capital
        
        if available <= 0:
            return self._event(
                "ignored",
                symbol,
                "no_available_balance",
                signal,
            )

        # Leverage guard: cap effective leverage during validation. Leverage
        # does not change edge, only amplifies liquidation and execution risk,
        # so the cap is enforced even if operator preferences request higher.
        max_leverage = int(getattr(self.config, "max_leverage", 5) or 5)
        leverage = min(int(self.config.leverage or 1), max_leverage)
        if leverage < 1:
            leverage = 1
        size = calculate_position_size(
            account_balance=available,
            risk_percent=self.config.risk_percent,
            entry=entry,
            stop_loss=stop_loss,
            # max_position_size_percent represents committed margin. Convert
            # it to the equivalent leveraged notional cap for paper sizing.
            max_position_percent=(
                self.config.max_position_size_percent * leverage
            ),
        )

        if size <= 0:
            return self._event(
                "ignored",
                symbol,
                "invalid_position_size",
                signal,
            )

        atr_at_entry = abs(entry - stop_loss) / 1.5

        position = {
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "size": size,
            "remaining_size": size,
            "leverage": leverage,
            "used_capital": round(entry * size / leverage, 8),
            "stop_loss": stop_loss,
            "static_stop_loss": stop_loss,
            "trailing_stop_loss": None,
            "trailing_active": False,
            "highest_price": entry,
            "lowest_price": entry,
            "atr_at_entry": atr_at_entry,
            "take_profit": take_profit,
            "tp_hit": [False, False, False],
            "realized_pnl_partial": 0.0,
            "opened_at": self._now(),
            "last_price": entry,
            "unrealized_pnl": 0.0,
            "confidence": float(signal["confidence"]),
            "entry_reason": self._build_entry_reason(signal, side),
            "configured_leverage": self.config.leverage,
        }

        open_positions[symbol] = position

        reason = (
            "signal_buy"
            if side == "BUY"
            else "signal_short"
        )

        return self._event(
            "opened",
            symbol,
            reason,
            signal,
            position=position,
        )

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

        position["highest_price"] = max(
            float(position.get("highest_price", position["entry"])),
            current_price,
        )
        position["lowest_price"] = min(
            float(position.get("lowest_price", position["entry"])),
            current_price,
        )
        position["unrealized_pnl"] = self._pnl(
            position,
            current_price,
        )

        if not self.config.auto_exit.enabled:
            return self._process_legacy_exit(
                state,
                symbol,
                current_price,
                signal,
            )

        atr_value = float(
            position.get("atr_at_entry", 0.0)
        )
        entry_price = float(position["entry"])

        self._activate_trailing(
            position,
            current_price,
            entry_price,
            atr_value,
        )
        self._update_trailing_stop(position, atr_value)

        # --- ACR+ bridge (Opsi C, opsional behind flag) ---
        # Bila flag aktif dan signal menyediakan ``ltf_candles``, upgrade
        # trailing/breakeven ke swing-based dan cek invalidation.
        if self.config.auto_exit.use_acr_position_manager:
            ltf_candles = self._extract_ltf_candles(signal)
            if ltf_candles:
                self._apply_acr_management(position, ltf_candles)
                invalidation = self._check_acr_invalidation(
                    position, ltf_candles
                )
                if invalidation is not None:
                    return [
                        self._close_position_full(
                            state,
                            symbol,
                            current_price,
                            f"acr_invalidation_{invalidation}",
                            signal,
                        )
                    ]

        self._update_effective_stop(position)

        if self._is_stop_hit(position, current_price):
            reason = (
                "trailing_stop"
                if position.get("trailing_active")
                else "stop_loss"
            )
            return [
                self._close_position_full(
                    state,
                    symbol,
                    current_price,
                    reason,
                    signal,
                )
            ]

        events = self._process_take_profits(
            state,
            symbol,
            current_price,
            signal,
        )
        return events

    def _process_legacy_exit(
        self,
        state: dict[str, object],
        symbol: str,
        price: float,
        signal: dict[str, object],
    ) -> list[dict[str, object]]:
        position = self._get_position(state, symbol)

        if self._is_stop_hit(position, price):
            return [
                self._close_position_full(
                    state,
                    symbol,
                    price,
                    "stop_loss",
                    signal,
                )
            ]

        targets = position.get("take_profit", [])
        if (
            isinstance(targets, list)
            and targets
            and self._is_tp_hit(
                position,
                float(targets[0]),
                price,
            )
        ):
            return [
                self._close_position_full(
                    state,
                    symbol,
                    price,
                    "take_profit_1",
                    signal,
                )
            ]

        return []

    def _activate_trailing(
        self,
        position: dict[str, object],
        current_price: float,
        entry_price: float,
        atr_value: float,
    ) -> None:
        if position.get("trailing_active", False):
            return

        trailing_percent = self.config.trailing_stop_percent
        if trailing_percent is not None:
            activation_distance = entry_price * (trailing_percent / 100)
        elif atr_value > 0:
            activation_distance = (
                atr_value
                * self.config.auto_exit.trailing_activation_atr_multiple
            )
        else:
            return

        if self._is_short(position):
            should_activate = (
                current_price
                <= entry_price - activation_distance
            )
        else:
            should_activate = (
                current_price
                >= entry_price + activation_distance
            )

        if should_activate:
            position["trailing_active"] = True

    def _update_trailing_stop(
        self,
        position: dict[str, object],
        atr_value: float,
    ) -> None:
        if not position.get("trailing_active"):
            return
        trailing_percent = self.config.trailing_stop_percent
        if trailing_percent is not None:
            reference = (
                float(position["lowest_price"])
                if self._is_short(position)
                else float(position["highest_price"])
            )
            trailing_distance = reference * (trailing_percent / 100)
        elif atr_value > 0:
            trailing_distance = (
                atr_value
                * self.config.auto_exit.trailing_distance_atr_multiple
            )
        else:
            return
        previous = position.get("trailing_stop_loss")
        entry_price = float(position["entry"])

        if self._is_short(position):
            candidate = (
                float(position["lowest_price"])
                + trailing_distance
            )
            # Floor rule SHORT: trailing stop tidak boleh di atas entry (min profit = breakeven)
            candidate = min(candidate, entry_price)

            if previous is None or candidate < float(previous):
                position["trailing_stop_loss"] = round(
                    candidate,
                    8,
                )
        else:
            candidate = (
                float(position["highest_price"])
                - trailing_distance
            )
            # Floor rule LONG: trailing stop tidak boleh di bawah entry (min profit = breakeven)
            candidate = max(candidate, entry_price)

            if previous is None or candidate > float(previous):
                position["trailing_stop_loss"] = round(
                    candidate,
                    8,
                )

    def _update_effective_stop(
        self,
        position: dict[str, object],
    ) -> None:
        static_stop = float(position["static_stop_loss"])
        trailing_stop = position.get("trailing_stop_loss")

        if trailing_stop is None:
            position["stop_loss"] = static_stop
            return

        if self._is_short(position):
            effective = min(
                static_stop,
                float(trailing_stop),
            )
        else:
            effective = max(
                static_stop,
                float(trailing_stop),
            )

        position["stop_loss"] = round(effective, 8)

    def _process_take_profits(
        self,
        state: dict[str, object],
        symbol: str,
        current_price: float,
        signal: dict[str, object],
    ) -> list[dict[str, object]]:
        position = self._get_position(state, symbol)
        targets = position.get("take_profit", [])
        hits = position.get("tp_hit", [False, False, False])
        fractions = self.config.auto_exit.tp_fractions
        events: list[dict[str, object]] = []

        if not isinstance(targets, list):
            return events

        if not isinstance(hits, list) or len(hits) < 3:
            hits = [False, False, False]

        for index in range(min(3, len(targets))):
            if hits[index]:
                continue

            target = float(targets[index])

            if not self._is_tp_hit(
                position,
                target,
                current_price,
            ):
                continue

            is_last = (
                index == 2
                or index == len(targets) - 1
            )

            if is_last:
                events.append(
                    self._close_position_full(
                        state,
                        symbol,
                        current_price,
                        f"take_profit_{index + 1}",
                        signal,
                    )
                )
                return events

            event = self._close_position_partial(
                state,
                symbol,
                current_price,
                fractions[index],
                f"take_profit_{index + 1}",
                signal,
            )

            if event is not None:
                events.append(event)
                hits[index] = True
                position["tp_hit"] = hits
                position["trailing_active"] = True
                # After TP1 hit: move SL to breakeven for "free ride"
                if index == 0:
                    entry_price = float(position["entry"])
                    position["static_stop_loss"] = round(entry_price, 8)

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
        position = self._get_position(state, symbol)
        remaining = float(
            position.get("remaining_size", position["size"])
        )
        size_to_close = remaining * fraction

        if size_to_close <= 0:
            return None

        pnl_partial = self._pnl_for_size(
            position,
            exit_price,
            size_to_close,
        )

        state["balance"] = (
            float(state["balance"]) + pnl_partial
        )

        position["remaining_size"] = round(
            remaining - size_to_close,
            8,
        )
        leverage = max(float(position.get("leverage", 1) or 1), 1.0)
        position["used_capital"] = round(
            float(position["entry"])
            * float(position["remaining_size"])
            / leverage,
            8,
        )
        position["realized_pnl_partial"] = round(
            float(position.get("realized_pnl_partial", 0.0))
            + pnl_partial,
            8,
        )
        position["unrealized_pnl"] = self._pnl(
            position,
            exit_price,
        )

        snapshot = {
            **position,
            "partial_exit_price": exit_price,
            "partial_size_closed": round(size_to_close, 8),
            "partial_realized_pnl": round(pnl_partial, 8),
            "partial_reason": reason,
        }

        return self._event(
            "partial_close",
            symbol,
            reason,
            signal,
            position=snapshot,
        )

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

        remaining = float(
            position.get("remaining_size", position["size"])
        )
        pnl_final = self._pnl_for_size(
            position,
            exit_price,
            remaining,
        )
        total_pnl = round(
            float(position.get("realized_pnl_partial", 0.0))
            + pnl_final,
            2,
        )

        state["balance"] = (
            float(state["balance"]) + pnl_final
        )

        closed_position = {
            **position,
            "exit": exit_price,
            "closed_at": self._now(),
            "final_size_closed": round(remaining, 8),
            "final_realized_pnl": round(pnl_final, 8),
            "realized_pnl": round(total_pnl, 8),
            "close_reason": reason,
        }

        return self._event(
            "closed",
            symbol,
            reason,
            signal,
            position=closed_position,
        )

    def _calculate_equity(
        self,
        state: dict[str, object],
        signals: list[dict[str, object]],
    ) -> float:
        latest_prices = {
            str(signal["symbol"]): float(signal["entry"])
            for signal in signals
        }

        equity = float(state["balance"])
        open_positions = state["open_positions"]

        if not isinstance(open_positions, dict):
            return equity

        for symbol, position in open_positions.items():
            if not isinstance(position, dict):
                continue

            fallback = float(
                position.get("last_price", position["entry"])
            )
            price = latest_prices.get(symbol, fallback)
            equity += self._pnl(position, price)

        return equity

    def _pnl(
        self,
        position: dict[str, object],
        price: float,
    ) -> float:
        remaining = float(
            position.get("remaining_size", position["size"])
        )
        return self._pnl_for_size(
            position,
            price,
            remaining,
        )

    def _pnl_for_size(
        self,
        position: dict[str, object],
        price: float,
        size: float,
    ) -> float:
        entry = float(position["entry"])
        direction = -1.0 if self._is_short(position) else 1.0
        return (price - entry) * size * direction

    def _is_stop_hit(
        self,
        position: dict[str, object],
        price: float,
    ) -> bool:
        stop = float(position["stop_loss"])

        if self._is_short(position):
            return price >= stop

        return price <= stop

    def _is_tp_hit(
        self,
        position: dict[str, object],
        target: float,
        price: float,
    ) -> bool:
        if self._is_short(position):
            return price <= target

        return price >= target

    def _is_short(
        self,
        position: dict[str, object],
    ) -> bool:
        return str(position.get("side", "BUY")).upper() in {
            "SHORT",
            "SELL",
        }

    def _entry_stop_loss(
        self,
        signal: dict[str, object],
        side: str,
        entry: float,
    ) -> float:
        percent = self.config.stop_loss_percent
        if percent is None:
            return float(signal["stop_loss"])
        multiplier = 1 + (percent / 100) if side == "SHORT" else 1 - (percent / 100)
        return round(entry * multiplier, 8)

    def _entry_take_profit(
        self,
        signal: dict[str, object],
        side: str,
        entry: float,
    ) -> list[float]:
        percent = self.config.take_profit_percent
        if percent is None:
            raw = signal.get("take_profit", [])
            return [float(value) for value in raw] if isinstance(raw, list) else []
        multiplier = 1 - (percent / 100) if side == "SHORT" else 1 + (percent / 100)
        return [round(entry * multiplier, 8)]

    def _get_position(
        self,
        state: dict[str, object],
        symbol: str,
    ) -> dict[str, object]:
        open_positions = state["open_positions"]

        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")

        position = open_positions.get(symbol)

        if not isinstance(position, dict):
            raise TypeError("position must be a dict")

        return position

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

        state = json.loads(
            path.read_text(encoding="utf-8-sig")
        )

        open_positions = state.get("open_positions")

        if not isinstance(open_positions, dict):
            raise TypeError("open_positions must be a dict")

        return state

    def _save_state(
        self,
        state: dict[str, object],
    ) -> None:
        path = Path(self.config.state_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )

    def _append_trade_event(
        self,
        event: dict[str, object],
    ) -> None:
        path = Path(self.config.trades_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event) + "\n")

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

    def _build_entry_reason(self, signal: dict[str, object], side: str) -> str:
        """Susun ringkasan alasan teknis entry dari meta signal.

        SHORT memakai short_meta bila tersedia, LONG memakai meta biasa.
        Menampilkan skor, RR, dan rule teknis yang lolos (maks 5).
        """
        meta = signal.get("meta") or {}
        if side == "SHORT":
            short_meta = signal.get("short_meta") or {}
            if isinstance(short_meta, dict) and short_meta:
                meta = short_meta

        parts: list[str] = []
        score = signal.get("score")
        if score is not None:
            parts.append(f"Score {float(score):.0f}")

        rr = signal.get("risk_reward")
        if rr:
            parts.append(f"RR {float(rr):.1f}:1")

        rule_names: list[str] = []
        if isinstance(meta, dict):
            names = meta.get("passed_rule_names")
            if isinstance(names, list):
                rule_names = [str(name) for name in names if str(name).strip()]

        if rule_names:
            shown = ", ".join(rule_names[:5])
            extra = len(rule_names) - 5
            if extra > 0:
                shown += f" (+{extra} lainnya)"
            parts.append(f"Rules: {shown}")

        if not parts:
            return "Sinyal " + ("SHORT" if side == "SHORT" else "BUY") + " terdeteksi"

        return " | ".join(parts)

    def _send_telegram_report(self, event: dict[str, object], signal: dict[str, object] | None = None) -> None:
        """Send trade report to Telegram if notifier is configured"""
        if self.telegram_notifier is None:
            return
        
        from app.telegram.trade_reporter import send_trade_report
        
        try:
            event_with_signal = {**event, "signal": signal}
            send_trade_report(self.telegram_notifier, event_with_signal)
        except Exception:
            pass  # Silently skip if reporting fails

    def _now(self) -> str:
        return datetime.now(tz=UTC).isoformat()

    # ------------------------------------------------------------------
    # ACR+ bridge helpers (Opsi C - opsional, behind use_acr_position_manager)
    # ------------------------------------------------------------------

    def _extract_ltf_candles(
        self, signal: dict[str, object]
    ) -> list[Any]:
        """Ambil LTF candles dari signal (opsional).

        Signal boleh menyediakan key ``ltf_candles`` berisi list of dict
        dengan minimal ``open, high, low, close, timestamp, volume``, atau
        list of ``Candle`` langsung. Return list ``Candle`` atau ``[]`` bila
        tidak tersedia / tidak valid.
        """
        raw = signal.get("ltf_candles")
        if not raw or not isinstance(raw, list):
            return []
        try:
            from app.core.models import Candle as _Candle
        except Exception:
            return []
        result: list[Any] = []
        symbol = str(signal.get("symbol", "UNKNOWN"))
        for item in raw:
            if isinstance(item, _Candle):
                result.append(item)
                continue
            if not isinstance(item, dict):
                continue
            try:
                result.append(_Candle(
                    symbol=str(item.get("symbol", symbol)),
                    timestamp=str(item.get("timestamp", "")),
                    open=float(item["open"]),
                    high=float(item["high"]),
                    low=float(item["low"]),
                    close=float(item["close"]),
                    volume=float(item.get("volume", 0.0)),
                ))
            except (KeyError, TypeError, ValueError):
                continue
        return result

    def _apply_acr_management(
        self, position: dict[str, object], ltf_candles: list[Any]
    ) -> None:
        """Terapkan break-even + trailing swing-based bila TP1 sudah hit."""
        try:
            from app.strategies.acr_engine_bridge import (
                apply_acr_breakeven,
                apply_acr_trailing,
            )
        except Exception:
            return
        buffer_pct = float(self.config.auto_exit.acr_trail_buffer_pct)
        apply_acr_breakeven(position)
        # An explicit dashboard percentage is authoritative for trailing
        # distance. Keep ACR breakeven/invalidation, but do not replace the
        # percentage trail with a swing-derived level.
        if self.config.trailing_stop_percent is None:
            apply_acr_trailing(position, ltf_candles, buffer_pct=buffer_pct)

    def _check_acr_invalidation(
        self, position: dict[str, object], ltf_candles: list[Any]
    ) -> str | None:
        """Cek invalidation (CISD/pattern lawan arah). Return alasan atau None."""
        try:
            from app.strategies.acr_engine_bridge import check_acr_invalidation
        except Exception:
            return None
        return check_acr_invalidation(position, ltf_candles)