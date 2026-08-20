"""
auth/browser_cookies.py

BrowserCookieProvider — the V1 authentication method.

Instead of requiring users to manually export and repeatedly replace a
cookies.txt file, yt-dlp reads cookies directly from the user's browser
profile via its supported `--cookies-from-browser BROWSER[:PROFILE]`
mechanism.

Safety:
  - ClipperOS never reads, copies, stores, or logs raw cookies.
  - yt-dlp reads them from the browser profile at call time.
  - connect() runs a lightweight probe that does NOT download the video
    (--skip-download) and only confirms yt-dlp can authenticate.
  - The chosen browser/profile (not a secret) is stored in prefs.py.
"""

from __future__ import annotations

import os
from typing import Optional

from auth.base import AuthProvider, ConnectionState
from auth import prefs

# A short, public video used only to verify authentication. The probe runs
# with --skip-download so nothing is saved.
PROBE_URL = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"

# Browsers yt-dlp supports for --cookies-from-browser.
SUPPORTED_BROWSERS = [
    "chrome",
    "chromium",
    "edge",
    "firefox",
    "brave",
    "opera",
    "safari",
    "vivaldi",
]


def detect_browsers() -> list[str]:
    """
    Best-effort detection of browsers available on this machine.

    Returns a list of browser names ClipperOS can offer in the dropdown.
    This is a light heuristic (checks for well-known executables/config
    locations); it does not read any cookies.
    """
    import os
    import sys

    found: list[str] = []
    home = os.path.expanduser("~")

    # Paths where profiles typically live. Presence is a good hint.
    browser_dirs = {
        "chrome":   [os.path.join(home, "AppData", "Local", "Google", "Chrome"),
                     os.path.join(home, ".config", "google-chrome")],
        "chromium": [os.path.join(home, "AppData", "Local", "Chromium"),
                     os.path.join(home, ".config", "chromium")],
        "edge":     [os.path.join(home, "AppData", "Local", "Microsoft", "Edge"),
                     os.path.join(home, ".config", "microsoft-edge")],
        "firefox":  [os.path.join(home, "AppData", "Roaming", "Mozilla", "Firefox"),
                     os.path.join(home, ".mozilla", "firefox")],
        "brave":    [os.path.join(home, "AppData", "Local", "BraveSoftware", "Brave-Browser"),
                     os.path.join(home, ".config", "BraveSoftware", "Brave-Browser")],
        "opera":    [os.path.join(home, "AppData", "Roaming", "Opera Software", "Opera Stable"),
                     os.path.join(home, ".config", "opera")],
        "vivaldi":  [os.path.join(home, "AppData", "Local", "Vivaldi"),
                     os.path.join(home, ".config", "vivaldi")],
        "safari":   [os.path.join(home, "Library", "Safari")],
    }

    for browser in SUPPORTED_BROWSERS:
        for d in browser_dirs.get(browser, []):
            if os.path.isdir(d):
                found.append(browser)
                break

    return found


def _redact(value: str) -> str:
    """Mask a sensitive value for logging."""
    return "<redacted>" if value else ""


