"""
downloader.py — ClipperOS v1.5.1

Changes from v1.5:
  - _make_progress_hook() now accepts an optional on_progress callback
    (signature: fn(percent: int, message: str)) so webapp.py can wire
    real yt-dlp progress into the job system.
  - _make_postprocessor_hook() captures the final output file path and
    calls an optional on_done callback (signature: fn(filepath: str)).
  - download_full() and download_clip() accept optional on_progress and
    on_done kwargs and pass them through to the hooks.
  - _run_with_ydl() also accepts and passes those hooks.
  - _DownloadResult gains an output_path field.
  - ALL existing behaviour, format strings, section-download logic,
    auth injection, retry logic and 1080p selection are UNCHANGED.
"""

import os
import shlex
import subprocess
import time
from typing import Callable, Optional

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
    "--cookies-from-browser", "--cookies", "--username",
    "--password", "--add-header", "--http-header",
}


def redact_command(command: list) -> str:
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
    args = build_auth_args()
    opts = {}
    i = 0
    while i < len(args):
        flag = args[i]
        if flag == "--cookies-from-browser" and i + 1 < len(args):
            opts["cookiesfrombrowser"] = (args[i + 1],)
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
        "quiet":       not DEBUG,
        "no_warnings": not DEBUG,
        "noprogress":  False,
        "newline":     True,
    }
    opts.update(_auth_to_opts())
    return opts


# ─── Progress hook ────────────────────────────────────────────────────────────

def _make_progress_hook(
    label: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
):
    """
    Returns a yt-dlp progress hook.

    Prints to stdout (for terminal clipper.py) AND calls on_progress(pct, msg)
    when provided so webapp.py can push real percentages into the job system.

    yt-dlp phases:
      "downloading"    — active download, percent available
      "finished"       — file saved, ffmpeg merge/pp may follow
      "error"          — download failed
    """
    def hook(d: dict):
        status = d.get("status")

        if status == "downloading":
            pct_str = d.get("_percent_str", "").strip()
            speed   = d.get("_speed_str",   "N/A").strip()
            eta     = d.get("_eta_str",     "N/A").strip()
            total   = d.get("_total_bytes_str", "N/A").strip()

            # Parse numeric percent for the progress bar
            pct_num = 0
            try:
                pct_num = int(float(pct_str.rstrip("%")))
            except (ValueError, AttributeError):
                pass

            msg = f"Downloading — {pct_str} of {total} at {speed} ETA {eta}"
            print(f"\r{label}: {msg}", end="", flush=True)

            if on_progress is not None:
                # Reserve 0–90 for downloading; 90–100 for post-processing
                scaled = min(90, int(pct_num * 0.9))
                on_progress(scaled, msg)

        elif status == "finished":
            msg = "Processing…"
            print(f"\n✅ {label}: download finished, processing...")
            if on_progress is not None:
                # Signal processing phase — 92% so bar shows almost done
                on_progress(92, msg)

        elif status == "error":
            print(f"\n❌ {label}: error during download")
            if on_progress is not None:
                on_progress(0, "Error during download")

    return hook


# ─── Post-processor hook (captures final output path) ─────────────────────────

def _make_postprocessor_hook(
    on_done: Optional[Callable[[str], None]] = None,
):
    """
    Returns a yt-dlp postprocessor hook.

    Called after each postprocessor completes. The final call (status='finished')
    carries the real output file path in info_dict['filepath'].
    """
    def hook(d: dict):
        if d.get("status") == "finished":
            # filepath is the actual output file after all post-processing
            filepath = (
                d.get("info_dict", {}).get("filepath")
                or d.get("filepath")
                or ""
            )
            if filepath and on_done is not None:
                on_done(os.path.abspath(filepath))

    return hook


# ─── Result object ────────────────────────────────────────────────────────────

class _DownloadResult:
    """Mimics subprocess.CompletedProcess. output_path added in v1.5.1."""
    def __init__(self, returncode: int, error: str = "", output_path: str = ""):
        self.returncode  = returncode
        self.stderr      = error
        self.stdout      = ""
        self.output_path = output_path   # absolute path of the created file


