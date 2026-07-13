from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.core.models import Candle, TradingSignal
from app.events.events import (
    PaperBalanceUpdated,
    PaperOrderCreated,
    PaperOrderFilled,
    PaperPositionClosed,
    PaperPositionOpened,
    SignalCreated,
)
from app.events.publisher import publish
from app.execution.order import OrderSide
from app.execution.simulator import ExecutionSettings, ExecutionSimulator
from app.exchange.binance.stream import BinanceStreamCallbacks
from app.exchange.binance.websocket import BinanceWebSocket
from app.market.data_service import MarketDataService
from app.paper.fills import PaperFill
from app.paper.orders import PaperOrder, paper_order_from_execution
from app.paper.persistence import PaperPersistence, PaperState
from app.portfolio.manager import PortfolioManager
from app.risk.manager import RiskDecision, RiskManager, RiskSettings
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


@dataclass(frozen=True)
class PaperEngineConfig:
    enabled: bool = True
    exchange: str = "binance"
    symbols: list[str] = field(default_factory=lambda: ["BTC/USDT"])
    timeframe: str = "1h"
    limit: int = 120
    min_window: int = 30
    starting_balance: float = 10_000.0
    rules_path: str = "configs/rules.json"
    weights_path: str | None = "configs/rule_weights.json"
    market_regime: str | None = None
    state_path: str = "logs/paper_state.json"
    events_path: str = "logs/paper_events.jsonl"
    fallback_to_sample_data: bool = True
    maker_fee_rate: float = 0.0002
    taker_fee_rate: float = 0.001
    slippage_basis_points: float = 5.0
    spread_basis_points: float = 2.0
    latency_candles: int = 0
    max_fill_ratio: float = 1.0
    min_fill_ratio: float = 0.25
    risk_per_trade_percent: float = 2.0  # Update dari 1.0% ke 2.0%
    max_position_size_percent: float = 15.0  # Satu posisi max 15% balance — aggressive setting
    max_exposure_percent: float = 95.0
    max_open_positions: int = 3
    max_daily_drawdown_percent: float = 5.0
    min_risk_reward: float = 2.0  # Update dari 1.2 ke 2.0 (RR 1:2)
    min_atr_percent: float = 0.0
    max_atr_percent: float = 25.0
    realtime_timeframe: str = "1m"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PaperEngineConfig":
        return cls(
            enabled=bool(data.get("enabled", True)),
            exchange=str(data.get("exchange", "binance")),
            symbols=[str(symbol) for symbol in data.get("symbols", ["BTC/USDT"])],
            timeframe=str(data.get("timeframe", "1h")),
            limit=int(data.get("limit", 120)),
            min_window=int(data.get("min_window", 30)),
            starting_balance=float(data.get("starting_balance", 10_000.0)),
            rules_path=str(data.get("rules_path", "configs/rules.json")),
            weights_path=cls._optional_path(data.get("weights_path", "configs/rule_weights.json")),
            market_regime=cls._optional_path(data.get("market_regime")),
            state_path=str(data.get("state_path", "logs/paper_state.json")),
            events_path=str(data.get("events_path", "logs/paper_events.jsonl")),
            fallback_to_sample_data=bool(data.get("fallback_to_sample_data", True)),
            maker_fee_rate=float(data.get("maker_fee_rate", 0.0002)),
            taker_fee_rate=float(data.get("taker_fee_rate", 0.001)),
            slippage_basis_points=float(data.get("slippage_basis_points", 5.0)),
            spread_basis_points=float(data.get("spread_basis_points", 2.0)),
            latency_candles=int(data.get("latency_candles", 0)),
            max_fill_ratio=float(data.get("max_fill_ratio", 1.0)),
            min_fill_ratio=float(data.get("min_fill_ratio", 0.25)),
            risk_per_trade_percent=float(data.get("risk_per_trade_percent", 1.0)),
            max_position_size_percent=float(data.get("max_position_size_percent", 95.0)),
            max_exposure_percent=float(data.get("max_exposure_percent", 95.0)),
            max_open_positions=int(data.get("max_open_positions", 3)),
            max_daily_drawdown_percent=float(data.get("max_daily_drawdown_percent", 5.0)),
            min_risk_reward=float(data.get("min_risk_reward", 1.2)),
            min_atr_percent=float(data.get("min_atr_percent", 0.0)),
            max_atr_percent=float(data.get("max_atr_percent", 25.0)),
            realtime_timeframe=str(data.get("realtime_timeframe", "1m")),
        )

    @staticmethod
    def _optional_path(value: object) -> str | None:
        if value in (None, ""):
            return None
        return str(value)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PaperEngineResult:
    config: PaperEngineConfig
    enabled: bool
    data_sources: dict[str, str]
    signals: list[dict[str, object]]
    orders: list[dict[str, object]]
    fills: list[dict[str, object]]
    risk: dict[str, object]
    portfolio: dict[str, object]
    state_path: str
    events_path: str

    def to_dict(self) -> dict[str, object]:
        return {
            "config": self.config.to_dict(),
            "enabled": self.enabled,
            "data_sources": self.data_sources,
            "signals": self.signals,
            "orders": self.orders,
            "fills": self.fills,
            "risk": self.risk,
            "portfolio": self.portfolio,
            "state_path": self.state_path,
            "events_path": self.events_path,
        }


