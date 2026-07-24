from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.exchange.public_http_client import PublicHttpExchangeClient, TickerSnapshot
from app.market.data_service import MarketDataService
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_short_signal, build_signal


DEFAULT_EXCLUDED_BASE_ASSETS = {
    "BUSD", "DAI", "FDUSD", "PYUSD", "TUSD", "USDC", "USDP", "USD1",
}

DYNAMIC_PREFILTER_MODES = {
    "top_volume",
    "top_gainer",
    "top_loser",
    "momentum_liquid",
}


def _is_excluded_entry_symbol(symbol: str, config: dict[str, object]) -> bool:
    """Exclude cash-like pairs from ranking without dropping position tracking."""

    configured = config.get("excluded_base_assets", DEFAULT_EXCLUDED_BASE_ASSETS)
    assets = (
        {str(value).strip().upper() for value in configured}
        if isinstance(configured, (list, tuple, set))
        else DEFAULT_EXCLUDED_BASE_ASSETS
    )
    base = symbol.upper().replace("-", "/").split("/", 1)[0]
    return base in assets


def _excluded_base_set(config: dict[str, object]) -> set[str]:
    configured = config.get("excluded_base_assets", DEFAULT_EXCLUDED_BASE_ASSETS)
    if isinstance(configured, (list, tuple, set)):
        return {str(value).strip().upper() for value in configured if str(value).strip()}
    return set(DEFAULT_EXCLUDED_BASE_ASSETS)


def _liquidity_thresholds(config: dict[str, object]) -> tuple[float, float]:
    raw = config.get("liquidity_quality_thresholds", {})
    if not isinstance(raw, dict):
        raw = {}
    high = float(raw.get("high", 50_000_000.0) or 50_000_000.0)
    med = float(raw.get("med", 10_000_000.0) or 10_000_000.0)
    return high, med


def compute_market_breadth(
    snapshots: list[TickerSnapshot],
) -> dict[str, object]:
    """Aggregate 24h ticker snapshots into a market breadth snapshot."""

    if not snapshots:
        return {
            "tickers_count": 0,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
            "avg_change_24h": 0.0,
            "median_change_24h": 0.0,
            "top_gainer": None,
            "top_loser": None,
        }

    changes = [item.change_24h_pct for item in snapshots]
    up_count = sum(1 for value in changes if value > 0)
    down_count = sum(1 for value in changes if value < 0)
    flat_count = len(changes) - up_count - down_count
    top_gainer = max(snapshots, key=lambda item: item.change_24h_pct)
    top_loser = min(snapshots, key=lambda item: item.change_24h_pct)

    return {
        "tickers_count": len(snapshots),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
        "avg_change_24h": round(sum(changes) / len(changes), 4),
        "median_change_24h": round(float(statistics.median(changes)), 4),
        "top_gainer": {
            "symbol": top_gainer.symbol,
            "change_24h_pct": top_gainer.change_24h_pct,
            "last_price": top_gainer.last_price,
            "vol_usdt_24h": top_gainer.vol_usdt_24h,
        },
        "top_loser": {
            "symbol": top_loser.symbol,
            "change_24h_pct": top_loser.change_24h_pct,
            "last_price": top_loser.last_price,
            "vol_usdt_24h": top_loser.vol_usdt_24h,
        },
    }

