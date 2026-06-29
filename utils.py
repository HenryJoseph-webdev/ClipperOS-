import os
import re
from datetime import datetime
from config import PLATFORM_FOLDERS, HISTORY_FILE, MAX_FILENAME_LEN


# ─── Folder Management ────────────────────────────────────────────────────────

def ensure_platform_folder(platform: str) -> str:
    """Create the platform subfolder if it doesn't exist, return its path."""
    folder = PLATFORM_FOLDERS.get(platform, PLATFORM_FOLDERS["unknown"])
    os.makedirs(folder, exist_ok=True)
    return folder


# ─── Platform Detection ───────────────────────────────────────────────────────

def detect_platform(url: str) -> str:
    """Return a platform key string from the URL."""
    url = url.lower()
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "kick.com" in url:
        return "kick"
    if "twitch.tv" in url:
        return "twitch"
    return "unknown"


# ─── Filename Cleanup ─────────────────────────────────────────────────────────

def clean_filename(name: str) -> str:
    """
    Strip platform auto-IDs and junk; enforce MAX_FILENAME_LEN.

    Examples:
      'XQC banned [clip_01KVRZHQQ1BWPA5PSCGEPQD6D8]' → 'XQC_banned'
      'VOD_1234567890'                                 → 'VOD'
      'My Sick Play'                                   → 'My_Sick_Play'
    """
    # Remove bracketed sections that look like auto-generated IDs
    # Pattern: bracket containing only alphanumeric chars + underscores (no spaces)
    name = re.sub(r"\s*[\[\(]\w+[\]\)]", "", name)
    # Strip any remaining bare bracket characters
    name = re.sub(r"[\[\](){}<>]", "", name)
    # Strip trailing Twitch/Kick clip IDs (alphanumeric 8+ chars after underscore)
    name = re.sub(r"_[A-Za-z0-9]{8,}$", "", name)
    # Replace spaces and dashes with underscores
    name = re.sub(r"[\s\-]+", "_", name.strip())
    # Remove characters that aren't alphanumeric, underscore, or dot
    name = re.sub(r"[^\w.]", "", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name).strip("_")
    name = name or "clip"
    # Enforce length limit
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN].rstrip("_")
    return name


# ─── Download History ─────────────────────────────────────────────────────────

def log_download(platform: str, url: str, filename: str, clip: bool = False,
                 start: str = None, end: str = None) -> None:
    """Append a one-liner entry to the history log."""
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        kind       = "CLIP" if clip else "FULL"
        time_range = f" [{start} → {end}]" if clip and start and end else ""
        entry = (
            f"[{timestamp}] {kind:<4} | {platform.upper():<8} | "
            f"{filename}{time_range} | {url}\n"
        )
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as e:
        print(f"   ⚠️  Could not write history: {e}")
