"""Reader for ``GET /fapi/v1/exchangeInfo``.

Exposes the symbol filters we actually use for order validation:

- ``LOT_SIZE.stepSize`` / ``minQty`` / ``maxQty`` — quantity granularity.
- ``PRICE_FILTER.tickSize`` — price granularity.
- ``MIN_NOTIONAL.notional`` — minimum notional value per order.
- ``MARKET_LOT_SIZE.stepSize`` — some symbols enforce a distinct market step.
- ``contractType`` — ``PERPETUAL`` vs quarterly deliveries.
- ``status`` — trading status (``TRADING`` etc.).

Everything else in the response (rateLimits, timezone, futures-specific
``symbols[].filters[].filterType``) is preserved via ``raw`` for callers
that want to inspect it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from app.exchange.binance_futures.client import FuturesHttpClient


@dataclass(frozen=True)
class FuturesSymbolInfo:
    symbol: str
    status: str
    contract_type: str
    base_asset: str
    quote_asset: str
    margin_asset: str
    price_precision: int
    quantity_precision: int
    tick_size: float
    step_size: float
    market_step_size: float
    min_qty: float
    max_qty: float
    min_notional: float
    order_types: tuple[str, ...]
    raw: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_perpetual(self) -> bool:
        return self.contract_type.upper() == "PERPETUAL"

    @property
    def is_trading(self) -> bool:
        return self.status.upper() == "TRADING"


class FuturesExchangeInfoReader:
    """Fetches and caches ``/fapi/v1/exchangeInfo``.

    The exchange info payload is large (~1MB) so callers should reuse a
    single reader across requests. Call :meth:`refresh` when Binance
    announces symbol filter changes.
    """

    def __init__(self, client: FuturesHttpClient) -> None:
        self._client = client
        self._cache: dict[str, FuturesSymbolInfo] = {}
        self._loaded = False

    def get(self, symbol: str, *, refresh: bool = False) -> FuturesSymbolInfo:
        if refresh or not self._loaded:
            self.refresh()
        key = symbol.upper()
        if key not in self._cache:
            raise KeyError(f"symbol not present in exchangeInfo: {key!r}")
        return self._cache[key]

    def all(self, *, refresh: bool = False) -> dict[str, FuturesSymbolInfo]:
        if refresh or not self._loaded:
            self.refresh()
        return dict(self._cache)

    def refresh(self) -> None:
        response = self._client.get("/fapi/v1/exchangeInfo", signed=False)
        payload = response.body if isinstance(response.body, dict) else {}
        symbols = payload.get("symbols", []) if isinstance(payload, dict) else []
        parsed: dict[str, FuturesSymbolInfo] = {}
        for entry in symbols:
            if not isinstance(entry, dict):
                continue
            info = _parse_symbol(entry)
            parsed[info.symbol] = info
        self._cache = parsed
        self._loaded = True



def _parse_symbol(entry: dict[str, Any]) -> FuturesSymbolInfo:
    filters = {
        str(f.get("filterType", "")): f
        for f in entry.get("filters", [])
        if isinstance(f, dict)
    }
    lot = filters.get("LOT_SIZE", {})
    market_lot = filters.get("MARKET_LOT_SIZE", lot)
    price_filter = filters.get("PRICE_FILTER", {})
    min_notional = filters.get("MIN_NOTIONAL", {})

    return FuturesSymbolInfo(
        symbol=str(entry.get("symbol", "")).upper(),
        status=str(entry.get("status", "")),
        contract_type=str(entry.get("contractType", "")),
        base_asset=str(entry.get("baseAsset", "")),
        quote_asset=str(entry.get("quoteAsset", "")),
        margin_asset=str(entry.get("marginAsset", entry.get("quoteAsset", ""))),
        price_precision=int(entry.get("pricePrecision", 0) or 0),
        quantity_precision=int(entry.get("quantityPrecision", 0) or 0),
        tick_size=_as_float(price_filter.get("tickSize")),
        step_size=_as_float(lot.get("stepSize")),
        market_step_size=_as_float(market_lot.get("stepSize", lot.get("stepSize"))),
        min_qty=_as_float(lot.get("minQty")),
        max_qty=_as_float(lot.get("maxQty")),
        min_notional=_as_float(min_notional.get("notional")),
        order_types=tuple(
            str(t)
            for t in entry.get("orderTypes", [])
            if isinstance(t, (str, bytes))
        ),
        raw=entry,
    )


def _as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
