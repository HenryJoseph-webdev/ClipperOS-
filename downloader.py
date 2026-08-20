"""
downloader.py — ClipperOS v1.5

Switched from subprocess.run() to the yt-dlp Python API so that
--cookies-from-browser works correctly on Windows (DPAPI context match).

Public API is unchanged — webapp.py and clipper.py need no modifications.
"""

import shlex
import subprocess
import time
from typing import Optional

from config import (
    QUALITY_MAP, KICK_FORMAT, TWITCH_FORMAT,
    DEFAULT_QUALITY, MAX_RETRIES, DEBUG,
)
from utils import detect_platform, ensure_platform_folder, log_download

try:
    from auth import build_auth_args
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    def build_auth_args():
        return []

# ── yt-dlp Python API ────────────────────────────────────────────────────────
try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError, ExtractorError
    YTDLP_API = True
except ImportError:
    YTDLP_API = False


# ─── Secure command logging ───────────────────────────────────────────────────

SENSITIVE_FLAGS = {
    "--cookies-from-browser",
    "--cookies",
    "--username",
    "--password",
    "--add-header",
    "--http-header",
}


def redact_command(command: list) -> str:
    """
    Return a safe, loggable string for a yt-dlp command.
    Used by the terminal clipper.py which still uses subprocess.
    """
    parts: list[str] = []
    i = 0
    while i < len(command):
        arg = command[i]
        if arg in SENSITIVE_FLAGS:
            parts.append(arg)
            if i + 1 < len(command):
                parts.append("<redacted>")
                i += 2
                continue
        elif any(arg.startswith(flag + "=") for flag in SENSITIVE_FLAGS):
            parts.append(arg.split("=", 1)[0] + "=<redacted>")
        else:
            parts.append(arg)
        i += 1
    return " ".join(shlex.quote(p) for p in parts)


# ─── Auth args → yt-dlp options dict ─────────────────────────────────────────

def _auth_to_opts() -> dict:
    """
    Translate CLI auth args from build_auth_args() into yt-dlp option keys.

    build_auth_args() returns a flat list like:
      ["--cookies-from-browser", "chrome:Default"]
      ["--cookies", "cookies.txt"]
      []   (not connected)
    """
    args = build_auth_args()
    opts = {}
    i = 0
    while i < len(args):
        flag = args[i]
        if flag == "--cookies-from-browser" and i + 1 < len(args):
            opts["cookiesfrombrowser"] = (args[i + 1],)   # yt-dlp expects a tuple
            i += 2
        elif flag == "--cookies" and i + 1 < len(args):
            opts["cookiefile"] = args[i + 1]
            i += 2
        else:
            i += 1
    return opts


# ─── Format Resolution ────────────────────────────────────────────────────────

def get_format(url: str, quality: str = DEFAULT_QUALITY) -> str:
    platform = detect_platform(url)
    if platform == "kick":
        return KICK_FORMAT
    if platform == "twitch":
        return TWITCH_FORMAT
    return QUALITY_MAP.get(quality, QUALITY_MAP[DEFAULT_QUALITY])


# ─── Base yt-dlp options ──────────────────────────────────────────────────────

def _base_opts() -> dict:
    """Common yt-dlp options shared by all download types."""
    opts = {
        "quiet":           not DEBUG,
        "no_warnings":     not DEBUG,
        "noprogress":      False,
        "newline":         True,
    }
    opts.update(_auth_to_opts())
    return opts


# ─── Progress hook ────────────────────────────────────────────────────────────

def _make_progress_hook(label: str):
    """
    Returns a yt-dlp progress hook that prints to stdout.
    webapp.py captures stdout for job status updates.
    """
    def hook(d):
        status = d.get("status")
        if status == "downloading":
            pct     = d.get("_percent_str", "?%").strip()
            speed   = d.get("_speed_str", "?").strip()
            eta     = d.get("_eta_str", "?").strip()
            total   = d.get("_total_bytes_str", "?").strip()
            print(f"\r{label}: {pct} of {total} at {speed} ETA {eta}", end="", flush=True)
        elif status == "finished":
            print(f"\n✅ {label}: download finished, processing...")
        elif status == "error":
            print(f"\n❌ {label}: error during download")
    return hook


# ─── Core yt-dlp runner ───────────────────────────────────────────────────────

class _DownloadResult:
    """Mimics subprocess.CompletedProcess so webapp.py needs no changes."""
    def __init__(self, returncode: int, error: str = ""):
        self.returncode = returncode
        self.stderr     = error
        self.stdout     = ""


