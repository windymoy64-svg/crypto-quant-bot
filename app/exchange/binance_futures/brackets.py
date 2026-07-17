"""Leverage bracket helpers for USDⓈ-M Futures risk math.

The bracket table returned by ``GET /fapi/v1/leverageBracket`` describes
maintenance margin tiers per symbol:

- ``bracket`` — the tier index.
- ``initialLeverage`` — the max initial leverage allowed in this tier.
- ``notionalCap`` / ``notionalFloor`` — the notional value range (USDT).
- ``maintMarginRatio`` — the maintenance margin rate (MMR).
- ``cum`` — cumulative maintenance amount (a constant offset used by the
  Binance liquidation formula).

Given a notional value we pick the tier where ``notionalFloor <= notional
< notionalCap``. That tier's MMR and cumulative offset feed into the
liquidation price formula (see ``risk_math.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.exchange.binance_futures.client import FuturesHttpClient


@dataclass(frozen=True)
class LeverageBracket:
    bracket: int
    initial_leverage: int
    notional_floor: float
    notional_cap: float
    maint_margin_ratio: float
    cumulative: float

    def contains(self, notional: float) -> bool:
        return self.notional_floor <= notional < self.notional_cap


@dataclass(frozen=True)
class SymbolBrackets:
    symbol: str
    brackets: tuple[LeverageBracket, ...]

    def bracket_for(self, notional: float) -> LeverageBracket:
        if notional < 0:
            raise ValueError("notional must be non-negative")
        for entry in self.brackets:
            if entry.contains(notional):
                return entry
        # Fallback: return the highest tier if notional exceeds the cap.
        return self.brackets[-1]


class FuturesLeverageBracketReader:
    """Wraps ``GET /fapi/v1/leverageBracket``.

    Results are cached per instance to avoid hammering the endpoint. The
    cache is process-local; long-running services should recreate the reader
    every few hours to pick up bracket changes announced by Binance.
    """

    def __init__(self, client: FuturesHttpClient) -> None:
        self._client = client
        self._cache: dict[str, SymbolBrackets] = {}
        self._all_loaded = False

    def get(self, symbol: str, *, refresh: bool = False) -> SymbolBrackets:
        symbol_key = symbol.upper()
        if not refresh and symbol_key in self._cache:
            return self._cache[symbol_key]
        response = self._client.get(
            "/fapi/v1/leverageBracket", {"symbol": symbol_key}
        )
        rows = response.body if isinstance(response.body, list) else []
        if not rows:
            raise ValueError(f"no leverage bracket returned for {symbol_key}")
        parsed = _parse_symbol_entry(rows[0])
        self._cache[symbol_key] = parsed
        return parsed

    def all(self, *, refresh: bool = False) -> dict[str, SymbolBrackets]:
        if self._all_loaded and not refresh:
            return dict(self._cache)
        response = self._client.get("/fapi/v1/leverageBracket")
        rows = response.body if isinstance(response.body, list) else []
        out: dict[str, SymbolBrackets] = {}
        for entry in rows:
            if not isinstance(entry, dict):
                continue
            parsed = _parse_symbol_entry(entry)
            out[parsed.symbol] = parsed
        self._cache = out
        self._all_loaded = True
        return dict(out)


def _parse_symbol_entry(entry: dict[str, Any]) -> SymbolBrackets:
    symbol = str(entry.get("symbol", "")).upper()
    if not symbol:
        raise ValueError("bracket entry missing 'symbol'")
    brackets_raw = entry.get("brackets", []) or []
    if not isinstance(brackets_raw, list) or not brackets_raw:
        raise ValueError(f"bracket entry for {symbol} has no tiers")
    tiers = tuple(
        _parse_bracket(bracket)
        for bracket in brackets_raw
        if isinstance(bracket, dict)
    )
    # Binance returns brackets ordered by ascending bracket index / notional.
    ordered = tuple(sorted(tiers, key=lambda b: b.bracket))
    return SymbolBrackets(symbol=symbol, brackets=ordered)


def _parse_bracket(entry: dict[str, Any]) -> LeverageBracket:
    return LeverageBracket(
        bracket=int(entry.get("bracket", 0)),
        initial_leverage=int(entry.get("initialLeverage", 0)),
        notional_floor=float(entry.get("notionalFloor", 0.0)),
        notional_cap=float(entry.get("notionalCap", 0.0)),
        maint_margin_ratio=float(entry.get("maintMarginRatio", 0.0)),
        cumulative=float(entry.get("cum", 0.0)),
    )