class BrowserCookieProvider(AuthProvider):
    """Authentication via yt-dlp's --cookies-from-browser."""

    def __init__(self) -> None:
        self._browser: Optional[str] = None
        self._profile: Optional[str] = None
        self._load_from_prefs()

    def _load_from_prefs(self) -> None:
        """Restore the saved browser/profile choice from prefs."""
        self._browser = prefs.get_browser_pref()
        self._profile = prefs.get_profile_pref()

    # ── Identity ──────────────────────────────────────────────────────────────

    def id(self) -> str:
        return "browser_cookies"

    def name(self) -> str:
        return "Browser cookies"

    # ── Capability ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        return len(detect_browsers()) > 0

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self, **kwargs) -> ConnectionState:
        browser = kwargs.get("browser", "").strip().lower()
        profile = (kwargs.get("profile") or "").strip() or None

        if not browser:
            return ConnectionState(
                provider="browser_cookies", available=True,
                message="No browser selected.",
                error="No browser selected.",
            )

        # Validate the browser is one we support & detect.
        if browser not in detect_browsers():
            return ConnectionState(
                provider="browser_cookies", available=True,
                browser=browser, profile=profile,
                message="Browser not detected on this machine.",
                error=f"Could not find a {browser} installation.",
            )

        # Save the preference FIRST so build_auth_args uses it.
        self._browser = browser
        self._profile = profile
        prefs.set_selected_provider(self.id())
        prefs.set_browser_pref(browser, profile)

        # Verify authentication actually works.
        state = self.verify()
        if state.connected:
            return state
        # If verification failed, don't leave a broken selection active.
        prefs.clear_prefs()
        self._browser = None
        self._profile = None
        return state

    def disconnect(self) -> ConnectionState:
        self._browser = None
        self._profile = None
        prefs.clear_prefs()
        return ConnectionState(
            provider="browser_cookies", available=True,
            connected=False, message="YouTube disconnected.",
        )

    def verify(self) -> ConnectionState:
        if not self._browser:
            return ConnectionState(
                provider="browser_cookies", available=True,
                connected=False, message="Not connected.",
            )

        try:
            from yt_dlp import YoutubeDL
            from yt_dlp.utils import DownloadError
        except ImportError:
            return ConnectionState(
                provider="browser_cookies", available=True,
                browser=self._browser, profile=self._profile,
                connected=False, message="yt-dlp not installed.",
                error="yt-dlp is not installed. Run: pip install yt-dlp",
            )

        target = self._browser
        if self._profile:
            target = f"{self._browser}:{self._profile}"

        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "cookiesfrombrowser": (target,),
        }

        try:
            with YoutubeDL(opts) as ydl:
                ydl.extract_info(PROBE_URL, download=False)
        except DownloadError as exc:
            from auth.verify import classify_ytdlp_auth_error
            is_auth, hint = classify_ytdlp_auth_error(str(exc))
            if not is_auth:
                return ConnectionState(
                    provider="browser_cookies", available=True,
                    browser=self._browser, profile=self._profile,
                    connected=True,
                    message="Connected to YouTube.",
                    detail=f"Using {self._browser} session.",
                )
            if not hint:
                hint = "yt-dlp could not authenticate with this browser session."
            return ConnectionState(
                provider="browser_cookies", available=True,
                browser=self._browser, profile=self._profile,
                connected=False, message="Connection failed.",
                detail=hint,
                error="YouTube session unavailable or expired.",
            )
        except Exception as exc:
            from auth.verify import classify_ytdlp_auth_error
            is_auth, hint = classify_ytdlp_auth_error(str(exc))
            detail = hint or str(exc)[:200]
            return ConnectionState(
                provider="browser_cookies", available=True,
                browser=self._browser, profile=self._profile,
                connected=False, message="Verification failed.",
                detail=detail,
                error=detail,
            )

        return ConnectionState(
            provider="browser_cookies", available=True,
            browser=self._browser, profile=self._profile,
            connected=True,
            message="Connected to YouTube.",
            detail=f"Using {self._browser} session.",
        )

    # ── Download pipeline ─────────────────────────────────────────────────────

    def build_auth_args(self) -> list[str]:
        if not self._browser:
            return []
        target = self._browser
        if self._profile:
            target = f"{self._browser}:{self._profile}"
        return ["--cookies-from-browser", target]

    # ── Safe serialization ────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        base = ConnectionState(
            provider="browser_cookies",
            available=self.is_available(),
            connected=bool(self._browser),
            browser=self._browser,
            profile=self._profile,
        )
        if self._browser:
            base.message = "Connected to YouTube."
            base.detail = f"Using {self._browser} session."
        else:
            base.connected = False
            base.message = "YouTube not connected."
        return base.to_dict()