# ─── Core yt-dlp runner ───────────────────────────────────────────────────────

def _run_with_ydl(
    opts: dict,
    urls: list,
    label: str,
    on_progress: Optional[Callable[[int, str], None]] = None,
    on_done:     Optional[Callable[[str], None]] = None,
) -> _DownloadResult:
    """
    Run a yt-dlp download using the Python API with retry logic.

    on_progress(pct: int, msg: str) — called with real download percentage.
    on_done(filepath: str)          — called once with the final output path.
    """
    if not YTDLP_API:
        print("❌ yt-dlp is not installed. Run: pip install yt-dlp")
        return _DownloadResult(1, "yt-dlp not installed")

    # Inject real hooks if callbacks provided
    if on_progress is not None or on_done is not None:
        existing_progress = opts.get("progress_hooks", [])
        existing_pp       = opts.get("postprocessor_hooks", [])

        # Replace the plain progress hook with the enhanced version
        # that calls on_progress
        new_progress_hook = _make_progress_hook(label, on_progress)
        opts = {
            **opts,
            "progress_hooks":       [new_progress_hook],
            "postprocessor_hooks":  existing_pp + ([_make_postprocessor_hook(on_done)] if on_done else []),
        }

    last_error  = ""
    output_path = ""

    # Simple wrapper so postprocessor hook can write back to us
    captured = {"path": ""}
    if on_done is not None:
        orig_on_done = on_done
        def _capture_and_forward(fp: str):
            captured["path"] = fp
            orig_on_done(fp)
        # Replace the hook in opts
        opts = {
            **opts,
            "postprocessor_hooks": [
                h for h in opts.get("postprocessor_hooks", [])
                if not hasattr(h, "_is_capture_hook")
            ] + [_make_postprocessor_hook(_capture_and_forward)],
        }

    for attempt in range(1, MAX_RETRIES + 2):
        try:
            if DEBUG:
                safe = {k: v for k, v in opts.items()
                        if k not in ("cookiesfrombrowser", "cookiefile")}
                print(f"\n🐛 {label} attempt {attempt} — opts: {safe}")

            with YoutubeDL(opts) as ydl:
                ret = ydl.download(urls)

            if ret == 0:
                return _DownloadResult(0, output_path=captured["path"])

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

def download_full(
    url: str,
    filename: str,
    quality: str = DEFAULT_QUALITY,
    on_progress: Optional[Callable[[int, str], None]] = None,
    on_done:     Optional[Callable[[str], None]] = None,
) -> _DownloadResult:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    opts = {
        **_base_opts(),
        "format":             fmt,
        "paths":              {"home": folder},
        "outtmpl":            {"default": f"{filename}.%(ext)s"},
        "progress_hooks":     [_make_progress_hook("Downloading")],
        "postprocessor_hooks": [],
    }

    result = _run_with_ydl(opts, [url], "Full download",
                           on_progress=on_progress, on_done=on_done)
    if result.returncode == 0:
        log_download(platform, url, filename, clip=False)
    return result


# ─── Clip Download ────────────────────────────────────────────────────────────

def download_clip(
    url: str,
    start: str,
    end: str,
    filename: str,
    quality: str = DEFAULT_QUALITY,
    on_progress: Optional[Callable[[int, str], None]] = None,
    on_done:     Optional[Callable[[str], None]] = None,
) -> _DownloadResult:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    opts = {
        **_base_opts(),
        "format":                  fmt,
        "paths":                   {"home": folder},
        "outtmpl":                 {"default": f"{filename}.%(ext)s"},
        "download_ranges":         lambda info, ydl: [{"start_time": _ts(start), "end_time": _ts(end)}],
        "force_keyframes_at_cuts": True,
        "progress_hooks":          [_make_progress_hook(f"Clipping {start}→{end}")],
        "postprocessor_hooks":     [],
    }

    result = _run_with_ydl(opts, [url], "Clip download",
                           on_progress=on_progress, on_done=on_done)
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
