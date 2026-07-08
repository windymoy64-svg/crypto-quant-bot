from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


DashboardProvider = Callable[[], dict[str, Any]]


@dataclass
class TelegramCommandResult:
    text: str
    control_action: str = "none"

    def to_dict(self) -> dict[str, str]:
        return {"text": self.text, "control_action": self.control_action}


class TelegramControlCenter:
    def __init__(self, snapshot_provider: DashboardProvider) -> None:
        self.snapshot_provider = snapshot_provider
        self.running = True

    def handle(self, command: str) -> TelegramCommandResult:
        name = command.strip().split()[0].lower() if command.strip() else "/help"
        routes = {
            "/status": self._status,
            "/portfolio": self._portfolio,
            "/orders": self._orders,
            "/signals": self._signals,
            "/pnl": self._pnl,
            "/start": self._start,
            "/stop": self._stop,
            "/restart": self._restart,
            "/help": self._help,
        }
        return routes.get(name, self._help)()

    def _status(self) -> TelegramCommandResult:
        health = self.snapshot_provider().get("health", {})
        return TelegramCommandResult(f"Status: {health.get('status', 'unknown')} | API {health.get('api_status')} | Exchange {health.get('exchange_status')}")

    def _portfolio(self) -> TelegramCommandResult:
        portfolio = self.snapshot_provider().get("portfolio", {})
        return TelegramCommandResult(f"Equity: {portfolio.get('equity', 0)} | Available: {portfolio.get('available_balance', 0)} | Positions: {portfolio.get('open_positions_count', 0)}")

    def _orders(self) -> TelegramCommandResult:
        orders = self.snapshot_provider().get("live_orders", {})
        return TelegramCommandResult(f"Orders open={len(orders.get('open_orders', []))} filled={len(orders.get('filled_orders', []))} rejected={len(orders.get('rejected_orders', []))}")

    def _signals(self) -> TelegramCommandResult:
        market = self.snapshot_provider().get("market", {})
        return TelegramCommandResult(f"Signals: {market.get('count', 0)} | Timestamp: {market.get('timestamp')}")

    def _pnl(self) -> TelegramCommandResult:
        analytics = self.snapshot_provider().get("analytics", {})
        performance = analytics.get("performance", {}) if isinstance(analytics, dict) else {}
        return TelegramCommandResult(f"PnL: net={performance.get('net_pnl', 0)} return={performance.get('return_percent', 0)}%")

    def _start(self) -> TelegramCommandResult:
        self.running = True
        return TelegramCommandResult("Control center started. Trading controls remain guarded by live config.", "start")

    def _stop(self) -> TelegramCommandResult:
        self.running = False
        return TelegramCommandResult("Control center stopped. No new operator actions will be accepted.", "stop")

    def _restart(self) -> TelegramCommandResult:
        self.running = True
        return TelegramCommandResult("Control center restart requested.", "restart")

    def _help(self) -> TelegramCommandResult:
        return TelegramCommandResult("Commands: /status /portfolio /orders /signals /pnl /start /stop /restart /help")


class TelegramNotificationFormatter:
    def format(self, event_type: str, payload: dict[str, Any] | None = None) -> str:
        payload = payload or {}
        labels = {
            "BUY": "BUY signal",
            "SELL": "SELL signal",
            "OrderFilled": "Order filled",
            "RiskReject": "Risk reject",
            "DrawdownAlert": "Drawdown alert",
            "ConnectionLost": "Connection lost",
            "Recovery": "Recovery",
        }
        symbol = payload.get("symbol") or payload.get("pair") or "system"
        return f"{labels.get(event_type, event_type)} | {symbol} | {payload}"