def _run_with_ydl(opts: dict, urls: list, label: str) -> _DownloadResult:
    """
    Run a yt-dlp download using the Python API with retry logic.
    Returns a _DownloadResult whose .returncode is 0 on success.
    """
    if not YTDLP_API:
        print("❌ yt-dlp is not installed. Run: pip install yt-dlp")
        return _DownloadResult(1, "yt-dlp not installed")

    last_error = ""

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            if DEBUG:
                print(f"\n🐛 {label} attempt {attempt} — opts: "
                      f"{ {k: v for k, v in opts.items() if k not in ('cookiesfrombrowser', 'cookiefile')} }")

            with YoutubeDL(opts) as ydl:
                ret = ydl.download(urls)

            if ret == 0:
                return _DownloadResult(0)

            last_error = f"yt-dlp returned exit code {ret}"
            if attempt <= MAX_RETRIES:
                print(f"\n⚠️  Attempt {attempt} failed. Retrying in 3 s... "
                      f"({MAX_RETRIES - attempt + 1} left)\n")
                time.sleep(3)
            else:
                print(f"\n❌ {label} failed after {attempt} attempt(s).")
                return _DownloadResult(ret, last_error)

        except DownloadError as e:
            last_error = str(e)
            if attempt <= MAX_RETRIES:
                print(f"\n⚠️  Attempt {attempt} error: {last_error[:120]}. Retrying...")
                time.sleep(3)
            else:
                print(f"\n❌ {label} failed: {last_error[:200]}")
                return _DownloadResult(1, last_error)

        except Exception as e:
            last_error = str(e)
            print(f"\n❌ Unexpected error: {last_error}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return _DownloadResult(1, last_error)

    return _DownloadResult(1, last_error)


# ─── Format Listing ───────────────────────────────────────────────────────────

def list_formats(url: str) -> bool:
    """List available formats for a URL. Returns True on success."""
    print("\n📋 Fetching available formats...\n")
    if not YTDLP_API:
        print("❌ yt-dlp not installed.")
        return False
    try:
        opts = {**_base_opts(), "listformats": True}
        with YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=False)
        return True
    except Exception as e:
        print(f"❌ Could not fetch formats: {e}")
        return False


# ─── Subprocess fallback (used by terminal clipper.py) ────────────────────────

def _build_base_command() -> list:
    """CLI command prefix — still used by clipper.py terminal interface."""
    cmd = ["yt-dlp"]
    cmd.extend(build_auth_args())
    return cmd


PROGRESS_ARGS = [
    "--newline",
    "--progress-template",
    "%(progress._percent_str)s of %(progress._total_bytes_str)s "
    "at %(progress._speed_str)s ETA %(progress._eta_str)s",
]


def _run_with_retry(command: list, label: str) -> Optional[subprocess.CompletedProcess]:
    """
    Subprocess runner — kept for clipper.py terminal interface.
    webapp.py now goes through _run_with_ydl() instead.
    """
    if DEBUG:
        print(f"\n🐛 DEBUG command: {redact_command(command)}\n")

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            result = subprocess.run(command)
            if result.returncode == 0:
                return result
            if attempt <= MAX_RETRIES:
                print(f"\n⚠️  Attempt {attempt} failed (exit {result.returncode}). "
                      f"Retrying in 3 s... ({MAX_RETRIES - attempt + 1} left)\n")
                time.sleep(3)
            else:
                print(f"\n❌ {label} failed after {attempt} attempt(s).")
                return result
        except FileNotFoundError:
            print("❌ yt-dlp is not installed or not found in PATH.")
            return None
        except PermissionError:
            print("❌ Permission denied.")
            return None
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return None

    return None


# ─── Full Download ────────────────────────────────────────────────────────────

def download_full(url: str, filename: str,
                  quality: str = DEFAULT_QUALITY) -> _DownloadResult:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    opts = {
        **_base_opts(),
        "format":           fmt,
        "paths":            {"home": folder},
        "outtmpl":          {"default": f"{filename}.%(ext)s"},
        "progress_hooks":   [_make_progress_hook("Downloading")],
    }

    result = _run_with_ydl(opts, [url], "Full download")
    if result.returncode == 0:
        log_download(platform, url, filename, clip=False)
    return result


# ─── Clip Download ────────────────────────────────────────────────────────────

def download_clip(url: str, start: str, end: str,
                  filename: str, quality: str = DEFAULT_QUALITY) -> _DownloadResult:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    opts = {
        **_base_opts(),
        "format":              fmt,
        "paths":               {"home": folder},
        "outtmpl":             {"default": f"{filename}.%(ext)s"},
        "download_ranges":     lambda info, ydl: [{"start_time": _ts(start), "end_time": _ts(end)}],
        "force_keyframes_at_cuts": True,
        "progress_hooks":      [_make_progress_hook(f"Clipping {start}→{end}")],
    }

    result = _run_with_ydl(opts, [url], "Clip download")
    if result.returncode == 0:
        log_download(platform, url, filename, clip=True, start=start, end=end)
    return result


def _ts(timestamp: str) -> float:
    """Convert HH:MM:SS to seconds for yt-dlp download_ranges."""
    parts = timestamp.strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(parts[0])
    except (ValueError, IndexError):
        return 0.0