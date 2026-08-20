"""
auth/registry.py

A simple registry of auth providers. The active provider is resolved from
the stored preference. New providers (e.g. OAuth2) are added here later
without touching the download pipeline.
"""

from __future__ import annotations

from typing import Optional

from auth.base import AuthProvider, ConnectionState
from auth.browser_cookies import BrowserCookieProvider, detect_browsers
from auth.cookies_file import CookiesFileProvider, cookies_exists
from auth import prefs


def all_providers() -> list[AuthProvider]:
    """Return every registered provider instance."""
    return [
        CookiesFileProvider(),
        BrowserCookieProvider(),
    ]


def get_provider(provider_id: str) -> Optional[AuthProvider]:
    """Return a provider by id, or None."""
    for p in all_providers():
        if p.id() == provider_id:
            return p
    return None


def get_active_provider() -> Optional[AuthProvider]:
    """Return the provider selected in prefs, or None."""
    selected = prefs.get_selected_provider()
    if selected == "none":
        return None
    return get_provider(selected)


def _provider_manifest() -> list[dict]:
    return [
        {"id": p.id(), "name": p.name(), "available": p.is_available()}
        for p in all_providers()
    ]


def get_status() -> dict:
    """
    Aggregate status for the UI.

    Always returns a dict; never includes credentials.
    """
    providers = all_providers()
    browsers = detect_browsers()

    base = {
        "providers": _provider_manifest(),
        "browsers": browsers,
        "cookies_configured": cookies_exists(),
        "cookies_updated_at": prefs.get_cookies_updated_at(),
    }

    active = get_active_provider()
    if active is None:
        return {
            **base,
            "provider": "none",
            "connected": False,
            "message": "YouTube not connected.",
            "available": any(p.is_available() for p in providers),
            "browser": None,
            "profile": None,
            "error": None,
        }

    return {**base, **active.to_dict()}


def connect(provider_id: str, **kwargs) -> dict:
    """Connect via the given provider. Returns UI-facing status dict."""
    provider = get_provider(provider_id)
    if provider is None:
        return {
            "provider": provider_id,
            "connected": False,
            "message": "Unknown provider.",
            "error": f"No provider with id '{provider_id}'.",
            "available": False,
        }
    state: ConnectionState = provider.connect(**kwargs)
    return state.to_dict()


def disconnect() -> dict:
    """Disconnect the active provider. Returns UI-facing status dict."""
    active = get_active_provider()
    if active is not None:
        state: ConnectionState = active.disconnect()
        return state.to_dict()
    return {
        "provider": "none",
        "connected": False,
        "message": "YouTube not connected.",
        "available": False,
        "error": None,
    }
