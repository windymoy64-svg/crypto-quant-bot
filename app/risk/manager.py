from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.core.models import Candle
from app.events.events import RiskApproved, RiskRejected
from app.events.publisher import publish
from app.risk.drawdown import DailyDrawdownGuard
from app.risk.exposure import ExposureGuard
from app.risk.position_size import PositionSizeRequest, PositionSizer
from app.risk.stoploss import StopLossValidator
from app.risk.takeprofit import RiskRewardValidator
from app.risk.volatility import ATRVolatilityFilter


def calculate_position_size(
    account_balance: float,
    risk_percent: float,
    entry: float,
    stop_loss: float,
    max_position_percent: float = 25.0,
) -> float:
    """Hitung size posisi dengan dua batasan wajib:
    1. Risk per trade: (entry - SL) × size ≤ balance × risk_percent
    2. Notional cap: size × entry ≤ balance × max_position_percent
    """
    if account_balance <= 0:
        raise ValueError("account_balance must be positive")
    if risk_percent <= 0:
        raise ValueError("risk_percent must be positive")

    risk_per_unit = abs(entry - stop_loss)
    if risk_per_unit == 0:
        return 0.0
    if entry <= 0:
        return 0.0

    # Batas 1: risk-based sizing
    amount_to_risk = account_balance * (risk_percent / 100)
    size_by_risk = amount_to_risk / risk_per_unit

    # Batas 2: notional cap (posisi tidak boleh > X% dari balance)
    max_notional = account_balance * (max_position_percent / 100)
    size_by_notional = max_notional / entry

    # Ambil yang lebih kecil — mana yang lebih ketat
    size = min(size_by_risk, size_by_notional)

    # Batas 3: SL terlalu dekat (< 0.5% dari entry) → tolak
    sl_distance_pct = (risk_per_unit / entry) * 100
    if sl_distance_pct < 0.5:
        return 0.0

    return round(size, 8)


@dataclass(frozen=True)
class RiskSettings:
    risk_per_trade_percent: float = 2.0  # Naik dari 1.0% ke 2.0% untuk RR 1:2
    max_position_size_percent: float = 95.0
    max_exposure_percent: float = 95.0
    max_open_positions: int = 1
    max_daily_drawdown_percent: float = 5.0
    min_risk_reward: float = 2.0  # Update dari 1.2 ke 2.0 (RR 1:2)
    min_atr_percent: float = 0.0
    max_atr_percent: float = 25.0


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    symbol: str
    timestamp: str
    requested_entry: float
    stop_loss: float
    take_profit: float
    quantity: float = 0.0
    notional: float = 0.0
    risk_amount: float = 0.0
    risk_reward: float = 0.0
    atr_percent: float = 0.0
    current_exposure: float = 0.0
    max_exposure: float = 0.0
    open_positions: int = 0
    daily_drawdown_percent: float = 0.0
    checks: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RiskManager:
    def __init__(self, settings: RiskSettings | None = None) -> None:
        self.settings = settings or RiskSettings()
        self.position_sizer = PositionSizer()
        self.stoploss = StopLossValidator()
        self.takeprofit = RiskRewardValidator(self.settings.min_risk_reward)
        self.exposure = ExposureGuard(self.settings.max_exposure_percent, self.settings.max_open_positions)
        self.drawdown = DailyDrawdownGuard(self.settings.max_daily_drawdown_percent)
        self.volatility = ATRVolatilityFilter(self.settings.min_atr_percent, self.settings.max_atr_percent)

    def evaluate_entry(
        self,
        *,
        symbol: str,
        timestamp: str,
        candles: list[Candle],
        cash: float,
        equity: float,
        entry: float,
        stop_loss: float,
        take_profit: float,
        open_positions: int,
        current_exposure: float,
    ) -> RiskDecision:
        self.drawdown.record_equity(timestamp, equity)
        max_exposure = self.exposure.max_exposure(equity)
        checks: dict[str, object] = {}

        stop_check = self.stoploss.validate_long(entry, stop_loss)
        checks["stop_loss"] = stop_check.to_dict()
        if not stop_check.valid:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, "invalid_stop_loss", checks)

        rr_check = self.takeprofit.validate_long(entry, stop_loss, take_profit)
        checks["risk_reward"] = rr_check.to_dict()
        if not rr_check.valid:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, "risk_reward_too_low", checks)

        exposure_check = self.exposure.validate(open_positions, current_exposure, equity)
        checks["exposure"] = exposure_check.to_dict()
        if not exposure_check.valid:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, exposure_check.reason, checks)

        drawdown_check = self.drawdown.validate(timestamp, equity)
        checks["drawdown"] = drawdown_check.to_dict()
        if not drawdown_check.valid:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, "daily_drawdown_limit", checks)

        volatility_check = self.volatility.validate(candles)
        checks["volatility"] = volatility_check.to_dict()
        if not volatility_check.valid:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, volatility_check.reason, checks)

        max_notional = min(
            cash * (self.settings.max_position_size_percent / 100),
            max(max_exposure - current_exposure, 0.0),
        )
        sizing = self.position_sizer.size(
            PositionSizeRequest(
                equity=equity,
                cash=cash,
                risk_percent=self.settings.risk_per_trade_percent,
                entry=entry,
                stop_loss=stop_loss,
                max_notional=max_notional,
            )
        )
        checks["position_size"] = sizing.to_dict()
        if sizing.quantity <= 0:
            return self._reject(symbol, timestamp, entry, stop_loss, take_profit, "position_size_zero", checks)

        decision = RiskDecision(
            approved=True,
            reason="approved",
            symbol=symbol,
            timestamp=timestamp,
            requested_entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            quantity=sizing.quantity,
            notional=sizing.notional,
            risk_amount=sizing.risk_amount,
            risk_reward=rr_check.ratio,
            atr_percent=volatility_check.atr_percent,
            current_exposure=current_exposure,
            max_exposure=max_exposure,
            open_positions=open_positions,
            daily_drawdown_percent=drawdown_check.drawdown_percent,
            checks=checks,
        )
        publish(
            RiskApproved(
                symbol=decision.symbol,
                timestamp=decision.timestamp,
                quantity=decision.quantity,
                notional=decision.notional,
                reason=decision.reason,
                decision=decision.to_dict(),
            )
        )
        return decision

    def summary(self, decisions: list[RiskDecision]) -> dict[str, object]:
        approvals = sum(1 for decision in decisions if decision.approved)
        rejections = len(decisions) - approvals
        reasons: dict[str, int] = {}
        for decision in decisions:
            reasons[decision.reason] = reasons.get(decision.reason, 0) + 1
        return {
            "decisions": len(decisions),
            "approved": approvals,
            "rejected": rejections,
            "reasons": reasons,
            "settings": asdict(self.settings),
        }

    def _reject(
        self,
        symbol: str,
        timestamp: str,
        entry: float,
        stop_loss: float,
        take_profit: float,
        reason: str,
        checks: dict[str, object],
    ) -> RiskDecision:
        decision = RiskDecision(
            approved=False,
            reason=reason,
            symbol=symbol,
            timestamp=timestamp,
            requested_entry=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            checks=checks,
        )
        publish(
            RiskRejected(
                symbol=decision.symbol,
                timestamp=decision.timestamp,
                reason=decision.reason,
                decision=decision.to_dict(),
            )
        )
        return decision
