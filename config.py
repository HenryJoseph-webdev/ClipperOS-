import os

# ─── App Identity ─────────────────────────────────────────────────────────────
APP_NAME    = "ClipperOS"
APP_VERSION = "1.2"

# ─── Base Download Folder ─────────────────────────────────────────────────────
BASE_DOWNLOAD_FOLDER = os.path.join(os.path.expanduser("~"), "Downloads", "ClipperOS")
JOB_DATABASE = os.environ.get(
    "CLIPPEROS_JOB_DB", os.path.join(BASE_DOWNLOAD_FOLDER, "jobs.sqlite3")
)
B2_APPLICATION_KEY_ID = os.environ.get("B2_APPLICATION_KEY_ID", "").strip()
B2_APPLICATION_KEY = os.environ.get("B2_APPLICATION_KEY", "").strip()
B2_BUCKET_NAME = os.environ.get("B2_BUCKET_NAME", "").strip()
B2_ENDPOINT = os.environ.get("B2_ENDPOINT", "").strip()
B2_REGION = os.environ.get("B2_REGION", "").strip()
B2_SIGNED_URL_TTL = int(os.environ.get("B2_SIGNED_URL_TTL", "900"))

# ─── Per-Platform Folders ─────────────────────────────────────────────────────
# (duplicate definition removed — was defined twice identically)
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
MAX_RETRIES      = 2
MAX_FILENAME_LEN = 80

# ─── Debug ────────────────────────────────────────────────────────────────────
DEBUG = False

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
# GEMINI_API_KEY: read from environment variable.
# To set it: set GEMINI_API_KEY=your_key_here  (Windows CMD)
#            $env:GEMINI_API_KEY="your_key_here"  (PowerShell)
#            export GEMINI_API_KEY=your_key_here  (bash/zsh)
# For development only, you may assign the key directly here,
# but never commit that value to git or sync it to cloud storage.
GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL     = "gemini-2.5-flash"
AI_PROVIDER      = os.environ.get("AI_PROVIDER", "gemini").strip().lower()
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODEL = os.environ.get(
    "OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731"
)
AI_MODEL = OPENROUTER_MODEL if AI_PROVIDER == "openrouter" else GEMINI_MODEL
ANALYSIS_VERSION = 1
TOP_CLIPS_COUNT  = 10
CHUNK_MINUTES    = 10
CHUNK_OVERLAP_SEC = 30