def detect_move_alerts(
    snapshots: list[TickerSnapshot],
    config: dict[str, object],
    *,
    now: datetime | None = None,
) -> list[dict[str, object]]:
    """Emit threshold-crossed alerts with cooldown dedupe (watch only)."""

    if not bool(config.get("move_alert_enabled", False)):
        return []

    threshold = float(config.get("move_alert_threshold_pct", 5.0) or 5.0)
    cooldown_minutes = max(1, int(config.get("move_alert_cooldown_minutes", 30) or 30))
    min_vol = float(config.get("move_alert_min_quote_volume_usdt", 0.0) or 0.0)
    state_path = Path(
        str(config.get("move_alert_state_path", "logs/move_alert_state.json"))
    )

    now = now or datetime.now(tz=UTC)
    now_iso = now.isoformat()

    previous: dict[str, object] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                previous = loaded
        except (OSError, json.JSONDecodeError):
            previous = {}

    raw_symbols = previous.get("symbols", {})
    symbol_state: dict[str, object] = (
        dict(raw_symbols) if isinstance(raw_symbols, dict) else {}
    )

    alerts: list[dict[str, object]] = []
    for snap in snapshots:
        if min_vol > 0 and snap.vol_usdt_24h < min_vol:
            continue
        if abs(snap.change_24h_pct) < threshold:
            continue

        side = "up" if snap.change_24h_pct >= 0 else "down"
        prior = symbol_state.get(snap.symbol, {})
        if not isinstance(prior, dict):
            prior = {}

        last_alert_at = str(prior.get("last_alert_at") or "")
        last_side = str(prior.get("last_side") or "")
        skip = False
        if last_alert_at:
            try:
                last_dt = datetime.fromisoformat(last_alert_at)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=UTC)
                if now - last_dt < timedelta(minutes=cooldown_minutes):
                    if last_side == side:
                        skip = True
            except ValueError:
                pass
        if skip:
            continue

        alert = {
            "type": "move_threshold",
            "symbol": snap.symbol,
            "side": side,
            "change_24h_pct": snap.change_24h_pct,
            "last_price": snap.last_price,
            "vol_usdt_24h": snap.vol_usdt_24h,
            "vol_coin_24h": snap.vol_coin_24h,
            "threshold": threshold,
            "timestamp": now_iso,
        }
        alerts.append(alert)
        symbol_state[snap.symbol] = {
            "last_alert_at": now_iso,
            "last_side": side,
            "last_change_pct": snap.change_24h_pct,
        }

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"symbols": symbol_state, "updated_at": now_iso}, indent=2),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"move alert state write failed: {exc}", flush=True)

    return alerts



@dataclass(frozen=True)
class ScanItem:
    symbol: str
    exchange: str
    timeframe: str
    data_source: str
    action: str
    confidence: float
    score: float
    entry: float
    stop_loss: float
    take_profit: list[float]
    risk: str
    warning: str | None
    failed_gates: list[str]
    raw_confidence: float | None
    short_action: str
    short_confidence: float
    short_score: float
    short_failed_gates: list[str]
    short_entry: float
    short_stop_loss: float
    short_take_profit: list[float]
    short_risk_reward: float
    meta: dict[str, object] = field(default_factory=dict)
    short_meta: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScanRankings:
    long: list[ScanItem]
    short: list[ScanItem]
    # Simbol yang wajib dipantau (misalnya posisi terbuka) disimpan terpisah
    # agar ranking top N tetap benar-benar berisi kandidat terbaik.
    tracked: list[ScanItem] = field(default_factory=list)
    market_breadth: dict[str, object] = field(default_factory=dict)
    move_alerts: list[dict[str, object]] = field(default_factory=list)
    ticker_meta: dict[str, dict[str, object]] = field(default_factory=dict)

    def __iter__(self):
        # Kompatibilitas opsional jika ada kode yang ingin membongkar dua hasil.
        yield self.long
        yield self.short


def resolve_symbols(
    config: dict[str, object],
    exchange: str,
) -> tuple[list[str], list[TickerSnapshot], dict[str, TickerSnapshot]]:
    """Resolve scan universe.

    Returns (symbols, liquid_snapshots_for_breadth, selected_snapshot_map).
    liquid_snapshots may be empty for static/all modes without ticker fetch.
    """
    mode = str(config.get("symbol_mode", "static")).strip().lower()
    quote_asset = str(config.get("quote_asset", "USDT"))
    top_n = int(config.get("prefilter_top_n", 100))
    min_quote_volume = float(config.get("min_quote_volume_usdt", 0.0) or 0.0)
    min_move_pct = float(config.get("min_move_pct", 0.0) or 0.0)
    momentum_sort = str(config.get("momentum_sort", "quote_volume"))
    excluded = _excluded_base_set(config)

    if mode in DYNAMIC_PREFILTER_MODES:
        client = PublicHttpExchangeClient(exchange)
        try:
            symbols, snapshots, by_symbol = client.prefilter_symbols(
                quote_asset=quote_asset,
                top_n=top_n,
                min_quote_volume_usdt=min_quote_volume,
                min_move_pct=min_move_pct,
                mode=mode,
                momentum_sort=momentum_sort,
                excluded_base_assets=excluded,
            )
            if symbols:
                return symbols, snapshots, by_symbol
        except ValueError:
            pass
        configured = [str(symbol) for symbol in config.get("symbols", [])]
        if configured:
            return configured[:top_n], [], {}
        raise ValueError(f"prefilter mode {mode} failed and no static symbols configured")

    if mode == "all":
        client = PublicHttpExchangeClient(exchange)
        try:
            symbols = client.fetch_all_symbols(quote_asset=quote_asset)
        except ValueError:
            symbols = [str(symbol) for symbol in config.get("symbols", [])]
            if not symbols:
                raise
        max_symbols = int(config.get("max_symbols", 0))
        if max_symbols > 0:
            symbols = symbols[:max_symbols]
        return symbols, [], {}

    return [str(symbol) for symbol in config.get("symbols", [])], [], {}


