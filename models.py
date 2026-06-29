

"""
models.py — shared data structures for ClipperOS.

Every module imports from here. Nothing else imports from this file.
This is the contract between transcript.py, ai.py, cache.py, and clipper.py.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ─── Timestamp ────────────────────────────────────────────────────────────────

@dataclass
class Timestamp:
    """
    A moment in a video expressed as HH:MM:SS.

    Stored as a string (matching yt-dlp's --download-sections format)
    but converts to/from total seconds for any arithmetic you need.
    """
    raw: str   # e.g. "00:12:42"

    # ── Construction helpers ──────────────────────────────────────────────────

    @classmethod
    def from_seconds(cls, total_seconds: float) -> "Timestamp":
        """Build a Timestamp from a number of seconds."""
        total_seconds = max(0.0, total_seconds)
        h = int(total_seconds // 3600)
        m = int((total_seconds % 3600) // 60)
        s = int(total_seconds % 60)
        return cls(raw=f"{h:02d}:{m:02d}:{s:02d}")

    @classmethod
    def from_string(cls, s: str) -> "Timestamp":
        """Accept HH:MM:SS, MM:SS, or plain seconds as a string."""
        s = s.strip()
        parts = s.split(":")
        if len(parts) == 3:
            return cls(raw=f"{int(parts[0]):02d}:{int(parts[1]):02d}:{int(parts[2]):02d}")
        if len(parts) == 2:
            return cls(raw=f"00:{int(parts[0]):02d}:{int(parts[1]):02d}")
        # plain seconds
        return cls.from_seconds(float(s))

    # ── Conversion ────────────────────────────────────────────────────────────

    def to_seconds(self) -> float:
        """Return total seconds as a float."""
        parts = self.raw.split(":")
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])

    def __str__(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return f"Timestamp('{self.raw}')"


# ─── Transcript ───────────────────────────────────────────────────────────────

@dataclass
class Transcript:
    """
    A downloaded transcript tied to one video.

    video_id  — platform-native ID (e.g. 'LXvv6CbGg8A', '2799245281')
    platform  — 'youtube' | 'twitch' | 'kick' | 'unknown'
    language  — BCP-47 code, e.g. 'en', 'en-US'
    content   — raw VTT/SRT/plain text as downloaded
    lines     — parsed list of (timestamp_str, text) pairs; populated by clean()
    """
    video_id:     str
    platform:     str
    title:        str                        = ""
    channel:      str                        = ""
    language:     str                        = "en"
    content:      str                        = ""
    lines:        list[tuple[str, str]]      = field(default_factory=list)
    fetched_at:   datetime                   = field(default_factory=datetime.now)
    file_path:    Optional[str]              = None   # set after saving to disk

    def is_empty(self) -> bool:
        return not self.content.strip()

    def word_count(self) -> int:
        return len(self.content.split())

    def duration_hint(self) -> Optional[str]:
        """Return the last timestamp in lines as a rough video-length hint."""
        if self.lines:
            return self.lines[-1][0]
        return None


# ─── Clip ─────────────────────────────────────────────────────────────────────

@dataclass
class Clip:
    """
    A single moment the AI identified as worth clipping.

    rank   — 1-based position in the sorted results (1 = best)
    score  — viral potential 1.0–10.0 as returned by Gemini
    """
    rank:    int
    start:   Timestamp
    end:     Timestamp
    title:   str
    reason:  str
    score:   float

    def duration_seconds(self) -> float:
        return self.end.to_seconds() - self.start.to_seconds()

    def duration_str(self) -> str:
        secs = self.duration_seconds()
        m, s = divmod(int(secs), 60)
        return f"{m}m {s}s"

    def to_dict(self) -> dict:
        return {
            "rank":   self.rank,
            "start":  self.start.raw,
            "end":    self.end.raw,
            "title":  self.title,
            "reason": self.reason,
            "score":  self.score,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Clip":
        return cls(
            rank   = d["rank"],
            start  = Timestamp.from_string(d["start"]),
            end    = Timestamp.from_string(d["end"]),
            title  = d["title"],
            reason = d["reason"],
            score  = float(d["score"]),
        )

    def __str__(self) -> str:
        return (
            f"#{self.rank:>2}  [{self.start} → {self.end}]  "
            f"score {self.score:.1f}  {self.title}"
        )


# ─── AIResponse ───────────────────────────────────────────────────────────────

@dataclass
class AIResponse:
    """
    Raw response from a single Gemini API call for one transcript chunk.

    chunk_index  — which chunk produced this (0-based)
    raw_json     — the string Gemini returned before parsing
    clips        — parsed Clip objects from this chunk
    error        — non-empty if the call or parse failed
    """
    chunk_index: int
    raw_json:    str                   = ""
    clips:       list[Clip]            = field(default_factory=list)
    error:       str                   = ""

    def ok(self) -> bool:
        return not self.error and bool(self.clips)


# ─── Analysis ─────────────────────────────────────────────────────────────────

@dataclass
class Analysis:
    """
    The complete result of analyzing one video's transcript.

    This is what cache.py writes to disk and reads back.
    analysis_version must match config.ANALYSIS_VERSION or the cache is stale.
    """
    analysis_version: int
    ai_model:         str
    video_id:         str
    platform:         str
    analyzed_at:      datetime              = field(default_factory=datetime.now)
    clips:            list[Clip]            = field(default_factory=list)
    chunk_responses:  list[AIResponse]      = field(default_factory=list)

    def top(self, n: int = 10) -> list[Clip]:
        """Return the top-n clips sorted by score descending."""
        return sorted(self.clips, key=lambda c: c.score, reverse=True)[:n]

    def to_dict(self) -> dict:
        return {
            "analysis_version": self.analysis_version,
            "ai_model":         self.ai_model,
            "video_id":         self.video_id,
            "platform":         self.platform,
            "analyzed_at":      self.analyzed_at.isoformat(),
            "clips":            [c.to_dict() for c in self.clips],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Analysis":
        return cls(
            analysis_version = d["analysis_version"],
            ai_model         = d["ai_model"],
            video_id         = d["video_id"],
            platform         = d["platform"],
            analyzed_at      = datetime.fromisoformat(d["analyzed_at"]),
            clips            = [Clip.from_dict(c) for c in d.get("clips", [])],
        )
