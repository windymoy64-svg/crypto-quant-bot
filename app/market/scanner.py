from __future__ import annotations

from dataclasses import asdict, dataclass

from app.market.data_service import MarketDataService
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal
from app.exchange.public_http_client import PublicHttpExchangeClient


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

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

def scan_symbols(config: dict[str, object], rules_path: str = "configs/rules.json") -> list[ScanItem]:
    exchange = str(config.get("exchange", "binance"))
    timeframe = str(config.get("timeframe", "1m"))
    limit = int(config.get("limit", 100))
    symbols = resolve_symbols(config, exchange)          # <— berubah di sini
    fallback = bool(config.get("fallback_to_sample_data", True))
    market_data = MarketDataService(exchange=exchange, fallback_to_sample_data=fallback)
    score_engine = ScoreEngine.from_json(rules_path)

    results: list[ScanItem] = []
    for symbol in symbols:
        loaded = market_data.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit,
        )
        score = score_engine.score(loaded.candles)
        signal = build_signal(symbol=symbol, candles=loaded.candles, score=score)
        signal_meta = getattr(signal, "meta", {}) or {}
        results.append(
            ScanItem(
                symbol=symbol,
                exchange=exchange,
                timeframe=timeframe,
                data_source=loaded.source,
                action=signal.action,
                confidence=signal.confidence,
                score=signal.score,
                entry=signal.entry,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk=signal.risk,
                warning=loaded.warning,
                failed_gates=list(signal_meta.get("failed_gates", []) or []),
                raw_confidence=signal_meta.get("raw_confidence"),
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    top_n = int(config.get("top_n", 0))
    if top_n > 0:
        results = results[:top_n]
    return results
