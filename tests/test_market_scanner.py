from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.models import Candle
from app.exchange.public_http_client import PublicHttpExchangeClient, TickerSnapshot
from app.market.live_data import load_market_candles
from app.market.scanner import (
    _is_excluded_entry_symbol,
    compute_market_breadth,
    detect_move_alerts,
    scan_symbols,
)


class FakeExchangeClient:
    def fetch_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        return [
            Candle(symbol, "2026-07-06T00:00:00Z", 100, 101, 99, 100, 1000),
            Candle(symbol, "2026-07-06T00:01:00Z", 100, 102, 99, 101, 1100),
        ]

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        return {"symbol": symbol, "bid": 100.0, "ask": 101.0, "last": 100.5}


def _snap(
    symbol: str,
    change: float,
    vol_usdt: float,
    last: float = 1.0,
) -> TickerSnapshot:
    base = symbol.replace("/", "")
    return TickerSnapshot(
        symbol=symbol,
        market_symbol=base,
        last_price=last,
        change_24h_pct=change,
        vol_coin_24h=vol_usdt / max(last, 1e-9),
        vol_usdt_24h=vol_usdt,
        trade_count_24h=1000,
    )


def test_load_market_candles_uses_live_client() -> None:
    loaded = load_market_candles(
        symbol="BTC/USDT",
        exchange="binance",
        timeframe="1m",
        limit=2,
        client=FakeExchangeClient(),
    )

    assert loaded.source == "live"
    assert loaded.candles[-1].close == 101


def test_scan_symbols_returns_json_ready_items() -> None:
    config = {
        "exchange": "binance",
        "timeframe": "1m",
        "limit": 100,
        "symbols": ["BTC/USDT"],
        "fallback_to_sample_data": True,
    }

    results = scan_symbols(config)

    assert results
    assert results[0].to_dict()["symbol"] == "BTC/USDT"


def test_public_http_client_formats_symbols() -> None:
    client = PublicHttpExchangeClient("binance")

    assert client._binance_symbol("BTC/USDT") == "BTCUSDT"
    assert client._okx_symbol("BTC/USDT") == "BTC-USDT"


def test_stablecoin_base_assets_are_excluded_from_new_entries() -> None:
    config = {"excluded_base_assets": ["USDC", "FDUSD", "USD1"]}

    assert _is_excluded_entry_symbol("USDC/USDT", config) is True
    assert _is_excluded_entry_symbol("FDUSD-USDT", config) is True
    assert _is_excluded_entry_symbol("USD1/USDT", config) is True
    assert _is_excluded_entry_symbol("BTC/USDT", config) is False


def test_compute_market_breadth_counts_and_median() -> None:
    snapshots = [
        _snap("A/USDT", 10.0, 20_000_000),
        _snap("B/USDT", -2.0, 20_000_000),
        _snap("C/USDT", 0.0, 20_000_000),
        _snap("D/USDT", -4.0, 20_000_000),
    ]
    breadth = compute_market_breadth(snapshots)

    assert breadth["tickers_count"] == 4
    assert breadth["up_count"] == 1
    assert breadth["down_count"] == 2
    assert breadth["flat_count"] == 1
    assert breadth["median_change_24h"] == -1.0
    assert breadth["top_gainer"]["symbol"] == "A/USDT"
    assert breadth["top_loser"]["symbol"] == "D/USDT"


def test_prefilter_momentum_liquid_and_min_volume() -> None:
    client = PublicHttpExchangeClient("binance")
    snapshots = [
        _snap("THIN/USDT", 40.0, 100_000),  # illiquid pump
        _snap("MOVE/USDT", 12.0, 30_000_000),
        _snap("QUIET/USDT", 1.0, 80_000_000),
        _snap("DROP/USDT", -8.0, 25_000_000),
        _snap("MEGA/USDT", 6.0, 100_000_000),
    ]

    # Monkeypatch snapshot fetch to avoid network.
    client.fetch_24h_ticker_snapshots = (  # type: ignore[method-assign]
        lambda **kwargs: [
            s
            for s in snapshots
            if s.vol_usdt_24h >= float(kwargs.get("min_quote_volume_usdt") or 0)
        ]
    )

    symbols, all_snaps, by_symbol = client.prefilter_symbols(
        top_n=10,
        min_quote_volume_usdt=5_000_000,
        min_move_pct=5.0,
        mode="momentum_liquid",
        momentum_sort="quote_volume",
    )

    assert "THIN/USDT" not in symbols
    # Movers first (sorted by volume), then pad with liquid quiet coins.
    assert symbols[0] == "MEGA/USDT"
    assert symbols[:3] == ["MEGA/USDT", "MOVE/USDT", "DROP/USDT"]
    assert "QUIET/USDT" in symbols  # pads universe when movers < top_n
    assert set(symbols) == {"MEGA/USDT", "MOVE/USDT", "DROP/USDT", "QUIET/USDT"}
    assert len(all_snaps) == 4  # after min vol
    assert "MOVE/USDT" in by_symbol


def test_prefilter_momentum_liquid_fills_to_top_n() -> None:
    """When movers < top_n, pad with highest-volume liquid non-movers."""
    client = PublicHttpExchangeClient("binance")
    snapshots = [
        _snap(f"M{i}/USDT", 10.0, 50_000_000 - i * 1000) for i in range(3)
    ] + [
        _snap(f"Q{i}/USDT", 0.5, 40_000_000 - i * 1000) for i in range(5)
    ]

    client.fetch_24h_ticker_snapshots = (  # type: ignore[method-assign]
        lambda **kwargs: list(snapshots)
    )

    symbols, _, _ = client.prefilter_symbols(
        top_n=6,
        min_quote_volume_usdt=1_000_000,
        min_move_pct=5.0,
        mode="momentum_liquid",
        momentum_sort="quote_volume",
    )

    assert len(symbols) == 6
    # First 3 are movers
    assert symbols[:3] == ["M0/USDT", "M1/USDT", "M2/USDT"]
    # Next are quiet pads by volume
    assert symbols[3:] == ["Q0/USDT", "Q1/USDT", "Q2/USDT"]


def test_detect_move_alerts_respects_cooldown(tmp_path: Path) -> None:
    state_path = tmp_path / "alerts.json"
    config = {
        "move_alert_enabled": True,
        "move_alert_threshold_pct": 5.0,
        "move_alert_cooldown_minutes": 30,
        "move_alert_min_quote_volume_usdt": 1_000_000,
        "move_alert_state_path": str(state_path),
    }
    snaps = [
        _snap("KDA/USDT", 12.0, 50_000_000),
        _snap("THIN/USDT", 20.0, 100_000),  # below min vol
    ]
    now = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)

    first = detect_move_alerts(snaps, config, now=now)
    assert len(first) == 1
    assert first[0]["symbol"] == "KDA/USDT"
    assert first[0]["side"] == "up"

    second = detect_move_alerts(
        snaps, config, now=now + timedelta(minutes=10)
    )
    assert second == []

    third = detect_move_alerts(
        snaps, config, now=now + timedelta(minutes=31)
    )
    assert len(third) == 1
