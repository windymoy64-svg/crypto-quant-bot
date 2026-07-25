"""Ops MCP package — read-only operator tools for crypto-quant-bot.

This package exposes bot status, portfolio, signals, and agent artifacts to
MCP clients (Cline / Claude). It does **not** place orders or mutate live
trading state. See ``docs/MCP_MAP.md``.
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
