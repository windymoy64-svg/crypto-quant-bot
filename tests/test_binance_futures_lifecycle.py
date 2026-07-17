from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.exchange.binance_futures import lifecycle as lifecycle_module
from app.exchange.binance_futures.bootstrap import FuturesBootstrapReport
from app.exchange.binance_futures.config import FuturesConfig


def _write_config(tmp_path: Path, payload: dict[str, Any]) -> Path:
    import json

    path = tmp_path / "futures.json"
    path.write_text(json.dumps(payload))
    return path


def test_bootstrap_returns_none_when_config_missing(tmp_path: Path) -> None:
    result = lifecycle_module.bootstrap_futures_if_enabled(
        tmp_path / "does_not_exist.json"
    )
    assert result is None


def test_bootstrap_returns_none_when_disabled(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"enabled": False})

    result = lifecycle_module.bootstrap_futures_if_enabled(path)

    assert result is None


def test_bootstrap_returns_none_when_credentials_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(tmp_path, {"enabled": True})
    monkeypatch.setattr(lifecycle_module, "_load_credentials", lambda: None)

    result = lifecycle_module.bootstrap_futures_if_enabled(path)

    assert result is None


def test_bootstrap_invokes_apply_futures_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(
        tmp_path,
        {"enabled": True, "symbols": {"BTCUSDT": {"leverage": 3}}},
    )
    monkeypatch.setattr(
        lifecycle_module, "_load_credentials", lambda: ("api-key", "api-secret")
    )

    captured: dict[str, Any] = {}

    def fake_apply(config: FuturesConfig, client) -> FuturesBootstrapReport:
        captured["config"] = config
        captured["client"] = client
        return FuturesBootstrapReport(skipped=False)

    monkeypatch.setattr(lifecycle_module, "apply_futures_settings", fake_apply)

    report = lifecycle_module.bootstrap_futures_if_enabled(path)

    assert report is not None
    assert report.skipped is False
    assert captured["config"].enabled is True
    assert captured["client"] is not None


def test_bootstrap_swallows_client_construction_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(tmp_path, {"enabled": True})
    monkeypatch.setattr(
        lifecycle_module, "_load_credentials", lambda: ("", "")
    )

    result = lifecycle_module.bootstrap_futures_if_enabled(path)

    # Empty credentials would raise inside FuturesHttpClient, but lifecycle
    # short-circuits before that because is_configured==False.
    assert result is None


def test_bootstrap_swallows_apply_exception(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_config(tmp_path, {"enabled": True})
    monkeypatch.setattr(
        lifecycle_module, "_load_credentials", lambda: ("api-key", "api-secret")
    )

    def raiser(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(lifecycle_module, "apply_futures_settings", raiser)

    result = lifecycle_module.bootstrap_futures_if_enabled(path)

    assert result is None
