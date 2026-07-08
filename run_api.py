from __future__ import annotations

import os

import uvicorn

from app.logger import setup_production_logging


def main() -> None:
    """Launch the production dashboard.

    The FastAPI application lives in ``app.dashboard.app`` and owns its own
    lifespan handler that runs ``production_startup()`` exactly once during
    server startup. We therefore must not call ``production_startup()`` here
    or the startup routine would execute twice per boot.
    """

    setup_production_logging()
    host = os.getenv("BOT_API_HOST", "127.0.0.1")
    port = int(os.getenv("BOT_API_PORT", "8899"))
    uvicorn.run(
        "app.dashboard.app:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
