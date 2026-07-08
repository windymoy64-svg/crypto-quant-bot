from __future__ import annotations

import os
import re
import shutil
import subprocess

import uvicorn

from app.config.production import load_dotenv_file
from app.logger import setup_production_logging


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} must be set in .env or environment")
    return value.strip()


def _command_output(command: list[str]) -> str:
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return "\n".join(part for part in (completed.stdout, completed.stderr) if part)


def _port_token_pattern(port: int) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9]):{port}(?![0-9])")


def _is_api_port_listening(port: int) -> bool:
    pattern = _port_token_pattern(port)

    if shutil.which("ss"):
        output = _command_output(["ss", "-ltnp"])
        if any("LISTEN" in line and pattern.search(line) for line in output.splitlines()):
            return True

    if shutil.which("lsof"):
        output = _command_output(["lsof", "-i", f":{port}"])
        if any(("LISTEN" in line or "TCP" in line) and pattern.search(line) for line in output.splitlines()):
            return True

    return False


def main() -> None:
    """Launch the production dashboard.

    The FastAPI application lives in ``app.dashboard.app`` and owns its own
    lifespan handler that runs ``production_startup()`` exactly once during
    server startup. We therefore must not call ``production_startup()`` here
    or the startup routine would execute twice per boot.
    """

    load_dotenv_file()
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
