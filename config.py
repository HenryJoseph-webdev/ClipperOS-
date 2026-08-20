import os

# ─── App Identity ─────────────────────────────────────────────────────────────
APP_NAME    = "ClipperOS"
APP_VERSION = "1.2"

# ─── Base Download Folder ─────────────────────────────────────────────────────
BASE_DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads", "ClipperOS")

PLATFORM_FOLDERS = {
    "youtube": os.path.join(BASE_DOWNLOAD_FOLDER, "YouTube"),
    "kick":    os.path.join(BASE_DOWNLOAD_FOLDER, "Kick"),
    "twitch":  os.path.join(BASE_DOWNLOAD_FOLDER, "Twitch"),
    "unknown": os.path.join(BASE_DOWNLOAD_FOLDER, "Other"),
}

# ─── Per-Platform Folders ─────────────────────────────────────────────────────
PLATFORM_FOLDERS = {
    "youtube": os.path.join(BASE_DOWNLOAD_FOLDER, "YouTube"),
    "kick":    os.path.join(BASE_DOWNLOAD_FOLDER, "Kick"),
    "twitch":  os.path.join(BASE_DOWNLOAD_FOLDER, "Twitch"),
    "unknown": os.path.join(BASE_DOWNLOAD_FOLDER, "Other"),
}

# ─── Format Strings ───────────────────────────────────────────────────────────
YOUTUBE_FORMAT_720  = "bestvideo[height<=720][vcodec*=avc1]+bestaudio/best[height<=720]"
YOUTUBE_FORMAT_1080 = "bestvideo[height<=1080][vcodec*=avc1]+bestaudio/best[height<=1080]"
YOUTUBE_FORMAT_1440 = "bestvideo[height<=1440][vcodec*=avc1]+bestaudio/best[height<=1440]"

KICK_FORMAT   = "0"
TWITCH_FORMAT = "best"

QUALITY_MAP = {
    "720p":  YOUTUBE_FORMAT_720,
    "1080p": YOUTUBE_FORMAT_1080,
    "1440p": YOUTUBE_FORMAT_1440,
}

DEFAULT_QUALITY = "1080p"

# ─── Download Behaviour ───────────────────────────────────────────────────────
MAX_RETRIES      = 2          # how many times to retry a failed download
MAX_FILENAME_LEN = 80         # characters — truncate anything longer

# ─── Debug ────────────────────────────────────────────────────────────────────
DEBUG = False                 # set True to print yt-dlp commands + extra errors

# ─── History Log ──────────────────────────────────────────────────────────────
HISTORY_FILE = os.path.join(BASE_DOWNLOAD_FOLDER, "download_history.log")

# ─── Transcript Storage ───────────────────────────────────────────────────────
TRANSCRIPT_BASE = os.path.join(BASE_DOWNLOAD_FOLDER, "transcripts")
TRANSCRIPT_FOLDERS = {
    "youtube": os.path.join(TRANSCRIPT_BASE, "youtube"),
    "twitch":  os.path.join(TRANSCRIPT_BASE, "twitch"),
    "kick":    os.path.join(TRANSCRIPT_BASE, "kick"),
    "unknown": os.path.join(TRANSCRIPT_BASE, "unknown"),
}

# ─── Cache Storage ────────────────────────────────────────────────────────────
CACHE_BASE = os.path.join(BASE_DOWNLOAD_FOLDER, "cache_data")
CACHE_FOLDERS = {
    "youtube": os.path.join(CACHE_BASE, "youtube"),
    "twitch":  os.path.join(CACHE_BASE, "twitch"),
    "kick":    os.path.join(CACHE_BASE, "kick"),
    "unknown": os.path.join(CACHE_BASE, "unknown"),
}

# ─── AI ───────────────────────────────────────────────────────────────────────
GEMINI_API_KEY = "AQ.Ab8RN6I_nutil9exidy3gwsEeGu5hxTLYjR1KCkseUel6arQsw"
GEMINI_MODEL     = "gemini-2.5-flash"
ANALYSIS_VERSION = 1        # bump this to auto-invalidate all cached analyses
TOP_CLIPS_COUNT  = 10       # how many clips AI should return
CHUNK_MINUTES    = 10       # transcript chunk size in minutes
CHUNK_OVERLAP_SEC = 30      # overlap between chunks (catches cross-boundary moments)
