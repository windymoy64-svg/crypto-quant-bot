from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.models import Candle
from app.exchange.base import ExchangeClient
from app.exchange.binance.account import BinanceAccountAPI
from app.exchange.binance.auth import BinanceAuth
from app.exchange.binance.exceptions import (
    BinanceConfigurationError,
    BinanceEmptyResponse,
    BinanceHTTPError,
    BinanceInvalidAPIKey,
    BinanceInvalidSymbol,
    BinanceNetworkTimeout,
    BinanceRateLimitError,
)
from app.exchange.binance.market import BinanceMarketAPI
from app.exchange.binance.models import BinanceConfig
from app.exchange.binance.signer import BinanceSigner
from app.exchange.binance.websocket import BinanceWebSocket


class BinanceConnector(ExchangeClient):
    live_base_url = "https://api.binance.com"
    testnet_base_url = "https://testnet.binance.vision"

    def __init__(
        self,
        config_path: str | Path = "configs/exchange.json",
        env_path: str | Path = ".env",
        config: BinanceConfig | None = None,
    ) -> None:
        self.config = config or self._load_config(config_path)
        if self.config.exchange.lower() != "binance":
            raise BinanceConfigurationError(f"Unsupported exchange for BinanceConnector: {self.config.exchange}")
        self.base_url = self.testnet_base_url if self.config.testnet else self.live_base_url
        self.auth = BinanceAuth(env_path)
        self.market = BinanceMarketAPI(self)
        self.account = BinanceAccountAPI(self)
        self.websocket = BinanceWebSocket(testnet=self.config.testnet)

    def fetch_candles(self, symbol: str, timeframe: str = "1h", limit: int = 100) -> list[Candle]:
        return self.market.klines(symbol, interval=timeframe, limit=limit)

    def fetch_ticker(self, symbol: str) -> dict[str, float | str]:
        ticker = self.market.ticker_24h(symbol)
        return {
            "symbol": symbol,
            "bid": float(ticker.get("bidPrice") or 0.0),
            "ask": float(ticker.get("askPrice") or 0.0),
            "last": float(ticker.get("lastPrice") or 0.0),
            "volume": float(ticker.get("volume") or 0.0),
        }

    def public_get(self, path: str, params: dict[str, object] | None = None) -> object:
        return self._request("GET", path, params or {}, signed=False)

    def private_get(self, path: str, params: dict[str, object] | None = None) -> object:
        credentials = self.auth.credentials(required=True)
        request_params = dict(params or {})
        request_params["timestamp"] = int(time.time() * 1000)
        request_params["recvWindow"] = self.config.recv_window
        request_params["signature"] = BinanceSigner(credentials.api_secret).sign(request_params)
        return self._request("GET", path, request_params, signed=True, api_key=credentials.api_key)

    def private_post(self, path: str, params: dict[str, object] | None = None) -> object:
        if path != "/api/v3/order":
            raise BinanceConfigurationError("BinanceConnector only supports gated Spot order submission")
        credentials = self.auth.credentials(required=True)
        request_params = dict(params or {})
        request_params["timestamp"] = int(time.time() * 1000)
        request_params["recvWindow"] = self.config.recv_window
        request_params["signature"] = BinanceSigner(credentials.api_secret).sign(request_params)
        return self._request("POST", path, request_params, signed=True, api_key=credentials.api_key)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, object],
        *,
        signed: bool,
        api_key: str | None = None,
    ) -> object:
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise BinanceConfigurationError("BinanceConnector only supports GET and gated POST requests")
        query = urlencode(params)
        url = f"{self.base_url}{path}"
        data = None
        if method == "GET" and query:
            url = f"{url}?{query}"
        if method == "POST":
            data = query.encode("utf-8")
        headers = {"User-Agent": "crypto-quant-bot-binance-readonly/1.0"}
        if signed:
            headers["X-MBX-APIKEY"] = api_key or ""
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            self._raise_http_error(exc)
        except (TimeoutError, socket.timeout) as exc:
            raise BinanceNetworkTimeout(f"Binance request timed out: {path}") from exc
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, socket.timeout):
                raise BinanceNetworkTimeout(f"Binance request timed out: {path}") from exc
            raise BinanceHTTPError(f"Binance network error for {path}: {reason}") from exc
        if not raw:
            raise BinanceEmptyResponse(f"Binance returned an empty response for {path}")
        data = json.loads(raw)
        self._validate_response(path, data, allow_empty=path in {"/api/v3/openOrders", "/api/v3/allOrders", "/api/v3/myTrades"})
        return data

    def _raise_http_error(self, exc: HTTPError) -> None:
        raw = exc.read().decode("utf-8") if exc.fp else ""
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {}
        code = int(payload.get("code") or exc.code)
        message = str(payload.get("msg") or exc.reason)
        self._raise_mapped_error(code, exc.code, message, exc)

    def _validate_response(self, path: str, data: object, *, allow_empty: bool = False) -> None:
        if (data == [] or data == {} or data is None) and not allow_empty:
            raise BinanceEmptyResponse(f"Binance returned no data for {path}")
        if isinstance(data, dict) and "code" in data and "msg" in data:
            self._raise_mapped_error(int(data.get("code") or 0), 400, str(data.get("msg") or "Binance error"), None)

    def _raise_mapped_error(self, code: int, status: int, message: str, original: Exception | None) -> None:
        full_message = f"Binance error {code} HTTP {status}: {message}"
        if status in {418, 429} or code in {-1003, -1015}:
            raise BinanceRateLimitError(full_message) from original
        if code in {-2014, -2015} or "api-key" in message.lower() or "signature" in message.lower():
            raise BinanceInvalidAPIKey(full_message) from original
        if code == -1121 or "invalid symbol" in message.lower():
            raise BinanceInvalidSymbol(full_message) from original
        raise BinanceHTTPError(full_message) from original

    def _load_config(self, config_path: str | Path) -> BinanceConfig:
        path = Path(config_path)
        if not path.exists():
            return BinanceConfig()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise BinanceConfigurationError("configs/exchange.json must contain a JSON object")
        return BinanceConfig.from_dict(data)