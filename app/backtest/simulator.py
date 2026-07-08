from __future__ import annotations

from dataclasses import dataclass, replace

from app.backtest.equity import EquityCurveBuilder, EquityPoint
from app.backtest.trade import BacktestTrade
from app.core.models import Candle, TradingSignal
from app.events.events import SignalCreated
from app.events.publisher import publish
from app.execution.order import OrderSide
from app.execution.simulator import ExecutionSettings, ExecutionSimulator
from app.portfolio.manager import PortfolioManager
from app.risk.manager import RiskDecision, RiskManager, RiskSettings
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


@dataclass(frozen=True)
class BacktestPosition:
    symbol: str
    quantity: float
    entry_time: str
    entry_price: float
    stop_loss: float
    take_profit: float
    entry_fee: float


@dataclass(frozen=True)
class SimulationResult:
    trades: list[BacktestTrade]
    equity_curve: list[EquityPoint]
    signals_seen: int
    final_cash: float
    risk: dict[str, object]
    portfolio: dict[str, object]


class BacktestSimulator:
    def __init__(
        self,
        *,
        initial_cash: float = 10_000.0,
        position_size_percent: float = 95.0,
        fee_rate: float = 0.001,
        min_window: int = 30,
        execution_settings: ExecutionSettings | None = None,
        risk_settings: RiskSettings | None = None,
    ) -> None:
        self.initial_cash = initial_cash
        self.position_size_percent = position_size_percent
        self.fee_rate = fee_rate
        self.min_window = max(2, min_window)
        self.execution = ExecutionSimulator(
            execution_settings or ExecutionSettings(taker_fee_rate=fee_rate, maker_fee_rate=fee_rate)
        )
        self.risk = RiskManager(
            risk_settings or RiskSettings(max_position_size_percent=position_size_percent)
        )

    def run(self, symbol: str, candles: list[Candle], score_engine: ScoreEngine) -> SimulationResult:
        if len(candles) < self.min_window:
            raise ValueError(f"not enough candles for backtest: need {self.min_window}, got {len(candles)}")

        cash = self.initial_cash
        portfolio = PortfolioManager.with_cash(self.initial_cash)
        position: BacktestPosition | None = None
        trades: list[BacktestTrade] = []
        equity = EquityCurveBuilder(self.initial_cash)
        risk_decisions: list[RiskDecision] = []
        signals_seen = 0

        for index in range(self.min_window - 1, len(candles)):
            current = candles[index]
            portfolio.update_price(symbol, current.close)
            window = candles[: index + 1]
            score = score_engine.score(window)
            signal = build_signal(symbol, window, score)
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
            signals_seen += 1

            if position is not None:
                exit_price, exit_reason = self._exit_decision(position, signal, current)
                if exit_price is not None:
                    trade, cash, position = self._close_position(
                        position,
                        exit_price,
                        exit_reason,
                        cash,
                        index,
                        candles,
                        portfolio,
                    )
                    if trade is not None:
                        trades.append(trade)
            elif signal.action == "BUY":
                take_profit = signal.take_profit[0] if signal.take_profit else signal.entry
                decision = self.risk.evaluate_entry(
                    symbol=symbol,
                    timestamp=current.timestamp,
                    candles=window,
                    cash=portfolio.available_balance,
                    equity=portfolio.equity,
                    entry=signal.entry,
                    stop_loss=signal.stop_loss,
                    take_profit=take_profit,
                    open_positions=portfolio.open_positions_count,
                    current_exposure=portfolio.market_value,
                )
                risk_decisions.append(decision)
                if decision.approved:
                    position, cash = self._open_position(
                        symbol,
                        signal.entry,
                        signal,
                        cash,
                        index,
                        candles,
                        decision,
                        portfolio,
                    )

            cash = portfolio.account.cash
            equity.add(current.timestamp, portfolio.account.cash, portfolio.market_value)

        if position is not None:
            last = candles[-1]
            trade, cash, position = self._close_position(
                position,
                last.close,
                "END_OF_TEST",
                cash,
                len(candles) - 1,
                candles,
                portfolio,
            )
            if trade is not None:
                trades.append(trade)
            equity.add(last.timestamp, cash, 0.0)

        return SimulationResult(
            trades=trades,
            equity_curve=equity.points,
            signals_seen=signals_seen,
            final_cash=round(cash, 8),
            risk={
                "summary": self.risk.summary(risk_decisions),
                "decisions": [decision.to_dict() for decision in risk_decisions],
            },
            portfolio=portfolio.summary(),
        )

    def _open_position(
        self,
        symbol: str,
        entry_price: float,
        signal: TradingSignal,
        cash: float,
        signal_index: int,
        candles: list[Candle],
        risk_decision: RiskDecision,
        portfolio: PortfolioManager,
    ) -> tuple[BacktestPosition | None, float]:
        fill = self.execution.execute_market_order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=risk_decision.quantity,
            requested_price=entry_price,
            signal_index=signal_index,
            candles=candles,
        )
        if fill.filled_quantity <= 0:
            return None, cash

        position = BacktestPosition(
            symbol=symbol,
            quantity=fill.filled_quantity,
            entry_time=fill.fills[-1].timestamp,
            entry_price=fill.average_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit[0] if signal.take_profit else entry_price,
            entry_fee=fill.total_fee,
        )
        portfolio.open_position(symbol, fill.filled_quantity, fill.average_price, fill.total_fee, fill.fills[-1].timestamp)
        return position, portfolio.account.cash

    def _close_position(
        self,
        position: BacktestPosition,
        exit_price: float,
        exit_reason: str,
        cash: float,
        signal_index: int,
        candles: list[Candle],
        portfolio: PortfolioManager,
    ) -> tuple[BacktestTrade | None, float, BacktestPosition | None]:
        fill = self.execution.execute_market_order(
            symbol=position.symbol,
            side=OrderSide.SELL,
            quantity=position.quantity,
            requested_price=exit_price,
            signal_index=signal_index,
            candles=candles,
        )
        if fill.filled_quantity <= 0:
            return None, cash, position

        allocated_entry_fee = position.entry_fee * (fill.filled_quantity / position.quantity) if position.quantity else 0.0
        proceeds = fill.total_notional
        gross_pnl = (fill.average_price - position.entry_price) * fill.filled_quantity
        fees = allocated_entry_fee + fill.total_fee
        net_pnl = gross_pnl - fees
        cost_basis = fill.filled_quantity * position.entry_price
        return_percent = (net_pnl / cost_basis) * 100 if cost_basis else 0.0
        trade = BacktestTrade(
            symbol=position.symbol,
            entry_side="BUY",
            exit_side="SELL",
            quantity=round(fill.filled_quantity, 8),
            entry_time=position.entry_time,
            exit_time=fill.fills[-1].timestamp,
            entry_price=round(position.entry_price, 8),
            exit_price=round(fill.average_price, 8),
            gross_pnl=round(gross_pnl, 8),
            fees=round(fees, 8),
            net_pnl=round(net_pnl, 8),
            return_percent=round(return_percent, 4),
            exit_reason=exit_reason,
        )
        remaining_quantity = position.quantity - fill.filled_quantity
        remaining_position = None
        if remaining_quantity > 0:
            remaining_position = replace(
                position,
                quantity=remaining_quantity,
                entry_fee=position.entry_fee - allocated_entry_fee,
            )
        portfolio.close_position(position.symbol, fill.filled_quantity, fill.average_price, fill.total_fee, fill.fills[-1].timestamp)
        return trade, portfolio.account.cash, remaining_position

    def _exit_decision(
        self,
        position: BacktestPosition,
        signal: TradingSignal,
        candle: Candle,
    ) -> tuple[float | None, str | None]:
        if candle.low <= position.stop_loss:
            return position.stop_loss, "STOP_LOSS"
        if candle.high >= position.take_profit:
            return position.take_profit, "TAKE_PROFIT"
        if signal.action == "SKIP":
            return candle.close, "SIGNAL_EXIT"
        return None, None