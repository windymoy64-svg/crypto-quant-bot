from __future__ import annotations

import os

import uvicorn

from app.config.production import production_startup
from app.logger import setup_production_logging


def main() -> None:
    setup_production_logging()
    production_startup()
    host = os.getenv("BOT_API_HOST", "127.0.0.1")
    port = int(os.getenv("BOT_API_PORT", "8899"))
    uvicorn.run("app.dashboard.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
