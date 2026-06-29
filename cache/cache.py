"""
cache/cache.py

Single responsibility: persist and retrieve Analysis objects to/from disk.

  - save_analysis(analysis)                   → str (path)
  - load_analysis(video_id, platform)         → Analysis | None
  - analysis_exists(video_id, platform)       → bool
  - is_stale(video_id, platform)              → bool
  - delete_analysis(video_id, platform)       → bool
  - invalidate_all()                          → int (files deleted)

Cache files live at:
    cache_data/<platform>/<video_id>.json

Every file carries analysis_version. If that version doesn't match
config.ANALYSIS_VERSION, the entry is treated as stale and ignored —
the caller should delete it and re-analyze.
"""

from __future__ import annotations

import json
import os
from typing import Optional

import config
from config import CACHE_FOLDERS, DEBUG
from models import Analysis


# ─── Internal Helpers ─────────────────────────────────────────────────────────

def _cache_path(video_id: str, platform: str) -> str:
    """Return the canonical .json path for this video's cached analysis."""
    folder = CACHE_FOLDERS.get(platform, CACHE_FOLDERS["unknown"])
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{video_id}.json")


# ─── Public API ───────────────────────────────────────────────────────────────

def analysis_exists(video_id: str, platform: str) -> bool:
    """Return True if a cache file exists, regardless of whether it's stale."""
    return os.path.isfile(_cache_path(video_id, platform))


def is_stale(video_id: str, platform: str) -> bool:
    """
    Return True if:
      - no cache file exists, OR
      - the file's analysis_version doesn't match config.ANALYSIS_VERSION.

    Reads only the version field — doesn't deserialize the whole file.
    """
    path = _cache_path(video_id, platform)

    if not os.path.isfile(path):
        return True

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        cached_version = data.get("analysis_version", -1)
        stale = cached_version != config.ANALYSIS_VERSION
        if stale and DEBUG:
            print(f"🐛 Cache stale: file v{cached_version} vs current v{config.ANALYSIS_VERSION}")
        return stale
    except (OSError, json.JSONDecodeError) as exc:
        if DEBUG:
            print(f"🐛 Cache read error during staleness check: {exc}")
        return True   # treat unreadable files as stale


def save_analysis(analysis: Analysis) -> str:
    """
    Serialize an Analysis to JSON and write it to the cache.

    Returns the absolute path written, or "" on failure.
    """
    path = _cache_path(analysis.video_id, analysis.platform)

    try:
        data = analysis.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        if DEBUG:
            print(f"🐛 Cache written: {path}")

        print(f"💾 Analysis cached → {path}")
        return path

    except OSError as exc:
        print(f"❌ Could not write cache: {exc}")
        return ""
    except (TypeError, ValueError) as exc:
        print(f"❌ Could not serialize analysis: {exc}")
        return ""


def load_analysis(video_id: str, platform: str) -> Optional[Analysis]:
    """
    Load a cached Analysis from disk.

    Returns None if:
      - the file doesn't exist
      - the file is stale (version mismatch)
      - the file is corrupt / unreadable

    The caller is responsible for deleting stale entries and re-analyzing.
    Use is_stale() first if you want to distinguish those cases.
    """
    path = _cache_path(video_id, platform)

    if not os.path.isfile(path):
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"❌ Could not read cache file: {exc}")
        return None

    # Version check — don't deserialize stale data
    cached_version = data.get("analysis_version", -1)
    if cached_version != config.ANALYSIS_VERSION:
        print(
            f"⚠️  Cache is stale for {video_id} "
            f"(v{cached_version} → current v{config.ANALYSIS_VERSION}). "
            f"Re-analysis needed."
        )
        return None

    try:
        return Analysis.from_dict(data)
    except (KeyError, ValueError, TypeError) as exc:
        print(f"❌ Cache file is corrupt — could not deserialize: {exc}")
        if DEBUG:
            import traceback
            traceback.print_exc()
        return None


def delete_analysis(video_id: str, platform: str) -> bool:
    """
    Delete the cached analysis file for this video.

    Returns True if deleted, False if it didn't exist or deletion failed.
    """
    path = _cache_path(video_id, platform)

    if not os.path.isfile(path):
        if DEBUG:
            print(f"🐛 No cache to delete for {video_id}")
        return False

    try:
        os.remove(path)
        print(f"🗑️  Cache deleted: {path}")
        return True
    except OSError as exc:
        print(f"❌ Could not delete cache file: {exc}")
        return False


def invalidate_all() -> int:
    """
    Delete every cache file whose analysis_version doesn't match
    config.ANALYSIS_VERSION. Safe to call after bumping the version.

    Returns the number of files deleted.
    """
    deleted = 0

    for platform, folder in CACHE_FOLDERS.items():
        if not os.path.isdir(folder):
            continue

        for fname in os.listdir(folder):
            if not fname.endswith(".json"):
                continue

            fpath = os.path.join(folder, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("analysis_version", -1) != config.ANALYSIS_VERSION:
                    os.remove(fpath)
                    deleted += 1
                    if DEBUG:
                        print(f"🐛 Invalidated: {fpath}")
            except (OSError, json.JSONDecodeError):
                # Unreadable file — delete it too
                try:
                    os.remove(fpath)
                    deleted += 1
                except OSError:
                    pass

    if deleted:
        print(f"🗑️  Invalidated {deleted} stale cache file(s).")
    else:
        print("✅ All cache files are current.")

    return deleted
