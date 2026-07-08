from __future__ import annotations

from dataclasses import asdict, dataclass

from app.market.data_service import MarketDataService
from app.scoring.engine import ScoreEngine
from app.signals.builder import build_signal


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

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def scan_symbols(config: dict[str, object], rules_path: str = "configs/rules.json") -> list[ScanItem]:
    exchange = str(config.get("exchange", "binance"))
    timeframe = str(config.get("timeframe", "1m"))
    limit = int(config.get("limit", 100))
    symbols = [str(symbol) for symbol in config.get("symbols", [])]
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
            )
        )
    return sorted(results, key=lambda item: item.score, reverse=True)
