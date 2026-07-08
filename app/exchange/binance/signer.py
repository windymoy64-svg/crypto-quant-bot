from __future__ import annotations

import hashlib
import hmac
from urllib.parse import urlencode


class BinanceSigner:
    def __init__(self, api_secret: str) -> None:
        self.api_secret = api_secret

    def sign(self, params: dict[str, object]) -> str:
        query = urlencode(params)
        return hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    def signed_params(self, params: dict[str, object]) -> dict[str, object]:
        signed = dict(params)
        signed["signature"] = self.sign(signed)
        return signed