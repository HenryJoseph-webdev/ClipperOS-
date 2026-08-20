"""
auth/cookies_file.py

CookiesFileProvider — export cookies once from a browser extension,
ClipperOS reads the file until it expires. Avoids Windows DPAPI entirely.

The cookies file lives at ~/.config/clipperos/cookies.txt (outside the repo).
ClipperOS never logs or exposes cookie values.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from auth.base import AuthProvider, ConnectionState
from auth import prefs
from auth.verify import validate_youtube_cookies_file

PROBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
MAX_COOKIE_FILE_BYTES = 1_048_576  # 1 MB


def cookies_path() -> str:
    """Absolute path to the stored cookies file."""
    return prefs.cookies_path()


def cookies_exists() -> bool:
    return os.path.isfile(cookies_path())


def _looks_like_netscape_cookies(text: str) -> bool:
    """Lightweight format check — no cookie values are logged."""
    if not text.strip():
        return False
    if text.lstrip().startswith("# Netscape HTTP Cookie File"):
        return True
    if text.lstrip().startswith("# HTTP Cookie File"):
        return True
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 7:
            return True
    return False


def save_cookies_file(data: bytes) -> None:
    """
    Validate and persist an uploaded cookies.txt file.
    Raises ValueError on invalid input.
    """
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > MAX_COOKIE_FILE_BYTES:
        raise ValueError("The file is too large (max 1 MB).")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("The file must be UTF-8 text.") from exc

    if not _looks_like_netscape_cookies(text):
        raise ValueError(
            "This doesn't look like a Netscape cookies.txt file. "
            "Export from a browser extension in Netscape/cookies.txt format."
        )

    path = cookies_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    prefs.set_file_perms(path)
    prefs.set_cookies_updated_at(datetime.now(timezone.utc).isoformat())

    ok, err = validate_youtube_cookies_file(path)
    if not ok:
        raise ValueError(err)


def _format_updated_at(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d, %Y at %I:%M %p")
    except ValueError:
        return ""


class CookiesFileProvider(AuthProvider):
    """Authentication via an exported cookies.txt file."""

    def id(self) -> str:
        return "cookies_file"

    def name(self) -> str:
        return "Cookies file"

    def is_available(self) -> bool:
        return True

    def connect(self, **kwargs) -> ConnectionState:
        if not cookies_exists():
            return ConnectionState(
                provider=self.id(),
                available=True,
                connected=False,
                message="No cookies file found.",
                error="Upload a cookies.txt file first.",
            )

        prefs.set_selected_provider(self.id())
        state = self.verify()
        if not state.connected:
            prefs.clear_prefs()
        return state

    def disconnect(self) -> ConnectionState:
        prefs.clear_prefs()
        return ConnectionState(
            provider=self.id(),
            available=True,
            connected=False,
            message="YouTube disconnected.",
            detail="Your cookies.txt file was kept — upload again to reconnect.",
        )

    def verify(self) -> ConnectionState:
        path = cookies_path()
        ok, err = validate_youtube_cookies_file(path)
        if not ok:
            return ConnectionState(
                provider=self.id(),
                available=True,
                connected=False,
                message="Connection failed.",
                detail=err,
                error=err,
            )

        updated = _format_updated_at(prefs.get_cookies_updated_at())
        detail = "Using cookies.txt"
        if updated:
            detail += f" · updated {updated}"

        return ConnectionState(
            provider=self.id(),
            available=True,
            connected=True,
            message="Connected to YouTube.",
            detail=detail,
        )

    def build_auth_args(self) -> list[str]:
        if not cookies_exists():
            return []
        return ["--cookies", cookies_path()]

    def to_dict(self) -> dict:
        if prefs.get_selected_provider() != self.id() or not cookies_exists():
            return ConnectionState(
                provider=self.id(),
                available=True,
                connected=False,
                message="YouTube not connected.",
            ).to_dict()

        ok, _ = validate_youtube_cookies_file(cookies_path())
        if not ok:
            return ConnectionState(
                provider=self.id(),
                available=True,
                connected=False,
                message="YouTube not connected.",
            ).to_dict()

        updated = _format_updated_at(prefs.get_cookies_updated_at())
        detail = "Using cookies.txt"
        if updated:
            detail += f" · updated {updated}"

        data = ConnectionState(
            provider=self.id(),
            available=True,
            connected=True,
            message="Connected to YouTube.",
            detail=detail,
        ).to_dict()
        data["cookies_configured"] = True
        data["cookies_updated_at"] = prefs.get_cookies_updated_at()
        return data
