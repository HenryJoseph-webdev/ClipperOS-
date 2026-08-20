"""
auth/base.py

Defines the pluggable authentication interface for ClipperOS.

The AuthProvider abstract base class is the extension point that lets
ClipperOS support multiple authentication mechanisms (browser cookies
today, OAuth2 later) without changing the download pipeline.

Safety contract:
  - Providers must NEVER expose, log, or persist raw credentials/cookies.
  - to_dict() is the ONLY thing the UI/API ever sees.
  - build_auth_args() returns yt-dlp CLI args; callers must redact them
    before any logging.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Optional


# ─── Connection state ─────────────────────────────────────────────────────────

@dataclass
class ConnectionState:
    """
    Serializable status of an auth provider.

    Exposed to the UI via to_dict() — never contains credentials.
    """
    provider:  str = "none"
    connected: bool = False
    message:   str = ""
    detail:    str = ""                     # human-readable secondary text
    browser:   Optional[str] = None         # active browser (browser-cookie provider)
    profile:   Optional[str] = None         # active browser profile, if any
    available: bool = False                 # provider usable on this environment
    error:     Optional[str] = None

    def to_dict(self) -> dict:
        """UI-facing representation. Never includes credentials."""
        return {
            "provider":  self.provider,
            "connected": self.connected,
            "message":   self.message,
            "detail":    self.detail,
            "browser":   self.browser,
            "profile":   self.profile,
            "available": self.available,
            "error":     self.error,
        }


# ─── Provider interface ───────────────────────────────────────────────────────

class AuthProvider(abc.ABC):
    """
    Abstract authentication provider.

    Implementations handle one authentication mechanism. The download
    pipeline only ever asks a provider for its yt-dlp args; it never sees
    credentials directly.
    """

    # ── Identity ──────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def id(self) -> str:
        """Stable identifier, e.g. 'browser_cookies'."""

    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable label, e.g. 'Browser cookies'."""

    # ── Capability ────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def is_available(self) -> bool:
        """True if this provider can run in the current environment."""

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @abc.abstractmethod
    def connect(self, **prefs) -> ConnectionState:
        """Bind/select this provider's configuration and verify it."""

    @abc.abstractmethod
    def disconnect(self) -> ConnectionState:
        """Unbind this provider (stop using it)."""

    @abc.abstractmethod
    def verify(self) -> ConnectionState:
        """Lightweight check that auth still works. Makes a network call."""

    # ── Download pipeline ─────────────────────────────────────────────────────

    @abc.abstractmethod
    def build_auth_args(self) -> list[str]:
        """
        Return yt-dlp CLI args for this provider, or [] for anonymous.

        e.g. ['--cookies-from-browser', 'chrome']
        Callers MUST redact these before logging commands.
        """

    # ── Safe serialization ────────────────────────────────────────────────────

    @abc.abstractmethod
    def to_dict(self) -> dict:
        """UI-facing status. Never includes credentials."""
