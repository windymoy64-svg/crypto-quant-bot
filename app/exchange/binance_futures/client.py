"""Signed HTTP client for the Binance USDⓈ-M Futures REST API.

Design goals:
- No third-party HTTP dependency (uses ``urllib.request`` like the rest of
  the codebase) so the adapter stays lightweight.
- Deterministic signing: HMAC-SHA256 over the query string using the API
  secret, with ``timestamp``/``recvWindow`` injected for signed endpoints.
- Structured error surface via :class:`FuturesHttpError` carrying Binance's
  ``code``/``msg`` fields where available.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


logger = logging.getLogger(__name__)


class FuturesEndpoint(str, Enum):
    """Binance USDⓈ-M Futures REST hosts."""

    MAINNET = "https://fapi.binance.com"
    TESTNET = "https://testnet.binancefuture.com"


class FuturesHttpError(RuntimeError):
    """Raised when the futures REST API returns a non-2xx response."""

    def __init__(
        self,
        status_code: int,
        code: int | None,
        message: str,
        *,
        path: str,
    ) -> None:
        super().__init__(f"{path} -> HTTP {status_code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.path = path


@dataclass(frozen=True)
class FuturesHttpResponse:
    status_code: int
    body: Any



class FuturesHttpClient:
    """Minimal signed HTTP client for ``/fapi/*`` endpoints."""

    _SIGNED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE"})

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        endpoint: FuturesEndpoint = FuturesEndpoint.MAINNET,
        recv_window: int = 5000,
        timeout: float = 10.0,
        opener: urllib.request.OpenerDirector | None = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("api_key and api_secret must be non-empty")
        if recv_window <= 0 or recv_window > 60_000:
            raise ValueError("recv_window must be within (0, 60000]")
        self._api_key = api_key
        self._api_secret = api_secret.encode("utf-8")
        self._endpoint = endpoint
        self._recv_window = int(recv_window)
        self._timeout = float(timeout)
        self._opener = opener

    def get(
        self, path: str, params: Mapping[str, Any] | None = None, *, signed: bool = True
    ) -> FuturesHttpResponse:
        return self._request("GET", path, params, signed=signed)

    def post(
        self, path: str, params: Mapping[str, Any] | None = None, *, signed: bool = True
    ) -> FuturesHttpResponse:
        return self._request("POST", path, params, signed=signed)

    def delete(
        self, path: str, params: Mapping[str, Any] | None = None, *, signed: bool = True
    ) -> FuturesHttpResponse:
        return self._request("DELETE", path, params, signed=signed)


    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None,
        *,
        signed: bool,
    ) -> FuturesHttpResponse:
        method = method.upper()
        if method not in self._SIGNED_METHODS:
            raise ValueError(f"unsupported method: {method}")

        merged = dict(params or {})
        if signed:
            merged.setdefault("recvWindow", self._recv_window)
            merged["timestamp"] = int(time.time() * 1000)

        query = urllib.parse.urlencode(
            _stringify(merged), quote_via=urllib.parse.quote
        )
        if signed:
            signature = hmac.new(
                self._api_secret, query.encode("utf-8"), hashlib.sha256
            ).hexdigest()
            query = (
                f"{query}&signature={signature}" if query else f"signature={signature}"
            )

        url = f"{self._endpoint.value}{path}"
        headers = {"X-MBX-APIKEY": self._api_key}

        if method in {"GET", "DELETE"}:
            full_url = f"{url}?{query}" if query else url
            request = urllib.request.Request(full_url, headers=headers, method=method)
        else:
            request = urllib.request.Request(
                url,
                data=query.encode("utf-8"),
                headers={
                    **headers,
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method=method,
            )

        try:
            if self._opener is not None:
                response = self._opener.open(request, timeout=self._timeout)
            else:
                response = urllib.request.urlopen(request, timeout=self._timeout)
        except urllib.error.HTTPError as exc:
            raise self._translate_http_error(exc, path) from exc
        except urllib.error.URLError as exc:
            raise FuturesHttpError(
                status_code=0,
                code=None,
                message=f"network_error: {exc.reason}",
                path=path,
            ) from exc

        with response:
            raw = response.read().decode("utf-8")
            status_code = int(response.status)
        body = json.loads(raw) if raw else None
        return FuturesHttpResponse(status_code=status_code, body=body)

    @staticmethod
    def _translate_http_error(
        exc: urllib.error.HTTPError, path: str
    ) -> FuturesHttpError:
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        code: int | None = None
        message = raw or exc.reason or "http_error"
        if raw:
            try:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    code = payload.get("code")
                    message = str(payload.get("msg", raw))
            except json.JSONDecodeError:
                pass
        return FuturesHttpError(
            status_code=int(exc.code), code=code, message=message, path=path
        )


def _stringify(params: Mapping[str, Any]) -> dict[str, str]:
    """Coerce values so ``urlencode`` produces stable strings.

    Booleans are lower-cased to ``true``/``false`` (per Binance convention);
    numbers are cast via ``str``; ``None`` entries are dropped.
    """

    out: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out

