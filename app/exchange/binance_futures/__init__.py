"""Binance USDⓈ-M Futures REST adapter.

Only exposes read + configuration endpoints. Order submission is intentionally
kept out of this initial rollout so leverage/margin type wiring can be
verified against testnet before enabling any live order flow.
"""

from __future__ import annotations

from app.exchange.binance_futures.account import (
    FuturesAccountReader,
    FuturesAccountSnapshot,
    FuturesBalance,
    FuturesPosition,
)
from app.exchange.binance_futures.client import (
    FuturesEndpoint,
    FuturesHttpClient,
    FuturesHttpError,
)
from app.exchange.binance_futures.bootstrap import (
    FuturesBootstrapReport,
    apply_futures_settings,
)
from app.exchange.binance_futures.brackets import (
    FuturesLeverageBracketReader,
    LeverageBracket,
    SymbolBrackets,
)
from app.exchange.binance_futures.config import (
    FuturesConfig,
    FuturesSymbolConfig,
)
from app.exchange.binance_futures.exchange_info import (
    FuturesExchangeInfoReader,
    FuturesSymbolInfo,
)
from app.exchange.binance_futures.lifecycle import bootstrap_futures_if_enabled
from app.exchange.binance_futures.risk_math import (
    LiquidationEstimate,
    PositionDirection,
    estimate_liquidation,
    initial_margin,
    liquidation_price,
    maintenance_margin,
)
from app.exchange.binance_futures.sizing import (
    FuturesSizingResult,
    SizingRejection,
    size_position,
)
from app.exchange.binance_futures.leverage import (
    FuturesLeverageManager,
    LeverageChangeResult,
    MarginType,
    MarginTypeChangeResult,
    PositionMode,
    PositionModeChangeResult,
)
from app.exchange.binance_futures.orders import (
    FuturesLiveSafetyGate,
    FuturesOrderRequest,
    FuturesOrderResult,
    FuturesOrderSubmissionEngine,
    OrderSide,
    OrderType,
    PositionSide,
    TimeInForce,
    WorkingType,
)


__all__ = [
    "FuturesAccountReader",
    "FuturesAccountSnapshot",
    "FuturesBalance",
    "FuturesBootstrapReport",
    "FuturesConfig",
    "FuturesEndpoint",
    "FuturesExchangeInfoReader",
    "FuturesHttpClient",
    "FuturesHttpError",
    "FuturesLeverageBracketReader",
    "FuturesLeverageManager",
    "FuturesLiveSafetyGate",
    "FuturesOrderRequest",
    "FuturesOrderResult",
    "FuturesOrderSubmissionEngine",
    "FuturesPosition",
    "FuturesSizingResult",
    "FuturesSymbolConfig",
    "FuturesSymbolInfo",
    "LeverageBracket",
    "LeverageChangeResult",
    "LiquidationEstimate",
    "MarginType",
    "MarginTypeChangeResult",
    "OrderSide",
    "OrderType",
    "PositionDirection",
    "PositionMode",
    "PositionModeChangeResult",
    "PositionSide",
    "SizingRejection",
    "SymbolBrackets",
    "TimeInForce",
    "WorkingType",
    "apply_futures_settings",
    "bootstrap_futures_if_enabled",
    "estimate_liquidation",
    "initial_margin",
    "liquidation_price",
    "maintenance_margin",
    "size_position",
]