def _failed_gates(buckets: object) -> list[str]:
    if not isinstance(buckets, dict):
        return []

    gates = buckets.get("_gates", {})
    if not isinstance(gates, dict):
        return []

    return [
        str(category)
        for category, info in gates.items()
        if isinstance(info, dict) and not info.get("passed")
    ]


def _ticker_meta_for_symbol(
    symbol: str,
    snapshot_map: dict[str, TickerSnapshot],
    breadth: dict[str, object],
    config: dict[str, object],
) -> dict[str, object]:
    snap = snapshot_map.get(symbol)
    if snap is None:
        return {}
    high, med = _liquidity_thresholds(config)
    median_change = float(breadth.get("median_change_24h") or 0.0)
    return {
        "change_24h_pct": snap.change_24h_pct,
        "last_price_24h": snap.last_price,
        "vol_coin_24h": snap.vol_coin_24h,
        "vol_usdt_24h": snap.vol_usdt_24h,
        "trade_count_24h": snap.trade_count_24h,
        "liquidity_quality": snap.liquidity_quality(high_usdt=high, med_usdt=med),
        "rs_vs_market": round(snap.change_24h_pct - median_change, 4),
        "market_median_change_24h": median_change,
    }

def scan_symbol_rankings(
    config: dict[str, object],
    rules_path: str = "configs/rules.json",
    market_data: MarketDataService | None = None,
) -> ScanRankings:
    exchange = str(config.get("exchange", "binance"))
    timeframe = str(config.get("timeframe", "1m"))
    limit = int(config.get("limit", 100))
    symbols, liquid_snapshots, snapshot_map = resolve_symbols(config, exchange)
    tracked_symbols = [
        str(symbol).strip().upper().replace("-", "/")
        for symbol in config.get("tracked_symbols", [])
        if str(symbol).strip()
    ]

    seen_symbols = set(symbols)
    for symbol in tracked_symbols:
        if symbol not in seen_symbols:
            symbols.append(symbol)
            seen_symbols.add(symbol)
    fallback = bool(config.get("fallback_to_sample_data", True))

    market_data = market_data or MarketDataService(
        exchange=exchange,
        fallback_to_sample_data=fallback,
    )

    breadth_source = liquid_snapshots
    if not breadth_source and snapshot_map:
        breadth_source = list(snapshot_map.values())
    market_breadth = compute_market_breadth(breadth_source)
    move_alerts = detect_move_alerts(breadth_source, config)

    long_engine = ScoreEngine.from_json(rules_path)
    short_shadow_enabled = bool(config.get("short_shadow_enabled", True))
    short_rules_path = str(config.get("short_rules_path", "configs/short_rules.json"))
    short_engine = (
        ScoreEngine.from_json(short_rules_path) if short_shadow_enabled else None
    )

    all_results: list[ScanItem] = []
    tracked_set = set(tracked_symbols)
    ticker_meta: dict[str, dict[str, object]] = {}



    for symbol in symbols:
        try:
            loaded = market_data.fetch_ohlcv(
                symbol=symbol,
                timeframe=timeframe,
                limit=limit,
                force_refresh=symbol in tracked_set,
            )
        except Exception as exc:
            print(f"scan symbol skipped {symbol}: {exc}", flush=True)
            continue

        long_score = long_engine.score(loaded.candles)
        long_signal = build_signal(
            symbol=symbol,
            candles=loaded.candles,
            score=long_score,
        )
        long_meta = dict(getattr(long_signal, "meta", {}) or {})
        ticker_fields = _ticker_meta_for_symbol(
            symbol, snapshot_map, market_breadth, config
        )
        if ticker_fields:
            long_meta.update(ticker_fields)
            ticker_meta[symbol] = ticker_fields

        short_score_result = (
            short_engine.score(loaded.candles) if short_engine is not None else None
        )
        short_signal = (
            build_short_signal(
                symbol=symbol,
                candles=loaded.candles,
                score=short_score_result,
            )
            if short_score_result is not None
            else None
        )
        short_meta = (
            dict(getattr(short_signal, "meta", {}) or {})
            if short_signal is not None
            else {}
        )
        if ticker_fields:
            short_meta.update(ticker_fields)

        if short_score_result is None:
            short_action = "DISABLED"
            short_confidence = 0.0
            short_score_value = 0.0
            short_failed_gates: list[str] = []
        else:
            short_action = (
                "SELL"
                if short_score_result.action == "BUY"
                else short_score_result.action
            )
            short_confidence = float(short_score_result.confidence)
            short_score_value = float(short_score_result.total_score)
            short_failed_gates = _failed_gates(short_score_result.buckets)

        all_results.append(
            ScanItem(
                symbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                data_source=loaded.source,
                action=long_signal.action,
                confidence=long_signal.confidence,
                score=long_signal.score,
                entry=long_signal.entry,
                stop_loss=long_signal.stop_loss,
                take_profit=long_signal.take_profit,
                risk=long_signal.risk,
                warning=loaded.warning,
                failed_gates=list(long_meta.get("failed_gates", []) or []),
                raw_confidence=long_meta.get("raw_confidence"),
                short_action=short_action,
                short_confidence=short_confidence,
                short_score=short_score_value,
                short_failed_gates=short_failed_gates,
                short_entry=(
                    float(short_signal.entry) if short_signal is not None else 0.0
                ),
                short_stop_loss=(
                    float(short_signal.stop_loss) if short_signal is not None else 0.0
                ),
                short_take_profit=(
                    list(short_signal.take_profit) if short_signal is not None else []
                ),
                short_risk_reward=(
                    float(short_signal.risk_reward) if short_signal is not None else 0.0
                ),
                meta=long_meta,
                short_meta=short_meta,
            )
        )


    long_top_n = int(config.get("top_n", 20))
    short_top_n = int(config.get("short_top_n", long_top_n))

    entry_results = [
        item
        for item in all_results
        if not _is_excluded_entry_symbol(item.symbol, config)
        or item.symbol in tracked_set
    ]
    # Existing excluded positions remain in ``tracked`` for exit management,
    # but must never re-enter either directional ranking.
    rankable_results = [
        item
        for item in entry_results
        if not _is_excluded_entry_symbol(item.symbol, config)
    ]

    long_ranked = sorted(
        rankable_results,
        key=lambda item: (item.score, item.confidence),
        reverse=True,
    )
    short_ranked = sorted(
        rankable_results,
        key=lambda item: (item.short_score, item.short_confidence),
        reverse=True,
    )

    if long_top_n > 0:
        long_ranked = long_ranked[:long_top_n]
    if short_top_n > 0:
        short_ranked = short_ranked[:short_top_n]

    tracked_results = [
        item for item in all_results if item.symbol in tracked_set
    ]

    return ScanRankings(
        long=long_ranked,
        short=short_ranked,
        tracked=tracked_results,
        market_breadth=market_breadth,
        move_alerts=move_alerts,
        ticker_meta=ticker_meta,
    )


def scan_symbols(
    config: dict[str, object],
    rules_path: str = "configs/rules.json",
) -> list[ScanItem]:
    """
    API lama dipertahankan.

    Pemanggil lama tetap hanya menerima ranking LONG, sehingga tidak ada
    perubahan perilaku pada paper trading maupun eksekusi live.
    """
    return scan_symbol_rankings(
        config=config,
        rules_path=rules_path,
    ).long
