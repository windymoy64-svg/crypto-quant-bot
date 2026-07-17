from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.bootstrap import apply_futures_settings
from app.exchange.binance_futures.client import FuturesHttpError, FuturesHttpResponse
from app.exchange.binance_futures.config import FuturesConfig
from app.exchange.binance_futures.leverage import MarginType, PositionMode


class _StubClient:
    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._responses = responses or {}
        self.errors: dict[str, FuturesHttpError] = {}

    def post(self, path, params=None, *, signed=True):  # noqa: ARG002
        self.calls.append((path, dict(params or {})))
        if path in self.errors:
            raise self.errors[path]
        return FuturesHttpResponse(
            status_code=200, body=self._responses.get(path, {})
        )

    def get(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("get should not be called during bootstrap")

    def delete(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("delete should not be called during bootstrap")


def test_bootstrap_skips_when_disabled() -> None:
    stub = _StubClient()
    report = apply_futures_settings(FuturesConfig(enabled=False), stub)

    assert report.skipped is True
    assert stub.calls == []
    assert report.ok is True


def test_bootstrap_applies_position_mode_and_multi_assets() -> None:
    stub = _StubClient()
    config = FuturesConfig.from_dict(
        {
            "enabled": True,
            "position_mode": "hedge",
            "multi_assets_margin": True,
        }
    )

    report = apply_futures_settings(config, stub)

    paths = [call[0] for call in stub.calls]
    assert "/fapi/v1/positionSide/dual" in paths
    assert "/fapi/v1/multiAssetsMargin" in paths
    assert report.position_mode is not None
    assert report.position_mode.mode is PositionMode.HEDGE
    assert report.multi_assets_changed is True
    assert report.ok is True


def test_bootstrap_applies_per_symbol_leverage_and_margin_type() -> None:
    stub = _StubClient(
        responses={
            "/fapi/v1/leverage": {
                "symbol": "BTCUSDT",
                "leverage": 5,
                "maxNotionalValue": "1000000",
            }
        }
    )
    config = FuturesConfig.from_dict(
        {
            "enabled": True,
            "default_leverage": 5,
            "symbols": {
                "BTCUSDT": {"leverage": 5, "margin_type": "ISOLATED"},
            },
        }
    )

    report = apply_futures_settings(config, stub)

    margin_paths = [c for c in stub.calls if c[0] == "/fapi/v1/marginType"]
    leverage_paths = [c for c in stub.calls if c[0] == "/fapi/v1/leverage"]
    assert margin_paths[0][1]["symbol"] == "BTCUSDT"
    assert margin_paths[0][1]["marginType"] == "ISOLATED"
    assert leverage_paths[0][1] == {"symbol": "BTCUSDT", "leverage": 5}

    assert report.leverage_results[0].symbol == "BTCUSDT"
    assert report.leverage_results[0].leverage == 5
    assert report.margin_type_results[0].margin_type is MarginType.ISOLATED
    assert report.ok is True


def test_bootstrap_swallows_no_change_errors() -> None:
    stub = _StubClient()
    stub.errors["/fapi/v1/positionSide/dual"] = FuturesHttpError(
        status_code=400,
        code=-4059,
        message="No need to change position side.",
        path="/fapi/v1/positionSide/dual",
    )
    stub.errors["/fapi/v1/marginType"] = FuturesHttpError(
        status_code=400,
        code=-4046,
        message="No need to change margin type.",
        path="/fapi/v1/marginType",
    )
    stub.errors["/fapi/v1/leverage"] = FuturesHttpError(
        status_code=400,
        code=-4028,
        message="Leverage not modified",
        path="/fapi/v1/leverage",
    )
    config = FuturesConfig.from_dict(
        {
            "enabled": True,
            "symbols": {"BTCUSDT": {"leverage": 3}},
        }
    )

    report = apply_futures_settings(config, stub)

    assert report.ok is True
    assert report.position_mode is not None
    assert report.position_mode.unchanged is True
    assert report.margin_type_results[0].unchanged is True
    assert report.leverage_results[0].unchanged is True


def test_bootstrap_records_hard_errors() -> None:
    stub = _StubClient()
    stub.errors["/fapi/v1/leverage"] = FuturesHttpError(
        status_code=400,
        code=-1121,
        message="Invalid symbol.",
        path="/fapi/v1/leverage",
    )
    config = FuturesConfig.from_dict(
        {
            "enabled": True,
            "symbols": {"UNKNOWN": {"leverage": 3}},
        }
    )

    report = apply_futures_settings(config, stub)

    assert report.ok is False
    assert any("UNKNOWN leverage" in err for err in report.errors)
    # Margin type still succeeded even though leverage failed.
    assert report.margin_type_results[0].symbol == "UNKNOWN"


def test_bootstrap_without_symbols_still_applies_account_settings() -> None:
    stub = _StubClient()
    config = FuturesConfig.from_dict({"enabled": True})

    report = apply_futures_settings(config, stub)

    paths = [call[0] for call in stub.calls]
    assert "/fapi/v1/positionSide/dual" in paths
    assert "/fapi/v1/multiAssetsMargin" in paths
    assert "/fapi/v1/marginType" not in paths  # no symbols configured
    assert "/fapi/v1/leverage" not in paths
    assert report.ok is True
