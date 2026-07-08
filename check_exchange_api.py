from __future__ import annotations

import json

from app.config.env import get_exchange_credentials
from app.exchange.ccxt_client import CcxtExchangeClient


def main() -> None:
    credentials = get_exchange_credentials()
    if not credentials.configured:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "EXCHANGE_API_KEY and EXCHANGE_SECRET are not configured",
                },
                indent=2,
            )
        )
        return

    client = CcxtExchangeClient(
        credentials.exchange_id,
        api_key=credentials.api_key,
        secret=credentials.secret,
        password=credentials.password,
    )
    balance = client.fetch_balance()
    print(
        json.dumps(
            {
                "ok": True,
                "exchange": credentials.exchange_id,
                "currencies": sorted(balance.get("total", {}).keys())[:20],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
