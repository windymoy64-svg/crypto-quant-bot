from __future__ import annotations

from typing import Any

import pytest

from app.exchange.binance_futures.brackets import (
    FuturesLeverageBracketReader,
    LeverageBracket,
    SymbolBrackets,
)
from app.exchange.binance_futures.client import FuturesHttpResponse


class _StubClient:
    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def get(self, path, params=None, *, signed=True):  # noqa: ARG002
        self.calls.append((path, dict(params or {}) if params else None))
        return FuturesHttpResponse(status_code=200, body=self._responses[path])


_BTC_BRACKETS = [
    {
        "symbol": "BTCUSDT",
        "brackets": [
            {
                "bracket": 1,
                "initialLeverage": 125,
                "notionalCap": 50000,
                "notionalFloor": 0,
                "maintMarginRatio": 0.004,
                "cum": 0,
            },
            {
                "bracket": 2,
                "initialLeverage": 100,
                "notionalCap": 250000,
                "notionalFloor": 50000,
                "maintMarginRatio": 0.005,
                "cum": 50,
            },
            {
                "bracket": 3,
                "initialLeverage": 50,
                "notionalCap": 1000000,
                "notionalFloor": 250000,
                "maintMarginRatio": 0.01,
                "cum": 1300,
            },
        ],
    }
]


def test_bracket_reader_fetches_symbol() -> None:
    stub = _StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS})
    reader = FuturesLeverageBracketReader(stub)

    result = reader.get("btcusdt")

    assert stub.calls[0] == ("/fapi/v1/leverageBracket", {"symbol": "BTCUSDT"})
    assert result.symbol == "BTCUSDT"
    assert len(result.brackets) == 3
    assert result.brackets[0].initial_leverage == 125


def test_bracket_reader_caches_by_symbol() -> None:
    stub = _StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS})
    reader = FuturesLeverageBracketReader(stub)

    reader.get("BTCUSDT")
    reader.get("BTCUSDT")

    assert len(stub.calls) == 1


def test_bracket_reader_refresh_bypasses_cache() -> None:
    stub = _StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS})
    reader = FuturesLeverageBracketReader(stub)

    reader.get("BTCUSDT")
    reader.get("BTCUSDT", refresh=True)

    assert len(stub.calls) == 2


def test_bracket_for_selects_correct_tier() -> None:
    reader = FuturesLeverageBracketReader(_StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS}))
    brackets = reader.get("BTCUSDT")

    tier_low = brackets.bracket_for(1000)
    tier_mid = brackets.bracket_for(60000)
    tier_high = brackets.bracket_for(500000)

    assert tier_low.bracket == 1
    assert tier_mid.bracket == 2
    assert tier_high.bracket == 3


def test_bracket_for_returns_top_tier_when_over_cap() -> None:
    reader = FuturesLeverageBracketReader(_StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS}))
    brackets = reader.get("BTCUSDT")

    assert brackets.bracket_for(10_000_000).bracket == 3


def test_bracket_for_rejects_negative_notional() -> None:
    reader = FuturesLeverageBracketReader(_StubClient({"/fapi/v1/leverageBracket": _BTC_BRACKETS}))
    brackets = reader.get("BTCUSDT")

    with pytest.raises(ValueError):
        brackets.bracket_for(-1)


def test_bracket_reader_all_returns_every_symbol() -> None:
    payload = _BTC_BRACKETS + [
        {
            "symbol": "ETHUSDT",
            "brackets": [
                {
                    "bracket": 1,
                    "initialLeverage": 100,
                    "notionalCap": 10000,
                    "notionalFloor": 0,
                    "maintMarginRatio": 0.005,
                    "cum": 0,
                }
            ],
        }
    ]
    stub = _StubClient({"/fapi/v1/leverageBracket": payload})
    reader = FuturesLeverageBracketReader(stub)

    result = reader.all()

    assert set(result.keys()) == {"BTCUSDT", "ETHUSDT"}


def test_bracket_reader_rejects_empty_response() -> None:
    stub = _StubClient({"/fapi/v1/leverageBracket": []})
    reader = FuturesLeverageBracketReader(stub)

    with pytest.raises(ValueError):
        reader.get("BTCUSDT")
