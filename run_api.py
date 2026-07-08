from __future__ import annotations

import os

import uvicorn

from app.config.production import load_dotenv_file
from app.logger import setup_production_logging


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set in .env or environment")
    return value.strip()


def main() -> None:
    """Launch the production dashboard.

    The FastAPI application lives in ``app.dashboard.app`` and owns its own
    lifespan handler that runs ``production_startup()`` exactly once during
    server startup. We therefore must not call ``production_startup()`` here
    or the startup routine would execute twice per boot.
    """

    load_dotenv_file()
    setup_production_logging()
    host = _required_env("BOT_API_HOST")
    port = int(_required_env("BOT_API_PORT"))
    uvicorn.run(
        "app.dashboard.app:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
