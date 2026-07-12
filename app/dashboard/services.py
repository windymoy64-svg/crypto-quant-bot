from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.analytics import AnalyticsConfig, AnalyticsEngine
from app.market.data_service import MarketDataService
from app.monitoring import system_health_monitor
from app.portfolio.sync import PortfolioSynchronizer


logger = logging.getLogger(__name__)
portfolio_synchronizer = PortfolioSynchronizer()
_DYNAMIC_SYMBOLS_CACHE: list[str] = []
_DYNAMIC_SYMBOLS_TS: float = 0.0

SUPPORTED_TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")
DEFAULT_KLINE_SYMBOL = "BTC/USDT"
DEFAULT_KLINE_TIMEFRAME = "1h"
DEFAULT_KLINE_LIMIT = 200
MAX_KLINE_LIMIT = 1000
DEFAULT_DASHBOARD_SYMBOLS = (
    "BTC/USDT",
    "ETH/USDT",
    "BNB/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "ADA/USDT",
    "DOGE/USDT",
    "TRX/USDT",
    "TON/USDT",
    "AVAX/USDT",
    "SHIB/USDT",
    "DOT/USDT",
    "LINK/USDT",
    "BCH/USDT",
    "NEAR/USDT",
    "MATIC/USDT",
    "LTC/USDT",
    "UNI/USDT",
    "ICP/USDT",
    "APT/USDT",
    "ETC/USDT",
    "ATOM/USDT",
    "FIL/USDT",
    "HBAR/USDT",
    "ARB/USDT",
    "OP/USDT",
    "INJ/USDT",
    "SUI/USDT",
    "SEI/USDT",
    "TIA/USDT",
    "RUNE/USDT",
    "AAVE/USDT",
    "MKR/USDT",
    "RENDER/USDT",
    "FET/USDT",
    "GRT/USDT",
    "ALGO/USDT",
    "XLM/USDT",
    "VET/USDT",
    "EOS/USDT",
)
SYMBOL_CONFIG_PATHS = (
    Path("configs/market_scan.json"),
    Path("configs/paper.json"),
    Path("configs/paper_trading.json"),
    Path("configs/live_trading.json"),
    Path("configs/live.json"),
)


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def read_json_file(path: str | Path, default: Any) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    try:
        return json.loads(target.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default


def read_jsonl_file(path: str | Path, limit: int = 100) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8-sig").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows[-limit:]


class DashboardService:
    def market(self) -> dict[str, Any]:
        latest = read_json_file("logs/latest_signals.json", {})

        signals = (
            latest.get("signals", [])
            if isinstance(latest, dict)
            else []
        )
        short_signals = (
            latest.get("short_signals", [])
            if isinstance(latest, dict)
            else []
        )
        # Sinyal untuk posisi terbuka yang keluar dari top N tetap dikirim
        # agar harganya tetap realtime di dashboard.
        tracked_signals = (
            latest.get("tracked_signals", [])
            if isinstance(latest, dict)
            else []
        )

        if not isinstance(signals, list):
            signals = []

        if not isinstance(short_signals, list):
            short_signals = []

        if not isinstance(tracked_signals, list):
            tracked_signals = []

        symbols = self.symbols()

        return {
            "timestamp": (
                latest.get("timestamp")
                if isinstance(latest, dict)
                else None
            ),
            "signals": signals,
            "count": len(signals),
            "short_signals": short_signals,
            "short_count": len(short_signals),
            "tracked_signals": tracked_signals,
            "tracked_count": len(tracked_signals),
            "symbols": symbols["symbols"],
            "symbol_count": symbols["count"],
            "configured_symbols": symbols["configured_symbols"],
            "read_only": True,
        }


    def symbols(self) -> dict[str, Any]:
        configured = self._load_symbols_from_configs()
        dynamic = self._load_dynamic_symbols()
        symbols = self._dedupe_symbols([*dynamic, *configured, *DEFAULT_DASHBOARD_SYMBOLS])
        return {
            "symbols": symbols,
            "configured_symbols": configured,
            "count": len(symbols),
            "read_only": True,
        }

    def _load_dynamic_symbols(self) -> list[str]:
        config = read_json_file("configs/market_scan.json", {})
        if not isinstance(config, dict) or str(config.get("symbol_mode", "static")) != "all":
            return []
        global _DYNAMIC_SYMBOLS_CACHE, _DYNAMIC_SYMBOLS_TS
        now = datetime.now(UTC).timestamp()
        if _DYNAMIC_SYMBOLS_CACHE and (now - _DYNAMIC_SYMBOLS_TS) < 300:
            return _DYNAMIC_SYMBOLS_CACHE
        try:
            from app.exchange.public_http_client import PublicHttpExchangeClient
            client = PublicHttpExchangeClient(str(config.get("exchange", "binance")))
            fetched = client.fetch_all_symbols(quote_asset=str(config.get("quote_asset", "USDT")))
        except Exception:
            logger.exception("Gagal ambil simbol dinamis untuk dashboard")
            return _DYNAMIC_SYMBOLS_CACHE or []
        _DYNAMIC_SYMBOLS_CACHE = fetched
        _DYNAMIC_SYMBOLS_TS = now
        return fetched

    def portfolio(self) -> dict[str, Any]:
        paper = self.paper()
        account = paper.get("account", {}) if isinstance(paper.get("account"), dict) else {}
        open_positions = paper.get("open_positions", [])
        if not isinstance(open_positions, list):
            open_positions = []
        base = {
            "timestamp": paper.get("updated_at"),
            "equity": paper.get("equity", account.get("cash", paper.get("balance", 0.0))),
            "available_balance": paper.get("available_balance", account.get("available_balance", paper.get("balance", 0.0))),
            "open_positions": open_positions,
            "open_positions_count": len(open_positions),
            "source": "paper_state",
            "read_only": True,
        }
        return portfolio_synchronizer.sync_from_lifecycle(base, self.live_orders())

    def live_orders(self) -> dict[str, Any]:
        snapshot = read_json_file("logs/live_orders.json", {})
        if not isinstance(snapshot, dict):
            snapshot = {}
        return {
            "open_orders": snapshot.get("open_orders", []) if isinstance(snapshot.get("open_orders"), list) else [],
            "filled_orders": snapshot.get("filled_orders", []) if isinstance(snapshot.get("filled_orders"), list) else [],
            "rejected_orders": snapshot.get("rejected_orders", []) if isinstance(snapshot.get("rejected_orders"), list) else [],
            "order_history": snapshot.get("order_history", []) if isinstance(snapshot.get("order_history"), list) else [],
            "read_only": True,
        }

    def paper(self) -> dict[str, Any]:
        state = read_json_file("logs/paper_state.json", {})
        if not isinstance(state, dict):
            state = {}
        positions = self._normalize_positions(state.get("positions", state.get("open_positions", [])))
        fills = state.get("fills", []) if isinstance(state.get("fills"), list) else []
        orders = state.get("orders", []) if isinstance(state.get("orders"), list) else []
        account = state.get("account", {}) if isinstance(state.get("account"), dict) else {}
        balance = state.get("balance", account.get("cash", 0.0))

        # Baca trade tertutup dari paper_trades.jsonl (ditulis oleh auto-exit engine)
        trade_events = read_jsonl_file("logs/paper_trades.jsonl", limit=500)
        closed_trades: list[dict[str, Any]] = []
        all_exits: list[dict[str, Any]] = []
        for ev in trade_events:
            t = ev.get("type")
            if t not in ("closed", "partial_close"):
                continue
            pos = ev.get("position") or {}
            pnl = pos.get("realized_pnl") if t == "closed" else pos.get("partial_realized_pnl", 0)
            entry = {
                "symbol": ev.get("symbol"),
                "pnl": float(pnl or 0),
                "reason": ev.get("reason"),
                "closed_at": ev.get("timestamp"),
                "type": t,
            }
            all_exits.append(entry)
            if t == "closed":
                closed_trades.append(entry)

        # Kalau state.fills kosong, pakai closed_trades sebagai fills — supaya panel LIVE terisi
        effective_fills = fills if fills else closed_trades

        return {
            "created_at": state.get("created_at"),
            "updated_at": state.get("updated_at"),
            "starting_balance": state.get("starting_balance", account.get("initial_balance", 0.0)),
            "balance": balance,
            "equity": state.get("equity", balance),
            "available_balance": account.get("available_balance", balance),
            "account": account,
            "open_positions": positions,
            "orders": orders[-100:],
            "fills": effective_fills[-100:],
            "trades": closed_trades[-100:],
            "events": read_jsonl_file("logs/paper_events.jsonl", limit=100),
            "read_only": True,
        }

    def backtest(self) -> dict[str, Any]:
        directory = Path("logs/backtests")
        files: list[dict[str, Any]] = []
        if directory.exists():
            for path in sorted(directory.glob("*.json"))[-25:]:
                data = read_json_file(path, {})
                files.append({
                    "path": str(path),
                    "updated_at": datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(),
                    "summary": self._backtest_summary(data),
                })
        return {"results": files, "count": len(files), "read_only": True}

    def analytics(self) -> dict[str, Any]:
        report = read_json_file("logs/analytics_report.json", {})
        if isinstance(report, dict) and report:
            report["read_only"] = True
            return report
        config_path = Path("configs/analytics.json")
        config = AnalyticsConfig.from_json(config_path) if config_path.exists() else AnalyticsConfig()
        generated = AnalyticsEngine().build_report(config).to_dict()
        generated["read_only"] = True
        generated["generated_at"] = utc_now_iso()
        return generated

    def health(self) -> dict[str, Any]:
        system = system_health_monitor.snapshot()
        return {
            "status": "ok",
            "service": "dashboard",
            "read_only": True,
            "timestamp": utc_now_iso(),
            "system": system,
            "cpu": system.get("cpu"),
            "ram": system.get("ram"),
            "disk": system.get("disk"),
            "latency_ms": system.get("latency_ms"),
            "api_status": system.get("api_status"),
            "websocket_status": system.get("websocket_status"),
            "exchange_status": system.get("exchange_status"),
            "uptime_seconds": system.get("uptime_seconds"),
            "sqlite": system.get("sqlite"),
            "binance_connectivity": system.get("binance_connectivity"),
            "artifacts": {
                "latest_signals": Path("logs/latest_signals.json").exists(),
                "paper_state": Path("logs/paper_state.json").exists(),
                "portfolio_state": Path("logs/portfolio_state.json").exists(),
                "analytics_report": Path("logs/analytics_report.json").exists(),
                "backtests_dir": Path("logs/backtests").exists(),
            },
        }

    def klines(
        self,
        symbol: str | None = None,
        timeframe: str | None = None,
        limit: int | None = None,
        exchange: str = "binance",
    ) -> dict[str, Any]:
        resolved_symbol = self._resolve_kline_symbol(symbol)
        resolved_timeframe = self._resolve_kline_timeframe(timeframe)
        resolved_limit = self._resolve_kline_limit(limit)

        service = MarketDataService(exchange=exchange, fallback_to_sample_data=True)
        try:
            result = service.fetch_ohlcv(
                symbol=resolved_symbol,
                timeframe=resolved_timeframe,
                limit=resolved_limit,
            )
        except Exception as exc:
            logger.exception("Failed to fetch klines for %s", resolved_symbol)
            return {
                "symbol": resolved_symbol,
                "timeframe": resolved_timeframe,
                "limit": resolved_limit,
                "source": "error",
                "warning": str(exc),
                "candles": [],
                "count": 0,
                "read_only": True,
            }

        candles = [self._candle_to_dict(candle) for candle in result.candles]
        return {
            "symbol": resolved_symbol,
            "timeframe": resolved_timeframe,
            "limit": resolved_limit,
            "source": result.source,
            "warning": result.warning,
            "candles": candles,
            "count": len(candles),
            "read_only": True,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "market": self.market(),
            "portfolio": self.portfolio(),
            "live_orders": self.live_orders(),
            "paper": self.paper(),
            "backtest": self.backtest(),
            "analytics": self.analytics(),
            "health": self.health(),
            "read_only": True,
        }

    def _resolve_kline_symbol(self, symbol: str | None) -> str:
        raw = (symbol or "").strip()
        if not raw:
            return DEFAULT_KLINE_SYMBOL
        return raw.upper().replace("-", "/")

    def _load_symbols_from_configs(self) -> list[str]:
        symbols: list[str] = []
        for path in SYMBOL_CONFIG_PATHS:
            data = read_json_file(path, {})
            if not isinstance(data, dict):
                continue
            symbols.extend(self._extract_symbols(data.get("symbols")))
            symbols.extend(self._extract_symbols(data.get("allowed_symbols")))
            symbols.extend(self._extract_symbols(data.get("watchlist")))
        return self._dedupe_symbols(symbols)

    def _extract_symbols(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        symbols: list[str] = []
        for item in value:
            if isinstance(item, str):
                raw = item.strip()
            elif isinstance(item, dict):
                raw = str(item.get("symbol", "")).strip()
            else:
                continue
            if raw:
                symbols.append(raw.upper().replace("-", "/"))
        return symbols

    def _dedupe_symbols(self, symbols: list[str] | tuple[str, ...]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for symbol in symbols:
            normalized = str(symbol).strip().upper().replace("-", "/")
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    def _resolve_kline_timeframe(self, timeframe: str | None) -> str:
        raw = (timeframe or "").strip().lower()
        if raw in SUPPORTED_TIMEFRAMES:
            return raw
        return DEFAULT_KLINE_TIMEFRAME

    def _resolve_kline_limit(self, limit: int | None) -> int:
        try:
            value = int(limit) if limit is not None else DEFAULT_KLINE_LIMIT
        except (TypeError, ValueError):
            return DEFAULT_KLINE_LIMIT
        if value <= 0:
            return DEFAULT_KLINE_LIMIT
        return min(value, MAX_KLINE_LIMIT)

    def _candle_to_dict(self, candle: Any) -> dict[str, Any]:
        timestamp = getattr(candle, "timestamp", "")
        return {
            "symbol": getattr(candle, "symbol", ""),
            "timestamp": timestamp,
            "time": self._timestamp_to_unix(timestamp),
            "open": float(getattr(candle, "open", 0.0)),
            "high": float(getattr(candle, "high", 0.0)),
            "low": float(getattr(candle, "low", 0.0)),
            "close": float(getattr(candle, "close", 0.0)),
            "volume": float(getattr(candle, "volume", 0.0)),
        }

    def _timestamp_to_unix(self, timestamp: str) -> int:
        if not timestamp:
            return 0
        try:
            normalized = str(timestamp).replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return 0
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return int(parsed.timestamp())

    def _normalize_positions(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            positions: list[dict[str, Any]] = []
            for symbol, data in value.items():
                if isinstance(data, dict):
                    positions.append({"symbol": symbol, **data})
                else:
                    positions.append({"symbol": symbol, "value": data})
            return positions
        return []

    def _backtest_summary(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {}
        metrics = data.get("metrics", {}) if isinstance(data.get("metrics"), dict) else {}
        trades = data.get("trades", []) if isinstance(data.get("trades"), list) else []
        equity = data.get("equity_curve", []) if isinstance(data.get("equity_curve"), list) else []
        return {
            "symbol": data.get("symbol"),
            "timeframe": data.get("timeframe"),
            "trades_count": len(trades),
            "equity_points": len(equity),
            "metrics": metrics,
        }


dashboard_service = DashboardService()
