"""Configuration model for USDⓈ-M Futures deployment.

Loaded from ``configs/futures.json``. Kept separate from ``configs/live.json``
so the existing spot flow keeps working while futures is opt-in via
``enabled=true``.

Schema (all fields optional except where noted):

- ``enabled`` (bool) — master switch. If False the bootstrap is skipped.
- ``venue`` — must be ``"usdm_futures"`` (only supported for now).
- ``network`` — ``"mainnet"`` | ``"testnet"``.
- ``position_mode`` — ``"one_way"`` | ``"hedge"``.
- ``multi_assets_margin`` (bool) — collateral in multiple assets.
- ``margin_type`` — ``"ISOLATED"`` | ``"CROSSED"``. Applied to every symbol.
- ``default_leverage`` (int, 1..125) — default per-symbol leverage.
- ``symbols`` (dict) — per-symbol overrides ``{symbol: {leverage: int,
  margin_type: str}}``.
- ``recv_window`` (int, ms).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.exchange.binance_futures.client import FuturesEndpoint
from app.exchange.binance_futures.leverage import MarginType, PositionMode


DEFAULT_CONFIG_PATH = Path("configs/futures.json")


@dataclass(frozen=True)
class FuturesSymbolConfig:
    symbol: str
    leverage: int
    margin_type: MarginType


@dataclass(frozen=True)
class FuturesConfig:
    enabled: bool = False
    venue: str = "usdm_futures"
    network: str = "testnet"
    position_mode: PositionMode = PositionMode.ONE_WAY
    multi_assets_margin: bool = False
    margin_type: MarginType = MarginType.ISOLATED
    default_leverage: int = 3
    symbols: tuple[FuturesSymbolConfig, ...] = field(default_factory=tuple)
    recv_window: int = 5000

    @property
    def endpoint(self) -> FuturesEndpoint:
        return (
            FuturesEndpoint.MAINNET
            if self.network.lower() == "mainnet"
            else FuturesEndpoint.TESTNET
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FuturesConfig":
        venue = str(data.get("venue", "usdm_futures")).lower()
        if venue != "usdm_futures":
            raise ValueError(
                f"venue={venue!r} not supported; only 'usdm_futures' is implemented"
            )

        network = str(data.get("network", "testnet")).lower()
        if network not in {"mainnet", "testnet"}:
            raise ValueError("network must be 'mainnet' or 'testnet'")

        mode_raw = str(data.get("position_mode", "one_way")).lower()
        if mode_raw not in {"one_way", "hedge"}:
            raise ValueError("position_mode must be 'one_way' or 'hedge'")
        position_mode = (
            PositionMode.HEDGE if mode_raw == "hedge" else PositionMode.ONE_WAY
        )

        margin_type = _parse_margin_type(data.get("margin_type", "ISOLATED"))
        default_leverage = _parse_leverage(data.get("default_leverage", 3))
        recv_window = int(data.get("recv_window", 5000))
        if not 0 < recv_window <= 60_000:
            raise ValueError("recv_window must be within (0, 60000]")

        symbols_raw = data.get("symbols", {}) or {}
        if not isinstance(symbols_raw, dict):
            raise ValueError("symbols must be a mapping")
        symbol_configs = tuple(
            FuturesSymbolConfig(
                symbol=str(sym).upper(),
                leverage=_parse_leverage(
                    entry.get("leverage", default_leverage)
                    if isinstance(entry, dict)
                    else default_leverage
                ),
                margin_type=(
                    _parse_margin_type(entry.get("margin_type", margin_type.value))
                    if isinstance(entry, dict)
                    else margin_type
                ),
            )
            for sym, entry in symbols_raw.items()
        )

        return cls(
            enabled=bool(data.get("enabled", False)),
            venue=venue,
            network=network,
            position_mode=position_mode,
            multi_assets_margin=bool(data.get("multi_assets_margin", False)),
            margin_type=margin_type,
            default_leverage=default_leverage,
            symbols=symbol_configs,
            recv_window=recv_window,
        )

    @classmethod
    def load(cls, path: str | Path = DEFAULT_CONFIG_PATH) -> "FuturesConfig":
        target = Path(path)
        if not target.exists():
            return cls()
        data = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{target} must contain a JSON object")
        return cls.from_dict(data)


def _parse_margin_type(value: Any) -> MarginType:
    text = str(value).upper()
    if text not in {"ISOLATED", "CROSSED"}:
        raise ValueError("margin_type must be 'ISOLATED' or 'CROSSED'")
    return MarginType(text)


def _parse_leverage(value: Any) -> int:
    leverage = int(value)
    if not 1 <= leverage <= 125:
        raise ValueError("leverage must be within [1, 125]")
    return leverage