class PaperTradingEngine:
    def __init__(
        self,
        market_data: MarketDataService | None = None,
        score_engine: ScoreEngine | None = None,
        risk_manager: RiskManager | None = None,
        execution: ExecutionSimulator | None = None,
        persistence: PaperPersistence | None = None,
    ) -> None:
        self.market_data = market_data
        self.score_engine = score_engine
        self.risk_manager = risk_manager
        self.execution = execution
        self.persistence = persistence

    def run_once(self, config: PaperEngineConfig) -> PaperEngineResult:
        persistence = self.persistence or PaperPersistence(config.state_path, config.events_path)
        state = persistence.load_state(config.starting_balance)
        portfolio = state.to_portfolio()
        if not config.enabled:
            return self._result(config, {}, [], [], [], [], portfolio, state, persistence)

        market_data = self.market_data or MarketDataService(
            exchange=config.exchange,
            fallback_to_sample_data=config.fallback_to_sample_data,
        )
        score_engine = self.score_engine or ScoreEngine.from_json(config.rules_path, self._existing_optional_path(config.weights_path))
        self.risk_manager = self.risk_manager or RiskManager(self._risk_settings(config))
        self.execution = self.execution or ExecutionSimulator(self._execution_settings(config))

        data_sources: dict[str, str] = {}
        signals: list[dict[str, object]] = []
        new_orders: list[dict[str, object]] = []
        new_fills: list[dict[str, object]] = []
        risk_decisions: list[RiskDecision] = []

        for symbol in config.symbols:
            result = market_data.fetch_ohlcv(symbol, config.timeframe, config.limit)
            candles = result.candles
            data_sources[symbol] = result.source
            if len(candles) < max(2, config.min_window):
                continue

            current = candles[-1]
            portfolio.update_price(symbol, current.close)
            signal = self._build_signal(symbol, candles, score_engine, config, current)
            signal_payload = signal.to_dict()
            signal_payload["timestamp"] = current.timestamp
            signals.append(signal_payload)
            self._maybe_close_position(symbol, signal, current, candles, portfolio, persistence, new_orders, new_fills)
            if signal.action == "BUY" and symbol not in portfolio.positions:
                decision = self._evaluate_risk(symbol, signal, candles, portfolio, current.timestamp)
                risk_decisions.append(decision)
                if decision.approved:
                    self._open_position(symbol, signal, decision, candles, portfolio, persistence, new_orders, new_fills)

        updated_at = self._latest_timestamp(signals)
        saved_state = PaperState.from_portfolio(
            portfolio,
            orders=[*state.orders, *new_orders],
            fills=[*state.fills, *new_fills],
            updated_at=updated_at,
        )
        persistence.save_state(saved_state)
        self._publish_balance(portfolio, updated_at)
        return self._result(config, data_sources, signals, new_orders, new_fills, risk_decisions, portfolio, saved_state, persistence)

    def create_realtime_stream(
        self,
        config: PaperEngineConfig,
        callbacks: BinanceStreamCallbacks | None = None,
    ) -> BinanceWebSocket:
        market_data = self.market_data or MarketDataService(config.exchange, fallback_to_sample_data=config.fallback_to_sample_data)
        return market_data.create_realtime_stream(config.symbols, timeframe=config.realtime_timeframe, callbacks=callbacks)

    def _build_signal(
        self,
        symbol: str,
        candles: list[Candle],
        score_engine: ScoreEngine,
        config: PaperEngineConfig,
        current: Candle,
    ) -> TradingSignal:
        score = score_engine.score(candles, config.market_regime)
        signal = build_signal(symbol, candles, score)
        publish(
            SignalCreated(
                symbol=symbol,
                action=signal.action,
                score=signal.score,
                confidence=signal.confidence,
                timestamp=current.timestamp,
                signal=signal.to_dict(),
            )
        )
        return signal

    def _evaluate_risk(
        self,
        symbol: str,
        signal: TradingSignal,
        candles: list[Candle],
        portfolio: PortfolioManager,
        timestamp: str,
    ) -> RiskDecision:
        if self.risk_manager is None:
            raise RuntimeError("risk manager is not initialized")
        take_profit = signal.take_profit[0] if signal.take_profit else signal.entry
        return self.risk_manager.evaluate_entry(
            symbol=symbol,
            timestamp=timestamp,
            candles=candles,
            cash=portfolio.available_balance,
            equity=portfolio.equity,
            entry=signal.entry,
            stop_loss=signal.stop_loss,
            take_profit=take_profit,
            open_positions=portfolio.open_positions_count,
            current_exposure=portfolio.market_value,
        )

    def _open_position(
        self,
        symbol: str,
        signal: TradingSignal,
        decision: RiskDecision,
        candles: list[Candle],
        portfolio: PortfolioManager,
        persistence: PaperPersistence,
        orders: list[dict[str, object]],
        fills: list[dict[str, object]],
    ) -> None:
        order = paper_order_from_execution(
            symbol=symbol,
            side="BUY",
            quantity=decision.quantity,
            requested_price=signal.entry,
            created_at=candles[-1].timestamp,
            meta={"source": "paper_trading", "risk": decision.to_dict()},
        )
        self._publish_order(order, persistence, orders)
        fill = self._execute(order, OrderSide.BUY, candles)
        if fill is None:
            return
        self._publish_fill(fill, persistence, fills)
        portfolio.open_position(symbol, fill.quantity, fill.price, fill.fee, fill.timestamp)
        position = portfolio.positions.get(symbol)
        publish(
            PaperPositionOpened(
                symbol=symbol,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                timestamp=fill.timestamp,
                position=position.to_dict(fill.price) if position else {},
            )
        )

    def _maybe_close_position(
        self,
        symbol: str,
        signal: TradingSignal,
        current: Candle,
        candles: list[Candle],
        portfolio: PortfolioManager,
        persistence: PaperPersistence,
        orders: list[dict[str, object]],
        fills: list[dict[str, object]],
    ) -> None:
        position = portfolio.positions.get(symbol)
        if position is None:
            return
        exit_price = None
        reason = ""
        if current.low <= signal.stop_loss:
            exit_price = signal.stop_loss
            reason = "STOP_LOSS"
        elif signal.take_profit and current.high >= signal.take_profit[0]:
            exit_price = signal.take_profit[0]
            reason = "TAKE_PROFIT"
        elif signal.action == "SKIP":
            exit_price = current.close
            reason = "SIGNAL_EXIT"
        if exit_price is None:
            return

        order = paper_order_from_execution(
            symbol=symbol,
            side="SELL",
            quantity=position.quantity,
            requested_price=exit_price,
            created_at=current.timestamp,
            reason=reason,
            meta={"source": "paper_trading"},
        )
        self._publish_order(order, persistence, orders)
        fill = self._execute(order, OrderSide.SELL, candles)
        if fill is None:
            return
        self._publish_fill(fill, persistence, fills)
        realized_pnl = portfolio.close_position(symbol, fill.quantity, fill.price, fill.fee, fill.timestamp)
        publish(
            PaperPositionClosed(
                symbol=symbol,
                quantity=fill.quantity,
                price=fill.price,
                fee=fill.fee,
                realized_pnl=realized_pnl,
                timestamp=fill.timestamp,
                position={"symbol": symbol, "close_reason": reason},
            )
        )

    def _execute(self, order: PaperOrder, side: OrderSide, candles: list[Candle]) -> PaperFill | None:
        if self.execution is None:
            raise RuntimeError("execution simulator is not initialized")
        result = self.execution.execute_market_order(
            symbol=order.symbol,
            side=side,
            quantity=order.quantity,
            requested_price=order.requested_price,
            signal_index=len(candles) - 1,
            candles=candles,
        )
        return PaperFill.from_fill_result(order.order_id, result)

    def _publish_order(self, order: PaperOrder, persistence: PaperPersistence, orders: list[dict[str, object]]) -> None:
        payload = order.to_dict()
        orders.append(payload)
        persistence.record_order(order)
        publish(
            PaperOrderCreated(
                order_id=order.order_id,
                symbol=order.symbol,
                side=order.side,
                order_type=order.order_type,
                quantity=order.quantity,
                requested_price=order.requested_price,
                timestamp=order.created_at,
                order=payload,
            )
        )

    def _publish_fill(self, fill: PaperFill, persistence: PaperPersistence, fills: list[dict[str, object]]) -> None:
        payload = fill.to_dict()
        fills.append(payload)
        persistence.record_fill(fill)
        publish(
            PaperOrderFilled(
                order_id=fill.order_id,
                symbol=fill.symbol,
                side=fill.side,
                quantity=fill.quantity,
                price=fill.price,
                notional=fill.notional,
                fee=fill.fee,
                status=fill.status,
                timestamp=fill.timestamp,
                fill=payload,
            )
        )

    def _publish_balance(self, portfolio: PortfolioManager, timestamp: str) -> None:
        publish(
            PaperBalanceUpdated(
                balance=portfolio.account.cash,
                equity=portfolio.equity,
                available_balance=portfolio.available_balance,
                used_capital=portfolio.used_capital,
                timestamp=timestamp,
                account=portfolio.account.to_dict(),
            )
        )

    def _result(
        self,
        config: PaperEngineConfig,
        data_sources: dict[str, str],
        signals: list[dict[str, object]],
        orders: list[dict[str, object]],
        fills: list[dict[str, object]],
        risk_decisions: list[RiskDecision],
        portfolio: PortfolioManager,
        state: PaperState,
        persistence: PaperPersistence,
    ) -> PaperEngineResult:
        return PaperEngineResult(
            config=config,
            enabled=config.enabled,
            data_sources=data_sources,
            signals=signals,
            orders=orders,
            fills=fills,
            risk={
                "summary": self.risk_manager.summary(risk_decisions) if self.risk_manager else {},
                "decisions": [decision.to_dict() for decision in risk_decisions],
            },
            portfolio=portfolio.summary() if config.enabled else state.to_dict(),
            state_path=str(persistence.state_path),
            events_path=str(persistence.events_path),
        )

    def _execution_settings(self, config: PaperEngineConfig) -> ExecutionSettings:
        return ExecutionSettings(
            maker_fee_rate=config.maker_fee_rate,
            taker_fee_rate=config.taker_fee_rate,
            slippage_basis_points=config.slippage_basis_points,
            spread_basis_points=config.spread_basis_points,
            latency_candles=config.latency_candles,
            max_fill_ratio=config.max_fill_ratio,
            min_fill_ratio=config.min_fill_ratio,
        )

    def _risk_settings(self, config: PaperEngineConfig) -> RiskSettings:
        return RiskSettings(
            risk_per_trade_percent=config.risk_per_trade_percent,
            max_position_size_percent=config.max_position_size_percent,
            max_exposure_percent=config.max_exposure_percent,
            max_open_positions=config.max_open_positions,
            max_daily_drawdown_percent=config.max_daily_drawdown_percent,
            min_risk_reward=config.min_risk_reward,
            min_atr_percent=config.min_atr_percent,
            max_atr_percent=config.max_atr_percent,
        )

    def _existing_optional_path(self, path: str | None) -> str | None:
        if not path:
            return None
        return path if Path(path).exists() else None

    def _latest_timestamp(self, signals: list[dict[str, object]]) -> str:
        if not signals:
            return ""
        return str(signals[-1].get("timestamp", ""))