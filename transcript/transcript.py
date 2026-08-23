"""
transcript/transcript.py

Single responsibility: everything to do with transcripts.
  - download_transcript(url)            → Transcript | None
  - clean_transcript(transcript)        → Transcript
  - save_transcript(transcript)         → str (path)
  - load_transcript(video_id, platform) → Transcript | None
  - delete_transcript(video_id, platform) → bool
  - transcript_exists(video_id, platform) → bool

Nothing AI. Nothing downloading video. Just transcripts.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from config import TRANSCRIPT_FOLDERS, DEBUG
from models import Transcript
from utils import detect_platform
from downloader import redact_command
from auth import build_auth_args


# ─── Internal Helpers ─────────────────────────────────────────────────────────

def _transcript_path(video_id: str, platform: str) -> str:
    """Return the canonical .txt path for this video's transcript."""
    folder = TRANSCRIPT_FOLDERS.get(platform, TRANSCRIPT_FOLDERS["unknown"])
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{video_id}.txt")


def _extract_video_id(url: str) -> str:
    """
    Pull the platform-native video ID from a URL.

    YouTube  : ?v=LXvv6CbGg8A  or  youtu.be/LXvv6CbGg8A
    Twitch   : twitch.tv/videos/2799245281
    Kick     : kick.com/streamer/clip/clip_01KV...
    Fallback : last non-empty path segment
    """
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    m = re.search(r"twitch\.tv/videos/(\d+)", url)
    if m:
        return m.group(1)

    m = re.search(r"twitch\.tv/\w+/clip/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    m = re.search(r"kick\.com/.+/clip/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    # Fallback: last non-empty path segment before query string
    path = url.rstrip("/").split("/")[-1].split("?")[0]
    return path or "unknown"


def _parse_vtt(raw: str) -> list[tuple[str, str]]:
    """
    Parse a VTT/SRT string into (HH:MM:SS, text) pairs.

    Strips cue headers, HTML tags, and deduplicates repeated caption lines
    that auto-generated VTT files often repeat across consecutive cues.
    """
    lines: list[tuple[str, str]] = []
    current_time: Optional[str] = None
    seen_texts: set[str] = set()

    for line in raw.splitlines():
        line = line.strip()

        # Timestamp line: 00:01:23.456 --> 00:01:25.789
        m = re.match(
            r"(\d{1,2}:\d{2}:\d{2})[\.,]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}",
            line,
        )
        if m:
            raw_ts = m.group(1)
            parts  = raw_ts.split(":")
            # Normalise to HH:MM:SS
            if len(parts) == 2:
                raw_ts = f"00:{int(parts[0]):02d}:{int(parts[1]):02d}"
            current_time = raw_ts
            continue

        # Skip WEBVTT header, NOTE blocks, numeric cue IDs, blank lines
        if not line or line.startswith("WEBVTT") or line.startswith("NOTE") or line.isdigit():
            continue

        if current_time:
            text = re.sub(r"<[^>]+>", "", line).strip()   # strip HTML tags
            if text and text not in seen_texts:
                lines.append((current_time, text))
                seen_texts.add(text)

    return lines


def _lines_to_plain(lines: list[tuple[str, str]]) -> str:
    """Convert parsed lines to a readable plain-text block for the AI."""
    return "\n".join(f"[{ts}] {text}" for ts, text in lines)


# ─── Public API ───────────────────────────────────────────────────────────────

def transcript_exists(video_id: str, platform: str) -> bool:
    """Return True if a saved transcript file exists for this video."""
    return os.path.isfile(_transcript_path(video_id, platform))


def download_transcript(url: str) -> Optional[Transcript]:
    """
    Download captions for a video URL using yt-dlp.

    Tries manual captions first, falls back to auto-generated.
    Returns a Transcript with raw VTT content, or None if unavailable.
    Twitch and Kick rarely have captions — returns None cleanly.
    """
    platform = detect_platform(url)
    video_id = _extract_video_id(url)

    print(f"\n📄 Fetching transcript  [{video_id}  {platform}]...")

    # Do not create transcript paths for unsupported or malformed input. A
    # host-only value such as 192.168.1.10:5000 is not a media URL; treating
    # its fallback segment as a video ID would create an invalid Windows path.
    if platform == "unknown":
        print("Unsupported media URL; cannot fetch captions.")
        return None

    # Use an OS-generated name rather than incorporating user input into a
    # filesystem path. This preserves the transcript layout and avoids path
    # traversal and platform-specific filename characters.
    transcript_folder = TRANSCRIPT_FOLDERS[platform]
    os.makedirs(transcript_folder, exist_ok=True)
    tmp_dir = tempfile.mkdtemp(prefix="_tmp_", dir=transcript_folder)

    command = [
        "yt-dlp",
        *build_auth_args(),
        "--write-auto-sub",
        "--write-sub",
        "--sub-lang",   "en",
        "--sub-format", "vtt",
        "--skip-download",
        "--no-playlist",
        "-o", os.path.join(tmp_dir, "%(id)s.%(ext)s"),
        url,
    ]

    if DEBUG:
        print("🐛 transcript command: {}".format(redact_command(command)))

    try:
        result = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError:
        print("❌ yt-dlp not found. Install it with: pip install yt-dlp")
        return None
    except Exception as exc:
        print(f"❌ Unexpected error running yt-dlp: {exc}")
        return None

    # ── Find the .vtt file yt-dlp wrote ──────────────────────────────────────
    vtt_content = ""
    title       = ""

    try:
        for fname in os.listdir(tmp_dir):
            if fname.endswith(".vtt"):
                vtt_path = os.path.join(tmp_dir, fname)
                try:
                    with open(vtt_path, "r", encoding="utf-8") as f:
                        vtt_content = f.read()
                except OSError as exc:
                    print(f"⚠️  Could not read subtitle file: {exc}")
                finally:
                    try:
                        os.remove(vtt_path)
                    except OSError:
                        pass
    except OSError:
        pass

    # Clean up temp directory
    try:
        os.rmdir(tmp_dir)
    except OSError:
        pass   # non-empty — leave it, user can clean manually

    if not vtt_content:
        print(f"⚠️  No captions found for this {platform} video.")
        if platform in ("twitch", "kick"):
            print("   Twitch/Kick clips rarely have captions.")
            print("   Speech-to-text support is planned for a future release.")
        return None

    # Best-effort title extraction from yt-dlp stdout
    for line in result.stdout.splitlines():
        m = re.search(r"\[(?:youtube|twitch|kick)\]\s+\S+:\s+(.+)", line)
        if m:
            title = m.group(1).strip()
            break

    return Transcript(
        video_id   = video_id,
        platform   = platform,
        title      = title,
        content    = vtt_content,
        fetched_at = datetime.now(),
    )


def clean_transcript(transcript: Transcript) -> Transcript:
    """
    Parse raw VTT content into structured lines and a clean plain-text block.

    Mutates and returns the same Transcript object.
    Always call this before save_transcript() or passing to ai.py.
    """
    if not transcript.content:
        return transcript

    transcript.lines   = _parse_vtt(transcript.content)
    transcript.content = _lines_to_plain(transcript.lines)
    return transcript


def save_transcript(transcript: Transcript) -> str:
    """
    Write the transcript to disk as <video_id>.txt.

    File format:
        Title:    <title>
        Channel:  <channel>
        ID:       <video_id>
        Platform: <platform>
        Language: <language>
        Date:     <ISO datetime>
        Words:    <word count>
        ---
        [00:00:01] Hello and welcome...

    Returns the absolute path, or "" on failure.
    """
    path = _transcript_path(transcript.video_id, transcript.platform)

    header = (
        f"Title:    {transcript.title}\n"
        f"Channel:  {transcript.channel}\n"
        f"ID:       {transcript.video_id}\n"
        f"Platform: {transcript.platform}\n"
        f"Language: {transcript.language}\n"
        f"Date:     {transcript.fetched_at.isoformat()}\n"
        f"Words:    {transcript.word_count()}\n"
        f"---\n"
    )

    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(header)
            f.write(transcript.content)
        transcript.file_path = path
        print(f"💾 Transcript saved → {path}")
        return path
    except OSError as exc:
        print(f"❌ Could not save transcript: {exc}")
        return ""


def load_transcript(video_id: str, platform: str) -> Optional[Transcript]:
    """
    Load a previously saved transcript from disk.

    Parses the header back into Transcript fields.
    Returns None if the file doesn't exist or can't be read.
    """
    path = _transcript_path(video_id, platform)

    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        print(f"❌ Could not load transcript: {exc}")
        return None

    # Split header from body on the --- separator
    if "---\n" in raw:
        header_block, content = raw.split("---\n", 1)
    else:
        header_block, content = "", raw

    meta: dict[str, str] = {}
    for line in header_block.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            meta[key.strip().lower()] = val.strip()

    transcript = Transcript(
        video_id  = meta.get("id",       video_id),
        platform  = meta.get("platform", platform),
        title     = meta.get("title",    ""),
        channel   = meta.get("channel",  ""),
        language  = meta.get("language", "en"),
        content   = content.strip(),
        file_path = path,
    )

    # Re-parse lines so ai.py can chunk them immediately
    transcript.lines = [
        (m.group(1), m.group(2))
        for line in content.splitlines()
        if (m := re.match(r"\[(\d{2}:\d{2}:\d{2})\]\s+(.+)", line))
    ]

    return transcript


def delete_transcript(video_id: str, platform: str) -> bool:
    """
    Delete the saved transcript file for this video.

    Returns True if deleted, False if the file didn't exist or deletion failed.
    """
    path = _transcript_path(video_id, platform)

    if not os.path.isfile(path):
        print(f"⚠️  No transcript found for {video_id}.")
        return False

    try:
        os.remove(path)
        print(f"🗑️  Transcript deleted: {path}")
        return True
    except OSError as exc:
        print(f"❌ Could not delete transcript: {exc}")
        return False
