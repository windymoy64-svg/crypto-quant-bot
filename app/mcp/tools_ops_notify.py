"""Monitoring + ops notification tools (MCP-4).

Read-only against trading execution. Telegram delivery defaults to dry-run
(outbox only) unless ``live=True`` and env credentials exist.
"""

from __future__ import annotations

import os
import time
from typing import Any

from app.mcp.guards import err_payload, ok_payload, scrub_secrets
from app.mcp.io_utils import artifact_exists, now_iso
from app.mcp.paths import (
    DEFAULT_ANALYTICS_PATH,
    DEFAULT_OBSERVATIONS_PATH,
    DEFAULT_PAPER_STATE_PATH,
    DEFAULT_PIPELINE_PATH,
    DEFAULT_SIGNALS_PATH,
    DEFAULT_TRADE_JOURNAL_PATH,
)

MAX_NOTIFY_CHARS = 3500
# Simple process-local rate limit for live sends.
_LAST_LIVE_SEND_AT: float = 0.0
_MIN_LIVE_SEND_INTERVAL_SEC = 5.0


def get_system_health() -> dict[str, Any]:
    """System health snapshot from SystemHealthMonitor + artifact flags."""
    try:
        from app.monitoring import system_health_monitor

        snap = system_health_monitor.snapshot()
        cleaned = scrub_secrets(snap) if isinstance(snap, dict) else {"raw": snap}
        if not isinstance(cleaned, dict):
            cleaned = {"raw": cleaned}

        artifacts = {
            "latest_signals": artifact_exists(DEFAULT_SIGNALS_PATH),
            "paper_state": artifact_exists(DEFAULT_PAPER_STATE_PATH),
            "agent_pipeline": artifact_exists(DEFAULT_PIPELINE_PATH),
            "analytics_report": artifact_exists(DEFAULT_ANALYTICS_PATH),
            "trade_journal": artifact_exists(DEFAULT_TRADE_JOURNAL_PATH),
            "chart_observations": artifact_exists(DEFAULT_OBSERVATIONS_PATH),
            "backtests_dir": artifact_exists("logs/backtests"),
        }
        return ok_payload(
            {
                "available": True,
                "timestamp": now_iso(),
                "system": cleaned,
                "artifacts": artifacts,
                "telegram_env_configured": bool(
                    os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="get_system_health")


def send_ops_notification(
    message: str,
    *,
    live: bool = False,
    prefix: str = "[ops-mcp]",
) -> dict[str, Any]:
    """Send an ops notification via TelegramNotifier.

    Defaults to dry-run (``live=False``): message is recorded in notifier outbox
    only. Live delivery requires ``live=True`` **and** TELEGRAM_BOT_TOKEN +
    TELEGRAM_CHAT_ID. Never used for trading orders.
    """
    global _LAST_LIVE_SEND_AT
    try:
        text = str(message or "").strip()
        if not text:
            raise ValueError("message_required")
        if len(text) > MAX_NOTIFY_CHARS:
            text = text[: MAX_NOTIFY_CHARS - 20] + "\n…[truncated]"

        full = f"{prefix} {text}".strip() if prefix else text
        want_live = bool(live)

        # Hard block live if env not configured.
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        env_ok = bool(token and chat_id)
        if want_live and not env_ok:
            return ok_payload(
                {
                    "sent": False,
                    "live": False,
                    "reason": "telegram_env_not_configured",
                    "message_preview": full[:200],
                }
            )

        if want_live:
            now = time.time()
            elapsed = now - _LAST_LIVE_SEND_AT
            if elapsed < _MIN_LIVE_SEND_INTERVAL_SEC:
                return ok_payload(
                    {
                        "sent": False,
                        "live": False,
                        "reason": "rate_limited",
                        "retry_after_seconds": round(
                            _MIN_LIVE_SEND_INTERVAL_SEC - elapsed, 2
                        ),
                        "message_preview": full[:200],
                    }
                )

        from app.telegram.notifier import TelegramNotifier

        notifier = TelegramNotifier(enabled=True, live=want_live and env_ok)
        notifier.send(full)
        if want_live and env_ok:
            _LAST_LIVE_SEND_AT = time.time()

        return ok_payload(
            {
                "sent": True,
                "live": bool(want_live and env_ok),
                "outbox_count": len(notifier.outbox),
                "message_preview": full[:200],
                "message_length": len(full),
                "note": (
                    "delivered_or_attempted"
                    if want_live and env_ok
                    else "dry_run_outbox_only"
                ),
            }
        )
    except Exception as exc:  # noqa: BLE001
        return err_payload(exc, tool="send_ops_notification")
