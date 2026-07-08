from __future__ import annotations

from dataclasses import asdict, dataclass

from app.portfolio.position import PortfolioPosition


@dataclass(frozen=True)
class SymbolExposure:
    symbol: str
    exposure: float
    exposure_percent: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PortfolioExposure:
    def by_symbol(
        self,
        positions: dict[str, PortfolioPosition],
        prices: dict[str, float],
        equity: float,
    ) -> dict[str, SymbolExposure]:
        result: dict[str, SymbolExposure] = {}
        for symbol, position in positions.items():
            exposure = position.market_value(prices.get(symbol))
            exposure_percent = (exposure / equity) * 100 if equity else 0.0
            result[symbol] = SymbolExposure(symbol, round(exposure, 8), round(exposure_percent, 4))
        return result

    def total(self, positions: dict[str, PortfolioPosition], prices: dict[str, float]) -> float:
        return round(sum(position.market_value(prices.get(symbol)) for symbol, position in positions.items()), 8)