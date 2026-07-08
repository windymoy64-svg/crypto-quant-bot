import os

import uvicorn

from app.dashboard.app import app
from app.logger import setup_production_logging


def main() -> None:
    setup_production_logging()

    host = os.getenv("BOT_API_HOST", "127.0.0.1")
    port = int(os.getenv("BOT_API_PORT", "8899"))

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,
    )


if __name__ == "__main__":
    main()