from __future__ import annotations


class BinanceConnectorError(RuntimeError):
    """Base error for Binance read-only connector failures."""


class BinanceNetworkTimeout(BinanceConnectorError):
    pass


class BinanceHTTPError(BinanceConnectorError):
    pass


class BinanceInvalidAPIKey(BinanceConnectorError):
    pass


class BinanceRateLimitError(BinanceConnectorError):
    pass


class BinanceInvalidSymbol(BinanceConnectorError):
    pass


class BinanceEmptyResponse(BinanceConnectorError):
    pass


class BinanceConfigurationError(BinanceConnectorError):
    pass