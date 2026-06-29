import subprocess
import time

from config import (
    QUALITY_MAP, KICK_FORMAT, TWITCH_FORMAT,
    DEFAULT_QUALITY, MAX_RETRIES, DEBUG,
)
from utils import detect_platform, ensure_platform_folder, log_download


# ─── Format Resolution ────────────────────────────────────────────────────────

def get_format(url: str, quality: str = DEFAULT_QUALITY) -> str:
    """Return the yt-dlp format string for this URL and quality choice."""
    platform = detect_platform(url)
    if platform == "kick":
        return KICK_FORMAT
    if platform == "twitch":
        return TWITCH_FORMAT
    return QUALITY_MAP.get(quality, QUALITY_MAP[DEFAULT_QUALITY])


# ─── Format Listing ───────────────────────────────────────────────────────────

def list_formats(url: str) -> bool:
    """Run yt-dlp -F and print available formats. Returns True on success."""
    print("\n📋 Fetching available formats...\n")
    try:
        result = subprocess.run(["yt-dlp", "-F", url])
        return result.returncode == 0
    except FileNotFoundError:
        print("❌ yt-dlp is not installed or not found in PATH.")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


# ─── Progress Args ────────────────────────────────────────────────────────────

PROGRESS_ARGS = [
    "--newline",
    "--progress-template",
    "%(progress._percent_str)s of %(progress._total_bytes_str)s "
    "at %(progress._speed_str)s ETA %(progress._eta_str)s",
]


# ─── Core Runner (with retry) ─────────────────────────────────────────────────

def _run_with_retry(command: list, label: str) -> subprocess.CompletedProcess | None:
    """
    Run a yt-dlp command, retrying up to MAX_RETRIES times on failure.
    Returns the CompletedProcess on success, None if all attempts fail.
    """
    if DEBUG:
        print(f"\n🐛 DEBUG command: {' '.join(command)}\n")

    for attempt in range(1, MAX_RETRIES + 2):   # +2: 1 initial + MAX_RETRIES retries
        try:
            result = subprocess.run(command)
            if result.returncode == 0:
                return result
            # Non-zero exit — maybe retry
            if attempt <= MAX_RETRIES:
                print(f"\n⚠️  Attempt {attempt} failed (exit {result.returncode}). "
                      f"Retrying in 3 s... ({MAX_RETRIES - attempt + 1} left)\n")
                time.sleep(3)
            else:
                print(f"\n❌ {label} failed after {attempt} attempt(s). "
                      f"(yt-dlp exit code: {result.returncode})")
                if DEBUG:
                    print(f"🐛 DEBUG: returncode={result.returncode}")
                return result

        except FileNotFoundError:
            print("❌ yt-dlp is not installed or not found in PATH.")
            return None
        except PermissionError:
            print("❌ Permission denied — check storage permissions.")
            return None
        except Exception as e:
            print(f"❌ Unexpected error during download: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            return None

    return None   # should never reach here, but satisfies type checkers


# ─── Full Download ────────────────────────────────────────────────────────────

def download_full(url: str, filename: str,
                  quality: str = DEFAULT_QUALITY) -> subprocess.CompletedProcess | None:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    command = [
        "yt-dlp",
        "-f", fmt,
        "-P", folder,
        "-o", f"{filename}.%(ext)s",
        *PROGRESS_ARGS,
        url,
    ]

    result = _run_with_retry(command, "Full download")
    if result and result.returncode == 0:
        log_download(platform, url, filename, clip=False)
    return result


# ─── Clip Download ────────────────────────────────────────────────────────────

def download_clip(url: str, start: str, end: str,
                  filename: str, quality: str = DEFAULT_QUALITY) -> subprocess.CompletedProcess | None:
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    fmt      = get_format(url, quality)

    command = [
        "yt-dlp",
        "-f", fmt,
        "--download-sections", f"*{start}-{end}",
        "-P", folder,
        "-o", f"{filename}.%(ext)s",
        *PROGRESS_ARGS,
        url,
    ]

    result = _run_with_retry(command, "Clip download")
    if result and result.returncode == 0:
        log_download(platform, url, filename, clip=True, start=start, end=end)
    return result
