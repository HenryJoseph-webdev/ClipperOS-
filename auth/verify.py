"""
auth/verify.py

Shared helpers for validating YouTube authentication without brittle
full yt-dlp download probes (format/JS challenge failures are not auth failures).
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional

# At least one of these indicates a signed-in YouTube session.
SESSION_COOKIE_NAMES = frozenset({
    "LOGIN_INFO",
    "SID",
    "__Secure-1PSID",
    "__Secure-3PSID",
    "SAPISID",
    "HSID",
})

AUTH_ERROR_PATTERNS = (
    r"sign in",
    r"login",
    r"not a bot",
    r"confirm you",
    r"private video",
    r"members only",
    r"authentication",
    r"account has been",
    r"dpapi",
    r"could not copy chrome cookie",
    r"could not find chrome cookies",
)

# yt-dlp failures that do NOT mean cookies are invalid.
NON_AUTH_ERROR_PATTERNS = (
    r"format is not available",
    r"only images are available",
    r"challenge solving failed",
    r"too many requests",
    r"http error 429",
    r"po token",
    r"visitor data",
    r"data sync id",
)


def parse_netscape_cookies(path: str) -> list[dict]:
    """Parse a Netscape cookies.txt file. Never logs cookie values."""
    cookies: list[dict] = []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, expiry_s, name, value = parts[:7]
        if "youtube.com" not in domain:
            continue
        try:
            expiry = int(expiry_s)
        except ValueError:
            expiry = 0
        cookies.append({
            "name": name,
            "value": value.strip(),
            "expiry": expiry,
            "domain": domain,
        })
    return cookies


def validate_youtube_cookies_file(path: str) -> tuple[bool, str]:
    """
    Validate a cookies.txt file for YouTube auth.
    Returns (ok, error_message).
    """
    if not os.path.isfile(path):
        return False, "No cookies file found. Upload cookies.txt to connect."

    cookies = parse_netscape_cookies(path)
    if not cookies:
        return False, (
            "No YouTube cookies found. Export cookies for youtube.com "
            "(not just google.com) while signed in."
        )

    now = time.time()
    session = [
        c for c in cookies
        if c["name"] in SESSION_COOKIE_NAMES and c["value"]
    ]
    if not session:
        return False, (
            "Missing login cookies. Sign in to YouTube in your browser, "
            "then export cookies again."
        )

    unexpired = [
        c for c in session
        if c["expiry"] == 0 or c["expiry"] > now
    ]
    if not unexpired:
        return False, "Cookies have expired. Export a fresh cookies.txt from your browser."

    return True, ""


def classify_ytdlp_auth_error(message: str) -> tuple[bool, str]:
    """
    Classify a yt-dlp error string.
    Returns (is_auth_failure, user_hint).
    """
    err = message or ""
    if any(re.search(p, err, re.I) for p in AUTH_ERROR_PATTERNS):
        if re.search(r"dpapi", err, re.I):
            return True, (
                "Browser cookies could not be decrypted on Windows. "
                "Use the Cookies file method instead."
            )
        if re.search(r"could not copy chrome cookie", err, re.I):
            return True, "Close your browser completely, then try again — or use Cookies file."
        return True, "YouTube session unavailable or expired."

    if any(re.search(p, err, re.I) for p in NON_AUTH_ERROR_PATTERNS):
        return False, ""

    return True, "yt-dlp could not verify this session."


def probe_with_ytdlp(opts: dict, url: str) -> tuple[bool, Optional[str]]:
    """
    Optional yt-dlp metadata probe. Treats format/JS/rate-limit errors as success
    when extraction got far enough — auth validation should not depend on formats.
    """
    try:
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
    except ImportError:
        return True, None  # file validation is enough; downloads will fail later with clear msg

    probe_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        **opts,
    }
    try:
        with YoutubeDL(probe_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info and info.get("id"):
            return True, None
        return True, None
    except DownloadError as exc:
        is_auth, hint = classify_ytdlp_auth_error(str(exc))
        if is_auth:
            return False, hint or "YouTube session unavailable or expired."
        return True, None
    except Exception:
        return True, None
