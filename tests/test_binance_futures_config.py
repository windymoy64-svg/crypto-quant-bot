from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.exchange.binance_futures.config import FuturesConfig, FuturesSymbolConfig
from app.exchange.binance_futures.leverage import MarginType, PositionMode
from app.exchange.binance_futures.client import FuturesEndpoint


def test_defaults_are_safe() -> None:
    config = FuturesConfig()

    assert config.enabled is False
    assert config.venue == "usdm_futures"
    assert config.network == "testnet"
    assert config.position_mode is PositionMode.ONE_WAY
    assert config.margin_type is MarginType.ISOLATED
    assert config.default_leverage == 3
    assert config.symbols == ()
    assert config.endpoint is FuturesEndpoint.TESTNET


def test_from_dict_full() -> None:
    config = FuturesConfig.from_dict(
        {
            "enabled": True,
            "network": "mainnet",
            "position_mode": "hedge",
            "multi_assets_margin": True,
            "margin_type": "CROSSED",
            "default_leverage": 5,
            "symbols": {
                "btcusdt": {"leverage": 10, "margin_type": "ISOLATED"},
                "ETHUSDT": {},
            },
            "recv_window": 3000,
        }
    )

    assert config.enabled is True
    assert config.network == "mainnet"
    assert config.endpoint is FuturesEndpoint.MAINNET
    assert config.position_mode is PositionMode.HEDGE
    assert config.multi_assets_margin is True
    assert config.margin_type is MarginType.CROSSED
    assert config.default_leverage == 5
    assert config.recv_window == 3000

    by_symbol = {s.symbol: s for s in config.symbols}
    assert by_symbol["BTCUSDT"].leverage == 10
    assert by_symbol["BTCUSDT"].margin_type is MarginType.ISOLATED
    # Fallbacks: entry omits both -> use defaults.
    assert by_symbol["ETHUSDT"].leverage == 5
    assert by_symbol["ETHUSDT"].margin_type is MarginType.CROSSED


def test_from_dict_rejects_unsupported_venue() -> None:
    with pytest.raises(ValueError, match="venue"):
        FuturesConfig.from_dict({"venue": "coinm_futures"})


def test_from_dict_rejects_invalid_network() -> None:
    with pytest.raises(ValueError, match="network"):
        FuturesConfig.from_dict({"network": "sandbox"})


def test_from_dict_rejects_invalid_position_mode() -> None:
    with pytest.raises(ValueError, match="position_mode"):
        FuturesConfig.from_dict({"position_mode": "dual"})


def test_from_dict_rejects_invalid_margin_type() -> None:
    with pytest.raises(ValueError, match="margin_type"):
        FuturesConfig.from_dict({"margin_type": "PORTFOLIO"})


def test_from_dict_rejects_invalid_leverage() -> None:
    with pytest.raises(ValueError, match="leverage"):
        FuturesConfig.from_dict({"default_leverage": 0})
    with pytest.raises(ValueError, match="leverage"):
        FuturesConfig.from_dict({"default_leverage": 200})


def test_from_dict_rejects_invalid_recv_window() -> None:
    with pytest.raises(ValueError, match="recv_window"):
        FuturesConfig.from_dict({"recv_window": 0})
    with pytest.raises(ValueError, match="recv_window"):
        FuturesConfig.from_dict({"recv_window": 120_000})


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    config = FuturesConfig.load(tmp_path / "does_not_exist.json")

    assert config.enabled is False
    assert config.symbols == ()


def test_load_parses_file(tmp_path: Path) -> None:
    path = tmp_path / "futures.json"
    path.write_text(
        json.dumps(
            {
                "enabled": True,
                "default_leverage": 4,
                "symbols": {"BTCUSDT": {"leverage": 8}},
            }
        )
    )

    config = FuturesConfig.load(path)

    assert config.enabled is True
    assert config.symbols[0] == FuturesSymbolConfig(
        symbol="BTCUSDT", leverage=8, margin_type=MarginType.ISOLATED
    )


def test_load_rejects_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "futures.json"
    path.write_text("[]")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        FuturesConfig.load(path)
