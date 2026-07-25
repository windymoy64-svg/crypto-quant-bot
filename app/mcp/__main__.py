"""Allow ``python -m app.mcp`` and ``python -m app.mcp.server``."""

from app.mcp.server import main

if __name__ == "__main__":
    main()
