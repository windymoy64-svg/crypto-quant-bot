from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.exchange.public_http_client import PublicHttpExchangeClient
from app.market.data_service import MarketDataService
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_short_signal, build_signal


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

    def __iter__(self):
        # Kompatibilitas opsional jika ada kode yang ingin membongkar dua hasil.
        yield self.long
        yield self.short


def resolve_symbols(config: dict[str, object], exchange: str) -> list[str]:
    mode = str(config.get("symbol_mode", "static"))

    if mode == "top_volume":
        client = PublicHttpExchangeClient(exchange)
        top_n = int(config.get("prefilter_top_n", 100))
        return client.fetch_top_symbols_by_volume(
            quote_asset=str(config.get("quote_asset", "USDT")),
            top_n=top_n,
        )

    if mode == "all":
        client = PublicHttpExchangeClient(exchange)
        symbols = client.fetch_all_symbols(
            quote_asset=str(config.get("quote_asset", "USDT")),
        )
        max_symbols = int(config.get("max_symbols", 0))
        if max_symbols > 0:
            symbols = symbols[:max_symbols]
        return symbols

    return [str(symbol) for symbol in config.get("symbols", [])]


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


def scan_symbol_rankings(
    config: dict[str, object],
    rules_path: str = "configs/rules.json",
) -> ScanRankings:
    exchange = str(config.get("exchange", "binance"))
    timeframe = str(config.get("timeframe", "1m"))
    limit = int(config.get("limit", 100))
    symbols = resolve_symbols(config, exchange)
    tracked_symbols = [
        str(symbol).strip().upper().replace("-", "/")
        for symbol in config.get("tracked_symbols", [])
        if str(symbol).strip()
    ]

    # Posisi yang sudah entry tidak boleh kehilangan pembaruan harga hanya
    # karena simbolnya keluar dari prefilter volume atau ranking top N.
    seen_symbols = set(symbols)
    for symbol in tracked_symbols:
        if symbol not in seen_symbols:
            symbols.append(symbol)
            seen_symbols.add(symbol)
    fallback = bool(config.get("fallback_to_sample_data", True))

    market_data = MarketDataService(
        exchange=exchange,
        fallback_to_sample_data=fallback,
    )

    # Engine LONG lama tetap menggunakan rules.json.
    long_engine = ScoreEngine.from_json(rules_path)

    # Engine SHORT terpisah dan masih shadow mode.
    short_shadow_enabled = bool(
        config.get("short_shadow_enabled", True)
    )
    short_rules_path = str(
        config.get("short_rules_path", "configs/short_rules.json")
    )
    short_engine = (
        ScoreEngine.from_json(short_rules_path)
        if short_shadow_enabled
        else None
    )

    all_results: list[ScanItem] = []

    tracked_set = set(tracked_symbols)

    for symbol in symbols:
        # Simbol posisi terbuka wajib harga realtime: lewati cache agar
        # perubahan harga benar-benar terpantau tiap siklus scan.
        loaded = market_data.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
            force_refresh=symbol in tracked_set,
        )

        # LONG: jalur lama.

        long_score = long_engine.score(loaded.candles)
        long_signal = build_signal(
            symbol=symbol,
            candles=loaded.candles,
            score=long_score,
        )
        long_meta = getattr(long_signal, "meta", {}) or {}

        # SHORT: hanya scoring shadow, belum membuat TradingSignal SELL.
        short_score_result = (
            short_engine.score(loaded.candles)
            if short_engine is not None
            else None
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
            getattr(short_signal, "meta", {}) or {}
            if short_signal is not None
            else {}
        )

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
            short_failed_gates = _failed_gates(
                short_score_result.buckets
            )

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
                failed_gates=list(
                    long_meta.get("failed_gates", []) or []
                ),
                raw_confidence=long_meta.get("raw_confidence"),
                short_action=short_action,
                short_confidence=short_confidence,
                short_score=short_score_value,
                short_failed_gates=short_failed_gates,
                short_entry=(
                    float(short_signal.entry)
                    if short_signal is not None
                    else 0.0
                ),
                short_stop_loss=(
                    float(short_signal.stop_loss)
                    if short_signal is not None
                    else 0.0
                ),
                short_take_profit=(
                    list(short_signal.take_profit)
                    if short_signal is not None
                    else []
                ),
                short_risk_reward=(
                    float(short_signal.risk_reward)
                    if short_signal is not None
                    else 0.0
                ),
                meta=long_meta,
                short_meta=short_meta,
            )
        )

    long_top_n = int(config.get("top_n", 20))
    short_top_n = int(
        config.get("short_top_n", long_top_n)
    )

    long_ranked = sorted(
        all_results,
        key=lambda item: (
            item.score,
            item.confidence,
        ),
        reverse=True,
    )

    short_ranked = sorted(
        all_results,
        key=lambda item: (
            item.short_score,
            item.short_confidence,
        ),
        reverse=True,
    )

    if long_top_n > 0:
        long_ranked = long_ranked[:long_top_n]

    if short_top_n > 0:
        short_ranked = short_ranked[:short_top_n]

    tracked_results = [
        item
        for item in all_results
        if item.symbol in tracked_set
    ]


    return ScanRankings(
        long=long_ranked,
        short=short_ranked,
        tracked=tracked_results,
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