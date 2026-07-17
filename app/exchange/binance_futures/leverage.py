"""Wrapper around Binance USDⓈ-M Futures leverage & margin endpoints.

Covers:
- ``POST /fapi/v1/leverage`` — set initial leverage (1x-125x, per symbol).
- ``POST /fapi/v1/marginType`` — ISOLATED vs CROSSED per symbol.
- ``POST /fapi/v1/positionSide/dual`` — hedge vs one-way position mode.
- ``POST /fapi/v1/multiAssetsMargin`` — single vs multi-asset collateral.

Binance returns ``code -4046`` ("no need to change margin type") or
``code -4059`` ("no need to change position side") when the requested state
already matches the account setting. Both are treated as a successful no-op
so callers can invoke these methods idempotently at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.exchange.binance_futures.client import FuturesHttpClient, FuturesHttpError


class MarginType(str, Enum):
    ISOLATED = "ISOLATED"
    CROSSED = "CROSSED"


class PositionMode(str, Enum):
    ONE_WAY = "one_way"
    HEDGE = "hedge"

    @property
    def dual_side(self) -> bool:
        return self is PositionMode.HEDGE


# Binance error codes we intentionally swallow when idempotent.
_NO_CHANGE_MARGIN_TYPE = -4046
_NO_CHANGE_POSITION_SIDE = -4059
_NO_CHANGE_MULTI_ASSETS = -4171
_NO_CHANGE_LEVERAGE_CODES = frozenset({-4028})


@dataclass(frozen=True)
class LeverageChangeResult:
    symbol: str
    leverage: int
    max_notional_value: str | None
    unchanged: bool


@dataclass(frozen=True)
class MarginTypeChangeResult:
    symbol: str
    margin_type: MarginType
    unchanged: bool


@dataclass(frozen=True)
class PositionModeChangeResult:
    mode: PositionMode
    unchanged: bool


class FuturesLeverageManager:
    """High-level wrapper for leverage / margin type / position mode changes."""

    def __init__(self, client: FuturesHttpClient) -> None:
        self._client = client

    def set_leverage(self, symbol: str, leverage: int) -> LeverageChangeResult:
        if not symbol:
            raise ValueError("symbol is required")
        if not 1 <= leverage <= 125:
            raise ValueError("leverage must be within [1, 125]")
        try:
            response = self._client.post(
                "/fapi/v1/leverage",
                {"symbol": symbol.upper(), "leverage": leverage},
            )
        except FuturesHttpError as exc:
            if exc.code in _NO_CHANGE_LEVERAGE_CODES:
                return LeverageChangeResult(
                    symbol=symbol.upper(),
                    leverage=leverage,
                    max_notional_value=None,
                    unchanged=True,
                )
            raise
        payload = response.body if isinstance(response.body, dict) else {}
        return LeverageChangeResult(
            symbol=str(payload.get("symbol", symbol.upper())),
            leverage=int(payload.get("leverage", leverage)),
            max_notional_value=(
                str(payload["maxNotionalValue"])
                if "maxNotionalValue" in payload
                else None
            ),
            unchanged=False,
        )

    def set_margin_type(
        self, symbol: str, margin_type: MarginType
    ) -> MarginTypeChangeResult:
        if not symbol:
            raise ValueError("symbol is required")
        try:
            self._client.post(
                "/fapi/v1/marginType",
                {"symbol": symbol.upper(), "marginType": margin_type.value},
            )
        except FuturesHttpError as exc:
            if exc.code == _NO_CHANGE_MARGIN_TYPE:
                return MarginTypeChangeResult(
                    symbol=symbol.upper(),
                    margin_type=margin_type,
                    unchanged=True,
                )
            raise
        return MarginTypeChangeResult(
            symbol=symbol.upper(),
            margin_type=margin_type,
            unchanged=False,
        )

    def set_position_mode(self, mode: PositionMode) -> PositionModeChangeResult:
        try:
            self._client.post(
                "/fapi/v1/positionSide/dual",
                {"dualSidePosition": mode.dual_side},
            )
        except FuturesHttpError as exc:
            if exc.code == _NO_CHANGE_POSITION_SIDE:
                return PositionModeChangeResult(mode=mode, unchanged=True)
            raise
        return PositionModeChangeResult(mode=mode, unchanged=False)

    def set_multi_assets_margin(self, enabled: bool) -> bool:
        """Return ``True`` on change, ``False`` when already in target state."""

        try:
            self._client.post(
                "/fapi/v1/multiAssetsMargin",
                {"multiAssetsMargin": enabled},
            )
        except FuturesHttpError as exc:
            if exc.code == _NO_CHANGE_MULTI_ASSETS:
                return False
            raise
        return True
