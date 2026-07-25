"""Safety guards for Ops MCP (read-only).

All tools must stay inside the project tree and only read allowlisted paths.
No order placement, credential mutation, or secret leakage.
"""

from __future__ import annotations

from pathlib import Path

# Project root = parents of app/mcp/guards.py → app/mcp → app → repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Relative path prefixes that tools may read.
ALLOWED_READ_PREFIXES: tuple[str, ...] = (
    "logs/",
    "data/",
    "configs/",
    "reports/",
)

# Path segments that must never be returned or opened via MCP.
SECRET_NAME_MARKERS: tuple[str, ...] = (
    ".env",
    "secret",
    "api_key",
    "apikey",
    "private_key",
    "credentials",
)


class McpGuardError(ValueError):
    """Raised when a path or action violates Ops MCP policy."""


def resolve_project_path(relative_path: str | Path) -> Path:
    """Resolve a relative path under PROJECT_ROOT with allowlist checks.

    Absolute paths outside the project, path traversal, and secret-looking
    filenames are rejected.
    """
    raw = str(relative_path).replace("\\", "/").lstrip("/")
    if not raw:
        raise McpGuardError("empty_path")

    lowered = raw.lower()
    for marker in SECRET_NAME_MARKERS:
        if marker in lowered:
            raise McpGuardError(f"secret_path_blocked:{raw}")

    allowed = any(
        raw == prefix.rstrip("/") or raw.startswith(prefix)
        for prefix in ALLOWED_READ_PREFIXES
    )
    if not allowed:
        raise McpGuardError(f"path_not_allowlisted:{raw}")

    candidate = (PROJECT_ROOT / raw).resolve()
    try:
        candidate.relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise McpGuardError(f"path_escapes_project:{raw}") from exc

    return candidate


def assert_read_only_mode() -> None:
    """Documented no-op guard: Ops MCP never enables write/execution tools."""
    return None


def ok_payload(data: dict | list | str | int | float | bool | None, **extra: object) -> dict:
    """Standard success envelope for tools."""
    payload: dict[str, object] = {"ok": True, "read_only": True}
    if isinstance(data, dict):
        payload.update(data)
    else:
        payload["data"] = data
    payload.update(extra)
    return payload


def err_payload(error: str | Exception, **extra: object) -> dict:
    """Standard error envelope — tools should not crash the MCP server."""
    payload: dict[str, object] = {
        "ok": False,
        "read_only": True,
        "error": str(error),
    }
    payload.update(extra)
    return payload


def scrub_secrets(obj: object) -> object:
    """Recursively drop keys that look like secrets from JSON-ish payloads."""
    if isinstance(obj, dict):
        cleaned: dict[str, object] = {}
        for key, value in obj.items():
            key_l = str(key).lower()
            if any(marker in key_l for marker in SECRET_NAME_MARKERS):
                cleaned[str(key)] = "[redacted]"
            else:
                cleaned[str(key)] = scrub_secrets(value)
        return cleaned
    if isinstance(obj, list):
        return [scrub_secrets(item) for item in obj]
    return obj
