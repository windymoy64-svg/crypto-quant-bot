from __future__ import annotations

from dataclasses import asdict, dataclass

from app.market.scanner import ScanItem


@dataclass(frozen=True)
class RankedSignal:
    rank: int
    symbol: str
    score: float
    confidence: float
    category: str
    action: str
    timeframe: str
    price: float
    data_source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class RankingEngine:
    def rank(self, scan_results: list[ScanItem]) -> list[RankedSignal]:
        sorted_results = sorted(scan_results, key=lambda item: item.score, reverse=True)
        return [
            RankedSignal(
                rank=rank,
                symbol=item.symbol,
                score=item.score,
                confidence=item.confidence,
                category=self.category_for_score(item.score),
                action=item.action,
                timeframe=item.timeframe,
                price=item.entry,
                data_source=item.data_source,
            )
            for rank, item in enumerate(sorted_results, start=1)
        ]

    def summarize(self, ranked_signals: list[RankedSignal]) -> dict[str, float | int]:
        total = len(ranked_signals)
        scores = [signal.score for signal in ranked_signals]
        confidences = [signal.confidence for signal in ranked_signals]
        counts = {category: 0 for category in ("BUY_NOW", "BUY", "WATCH", "IGNORE")}
        for signal in ranked_signals:
            counts[signal.category] += 1

        return {
            "total_symbols": total,
            "average_score": round(sum(scores) / total, 2) if total else 0.0,
            "highest_score": round(max(scores), 2) if scores else 0.0,
            "lowest_score": round(min(scores), 2) if scores else 0.0,
            "average_confidence": round(sum(confidences) / total, 2) if total else 0.0,
            "buy_now": counts["BUY_NOW"],
            "buy": counts["BUY"],
            "watch": counts["WATCH"],
            "ignore": counts["IGNORE"],
        }

    def category_for_score(self, score: float) -> str:
        if score >= 95:
            return "BUY_NOW"
        if score >= 90:
            return "BUY"
        if score >= 85:
            return "WATCH"
        return "IGNORE"