"""
auth/prefs.py

Persists the user's authentication *preference* — which provider is
active, and which browser/profile to use for browser-cookie auth.

This file NEVER stores raw cookies or credentials. It only stores an
enum-like choice (browser name + profile identifier). The preference
file is written with 0600 permissions and is git-ignored (defense in
depth), even though it holds no secrets.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional

# Prefs live outside the repo so they're never committed.
# ~/.config/clipperos/auth_prefs.json  (Linux/macOS)
# %APPDATA%/clipperos/auth_prefs.json (Windows)
# Termux: ~/.config/clipperos/auth_prefs.json
def _prefs_path() -> str:
    config_home = os.environ.get(
        "XDG_CONFIG_HOME",
        os.path.join(os.path.expanduser("~"), ".config"),
    )
    return os.path.join(config_home, "clipperos", "auth_prefs.json")


PREFS_PATH = _prefs_path()


def cookies_path() -> str:
    """Stored cookies file — same config dir as prefs, never in the repo."""
    return os.path.join(os.path.dirname(PREFS_PATH), "cookies.txt")


def set_file_perms(path: str) -> None:
    """Best-effort 0600 on sensitive files (POSIX only)."""
    try:
        if sys.platform != "win32":
            os.chmod(path, 0o600)
    except OSError:
        pass


def _ensure_file_perms(path: str) -> None:
    set_file_perms(path)


def load_prefs() -> dict:
    """Load the stored preference dict. Returns {} on missing/corrupt file."""
    try:
        with open(PREFS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (OSError, ValueError):
        return {}


def save_prefs(prefs: dict) -> None:
    """Persist the preference dict with restrictive permissions."""
    os.makedirs(os.path.dirname(PREFS_PATH), exist_ok=True)
    with open(PREFS_PATH, "w", encoding="utf-8") as f:
        json.dump(prefs, f, indent=2)
    _ensure_file_perms(PREFS_PATH)


def clear_prefs() -> None:
    """Remove the prefs file entirely (used on Disconnect)."""
    try:
        if os.path.exists(PREFS_PATH):
            os.remove(PREFS_PATH)
    except OSError:
        pass


# ── Typed helpers ─────────────────────────────────────────────────────────────

def get_selected_provider() -> str:
    """Return the active provider id, or 'none'."""
    return load_prefs().get("provider", "none")


def set_selected_provider(provider: str) -> None:
    prefs = load_prefs()
    prefs["provider"] = provider
    save_prefs(prefs)


def get_browser_pref() -> Optional[str]:
    """Return the saved browser name (e.g. 'chrome'), or None."""
    return load_prefs().get("browser")


def get_profile_pref() -> Optional[str]:
    """Return the saved browser profile, or None."""
    return load_prefs().get("profile")


def set_browser_pref(browser: str, profile: Optional[str] = None) -> None:
    prefs = load_prefs()
    prefs["browser"] = browser
    if profile:
        prefs["profile"] = profile
    else:
        prefs.pop("profile", None)
    save_prefs(prefs)


def get_cookies_updated_at() -> Optional[str]:
    """ISO timestamp of the last cookies.txt upload, or None."""
    return load_prefs().get("cookies_updated_at")


def set_cookies_updated_at(iso_timestamp: str) -> None:
    prefs = load_prefs()
    prefs["cookies_updated_at"] = iso_timestamp
    save_prefs(prefs)
