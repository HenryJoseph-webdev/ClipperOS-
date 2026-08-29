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

import os

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
        _log_auth_diagnostics([])
        return []
    args = active.build_auth_args()
    _log_auth_diagnostics(args)
    return args


def _log_auth_diagnostics(args: list[str]) -> None:
    """Temporary safe diagnostics for the deployed cookie provisioning path."""
    from auth import prefs
    from auth.verify import validate_youtube_cookies_file

    cookies_path = prefs.cookies_path()
    cookies_exists = os.path.isfile(cookies_path)
    try:
        cookies_size = os.path.getsize(cookies_path) if cookies_exists else 0
    except OSError:
        cookies_size = 0

    prefs_exists = os.path.isfile(prefs.PREFS_PATH)
    selected_provider = prefs.get_selected_provider()
    safe_provider = selected_provider if selected_provider in {
        "none", "cookies_file", "browser_cookies"
    } else "unknown"

    cookies_valid = False
    if cookies_exists:
        cookies_valid, _ = validate_youtube_cookies_file(cookies_path)

    cookies_arg_constructed = any(
        args[index] == "--cookies" and index + 1 < len(args)
        for index in range(len(args))
    )
    print(
        "[auth][diag] "
        f"cookies_exists={cookies_exists} "
        f"cookies_size_bytes={cookies_size} "
        f"auth_prefs_exists={prefs_exists} "
        f"provider={safe_provider} "
        f"cookies_valid={cookies_valid} "
        f"cookies_arg_constructed={cookies_arg_constructed}"
    )


__all__ = [
    "get_active_provider",
    "get_status",
    "connect",
    "disconnect",
    "get_provider",
    "get_browsers",
    "build_auth_args",
]
