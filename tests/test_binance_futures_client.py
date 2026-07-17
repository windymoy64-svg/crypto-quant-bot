from __future__ import annotations

import hashlib
import hmac
import io
import json
import urllib.error
import urllib.parse
from typing import Any

import pytest

from app.exchange.binance_futures.client import (
    FuturesEndpoint,
    FuturesHttpClient,
    FuturesHttpError,
    _stringify,
)


class _FakeHTTPResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class _RecordingOpener:
    """Minimal opener stub capturing the outgoing request."""

    def __init__(self, response: _FakeHTTPResponse | Exception) -> None:
        self._response = response
        self.last_request: urllib.request.Request | None = None

    def open(self, request, timeout=None):  # noqa: ARG002 - matches OpenerDirector
        self.last_request = request
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _url_query(request) -> dict[str, str]:
    parsed = urllib.parse.urlparse(request.full_url)
    return dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))


def _decoded_body(request) -> dict[str, str]:
    raw = request.data.decode("utf-8") if request.data else ""
    return dict(urllib.parse.parse_qsl(raw, keep_blank_values=True))


def _make_client(response: Any) -> tuple[FuturesHttpClient, _RecordingOpener]:
    opener = _RecordingOpener(response)
    client = FuturesHttpClient(
        api_key="test-key",
        api_secret="test-secret",
        endpoint=FuturesEndpoint.TESTNET,
        opener=opener,
    )
    return client, opener


def test_stringify_normalizes_types() -> None:
    assert _stringify({"a": True, "b": 5, "c": "x", "d": None}) == {
        "a": "true",
        "b": "5",
        "c": "x",
    }


def test_get_signs_query_with_hmac_sha256() -> None:
    body = json.dumps({"ok": True}).encode("utf-8")
    client, opener = _make_client(_FakeHTTPResponse(200, body))

    response = client.get("/fapi/v3/balance")

    assert response.status_code == 200
    assert response.body == {"ok": True}
    assert opener.last_request is not None
    assert opener.last_request.get_method() == "GET"

    params = _url_query(opener.last_request)
    assert params["recvWindow"] == "5000"
    assert "timestamp" in params
    signature = params.pop("signature")
    reconstructed_query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    expected = hmac.new(
        b"test-secret", reconstructed_query.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    assert signature == expected
    assert opener.last_request.headers["X-mbx-apikey"] == "test-key"


def test_post_sends_form_body_and_content_type() -> None:
    body = json.dumps({"symbol": "BTCUSDT", "leverage": 5}).encode("utf-8")
    client, opener = _make_client(_FakeHTTPResponse(200, body))

    client.post("/fapi/v1/leverage", {"symbol": "btcusdt", "leverage": 5})

    request = opener.last_request
    assert request is not None
    assert request.get_method() == "POST"
    assert request.headers["Content-type"] == "application/x-www-form-urlencoded"
    payload = _decoded_body(request)
    assert payload["symbol"] == "btcusdt"
    assert payload["leverage"] == "5"
    assert "signature" in payload


def test_http_error_returns_structured_binance_message() -> None:
    error = urllib.error.HTTPError(
        url="https://testnet.binancefuture.com/fapi/v1/leverage",
        code=400,
        msg="Bad Request",
        hdrs=None,
        fp=io.BytesIO(json.dumps({"code": -4028, "msg": "Leverage not modified"}).encode()),
    )
    client, _ = _make_client(error)

    with pytest.raises(FuturesHttpError) as excinfo:
        client.post("/fapi/v1/leverage", {"symbol": "BTCUSDT", "leverage": 5})

    err = excinfo.value
    assert err.status_code == 400
    assert err.code == -4028
    assert err.message == "Leverage not modified"


def test_network_error_wrapped_as_futures_http_error() -> None:
    client, _ = _make_client(urllib.error.URLError("dns failure"))

    with pytest.raises(FuturesHttpError) as excinfo:
        client.get("/fapi/v3/balance")

    assert excinfo.value.status_code == 0
    assert "dns failure" in excinfo.value.message


def test_client_rejects_missing_credentials() -> None:
    with pytest.raises(ValueError):
        FuturesHttpClient(api_key="", api_secret="secret")
    with pytest.raises(ValueError):
        FuturesHttpClient(api_key="key", api_secret="")


def test_client_rejects_invalid_recv_window() -> None:
    with pytest.raises(ValueError):
        FuturesHttpClient(api_key="k", api_secret="s", recv_window=0)
    with pytest.raises(ValueError):
        FuturesHttpClient(api_key="k", api_secret="s", recv_window=120_000)
