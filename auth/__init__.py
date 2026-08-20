"""
auth/__init__.py

ClipperOS authentication package (V1).

Public API used by webapp.py and the download pipeline:
  - get_active_provider()  → AuthProvider | None
  - get_status()           → dict (UI-facing, never credentials)
  - connect(...)           → dict
  - disconnect()           → dict
  - get_browsers()         → list[str]
  - build_auth_args()      → list[str] (inject into yt-dlp commands)
"""

from __future__ import annotations

from auth.registry import (
    get_active_provider,
    get_status,
    connect,
    disconnect,
    get_provider,
)
from auth.browser_cookies import detect_browsers


def get_browsers() -> list[str]:
    """Return detected browsers for the Connect dropdown."""
    return detect_browsers()


def build_auth_args() -> list[str]:
    """
    Return yt-dlp auth args for the active provider, or [] if anonymous.

    Callers MUST redact these args before logging any command.
    """
    active = get_active_provider()
    if active is None:
        return []
    return active.build_auth_args()


__all__ = [
    "get_active_provider",
    "get_status",
    "connect",
    "disconnect",
    "get_provider",
    "get_browsers",
    "build_auth_args",
]
