"""
ai/ai.py

Single responsibility: take a Transcript, talk to Gemini, return an Analysis.

Public API:
  analyze_transcript(transcript, prompt_type) → Analysis

Internal pipeline:
  chunk_transcript  → list of text chunks
  ask_gemini        → AIResponse per chunk
  parse_response    → list[Clip] from one AIResponse
  merge_results     → deduplicate clips across chunks
  score_results     → re-rank by score, assign final rank numbers
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional

import config
from models import Analysis, AIResponse, Clip, Timestamp, Transcript
from ai.prompts import get_prompt


# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_transcript(transcript: Transcript) -> list[str]:
    """
    Split transcript.lines into overlapping time-window chunks.

    Each chunk covers CHUNK_MINUTES of content.
    Consecutive chunks share CHUNK_OVERLAP_SEC of lines at the boundary
    so a moment that spans a chunk boundary isn't missed.

    Returns a list of plain-text strings, each ready to paste into a prompt.
    If lines is empty but content exists, falls back to a single text chunk.
    """
    if not transcript.lines:
        # No structured lines — send the whole content as one chunk
        return [transcript.content] if transcript.content.strip() else []

    chunk_seconds  = config.CHUNK_MINUTES * 60
    overlap_seconds = config.CHUNK_OVERLAP_SEC

    chunks: list[str] = []
    chunk_start_sec = 0.0

    while True:
        chunk_end_sec = chunk_start_sec + chunk_seconds

        # Collect lines whose timestamp falls in [chunk_start, chunk_end)
        chunk_lines = [
            f"[{ts}] {text}"
            for ts, text in transcript.lines
            if _ts_to_sec(ts) >= chunk_start_sec
            and _ts_to_sec(ts) <  chunk_end_sec
        ]

        if not chunk_lines:
            break

        chunks.append("\n".join(chunk_lines))

        # Check if we've covered everything
        last_ts_sec = _ts_to_sec(transcript.lines[-1][0])
        if chunk_end_sec > last_ts_sec:
            break

        # Next chunk starts CHUNK_OVERLAP_SEC before this one ended
        chunk_start_sec = chunk_end_sec - overlap_seconds

    return chunks if chunks else [transcript.content]


def _ts_to_sec(ts: str) -> float:
    """Convert HH:MM:SS to seconds. Returns 0.0 on malformed input."""
    try:
        parts = ts.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(ts)
    except (ValueError, IndexError):
        return 0.0


# ─── Gemini API call ──────────────────────────────────────────────────────────

def ask_gemini(prompt: str, chunk_index: int = 0) -> AIResponse:
    """
    Send one prompt to the Gemini API and return an AIResponse.

    Uses urllib (stdlib only — no extra dependencies).
    Returns AIResponse with error set if anything goes wrong.
    """
    if not config.GEMINI_API_KEY:
        return AIResponse(
            chunk_index = chunk_index,
            error_kind  = "authentication",
            error       = "GEMINI_API_KEY is not set. "
                          "Export it with: export GEMINI_API_KEY=your_key_here",
        )

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{config.GEMINI_MODEL}:generateContent"
        f"?key={config.GEMINI_API_KEY}"
    )

    payload = json.dumps({
        "contents": [
            {"parts": [{"text": prompt}]}
        ],
        "generationConfig": {
            "temperature":     0.3,   # low = more consistent JSON output
            "topP":            0.9,
            "maxOutputTokens": 4096,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data    = payload,
        headers = {"Content-Type": "application/json"},
        method  = "POST",
    )

    if config.DEBUG:
        print(f"🐛 Sending chunk {chunk_index} to Gemini ({len(prompt)} chars)...")

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))

    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            error_kind = "quota"
            error_msg = "Gemini quota or rate limit exceeded (HTTP 429)."
        elif exc.code in (401, 403):
            error_kind = "authentication"
            error_msg = f"Gemini authentication failed (HTTP {exc.code})."
        elif 500 <= exc.code <= 599:
            error_kind = "provider"
            error_msg = f"Gemini provider error (HTTP {exc.code})."
        else:
            error_kind = "http"
            error_msg = f"Gemini HTTP error (HTTP {exc.code})."
        if config.DEBUG:
            print(f"🐛 Gemini HTTP error: {error_msg}")
        return AIResponse(chunk_index=chunk_index, error=error_msg,
                          error_kind=error_kind, http_status=exc.code)

    except urllib.error.URLError as exc:
        return AIResponse(
            chunk_index = chunk_index,
            error_kind  = "network",
            error       = f"Network error: {exc.reason}",
        )

    except TimeoutError:
        return AIResponse(
            chunk_index = chunk_index,
            error_kind  = "provider",
            error       = "Request timed out after 60 s.",
        )

    except Exception as exc:
        return AIResponse(
            chunk_index = chunk_index,
            error_kind  = "provider",
            error       = f"Unexpected error: {exc}",
        )

    # Extract the text content from Gemini's response envelope
    try:
        raw_text = body["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raw_text = ""
        if config.DEBUG:
            print(f"🐛 Unexpected Gemini response shape: {body}")

    return AIResponse(
        chunk_index = chunk_index,
        raw_json    = raw_text,
    )


# ─── Response Parsing ─────────────────────────────────────────────────────────

def ask_openrouter(prompt: str, chunk_index: int = 0) -> AIResponse:
    """Send one prompt to the configured OpenRouter model."""
    if not config.OPENROUTER_API_KEY:
        return AIResponse(chunk_index=chunk_index, error_kind="authentication",
                          error="OPENROUTER_API_KEY is not set.")
    payload = json.dumps({
        "model": config.OPENROUTER_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4096,
        "reasoning": {"effort": "none", "exclude": True},
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions", data=payload,
        headers={"Authorization": "Bearer " + config.OPENROUTER_API_KEY,
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            kind, message = "quota", "OpenRouter quota or rate limit exceeded (HTTP 429)."
        elif exc.code in (401, 403):
            kind, message = "authentication", f"OpenRouter authentication failed (HTTP {exc.code})."
        elif 500 <= exc.code <= 599:
            kind, message = "provider", f"OpenRouter provider error (HTTP {exc.code})."
        else:
            kind, message = "http", f"OpenRouter HTTP error (HTTP {exc.code}): {body_text[:200]}"
        return AIResponse(chunk_index=chunk_index, error_kind=kind,
                          error=message, http_status=exc.code)
    except urllib.error.URLError as exc:
        return AIResponse(chunk_index=chunk_index, error_kind="network",
                          error=f"OpenRouter network error: {exc.reason}")
    except TimeoutError:
        return AIResponse(chunk_index=chunk_index, error_kind="provider",
                          error="OpenRouter request timed out after 90 s.")
    except Exception as exc:
        return AIResponse(chunk_index=chunk_index, error_kind="provider",
                          error=f"Unexpected OpenRouter error: {exc}")
    try:
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content
                               if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise ValueError("OpenRouter response content was empty")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        return AIResponse(chunk_index=chunk_index, error_kind="provider",
                          error=f"OpenRouter response did not contain usable message content: {exc}")
    return AIResponse(chunk_index=chunk_index, raw_json=content)


def ask_ai(prompt: str, chunk_index: int = 0) -> AIResponse:
    """Dispatch one prompt to the configured AI provider."""
    if config.AI_PROVIDER == "gemini":
        return ask_gemini(prompt, chunk_index)
    if config.AI_PROVIDER == "openrouter":
        return ask_openrouter(prompt, chunk_index)
    return AIResponse(chunk_index=chunk_index, error_kind="provider",
                      error=f"Unsupported AI_PROVIDER: {config.AI_PROVIDER}")


def parse_response(response: AIResponse) -> list[Clip]:
    """
    Parse Gemini's raw JSON string into a list of Clip objects.

    Handles common Gemini quirks:
      - wrapping the JSON in ```json ... ``` code fences
      - trailing commas
      - score returned as string instead of float
      - missing rank field

    Sets response.clips and response.error in place.
    Returns the parsed clips (may be empty on failure).
    """
    raw = response.raw_json.strip()

    if not raw:
        response.error_kind = "parse"
        response.error = "Empty response from Gemini."
        return []

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$",          "", raw)
    raw = raw.strip()

    # Remove trailing commas before } or ] (common Gemini mistake)
    raw = re.sub(r",\s*([}\]])", r"\1", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        response.error_kind = "parse"
        response.error = f"JSON parse error: {exc}. Raw: {raw[:200]}"
        if config.DEBUG:
            print(f"🐛 {response.error}")
        return []

    raw_clips = data.get("clips", [])
    if not isinstance(raw_clips, list):
        response.error_kind = "parse"
        response.error = "Response JSON did not contain a 'clips' list."
        return []

    clips: list[Clip] = []
    for i, item in enumerate(raw_clips):
        try:
            clip = Clip(
                rank   = int(item.get("rank",  i + 1)),
                start  = Timestamp.from_string(str(item["start"])),
                end    = Timestamp.from_string(str(item["end"])),
                title  = str(item.get("title",  "Untitled")),
                reason = str(item.get("reason", "")),
                score  = float(item.get("score", 5.0)),
            )
            # Basic sanity: clip must be at least 5 seconds
            if clip.end.to_seconds() - clip.start.to_seconds() >= 5:
                clips.append(clip)
            elif config.DEBUG:
                print(f"🐛 Skipped clip under 5 s: {clip.start} → {clip.end}")

        except (KeyError, ValueError, TypeError) as exc:
            if config.DEBUG:
                print(f"🐛 Skipped malformed clip #{i}: {exc}  item={item}")
            continue

    response.clips = clips
    return clips


# ─── Merging ──────────────────────────────────────────────────────────────────

def merge_results(responses: list[AIResponse]) -> list[Clip]:
    """
    Combine clips from all chunk responses and remove near-duplicates.

    Two clips are considered duplicates if their start times are within
    30 seconds of each other. The higher-scored clip wins.
    """
    all_clips: list[Clip] = []
    for r in responses:
        all_clips.extend(r.clips)

    if not all_clips:
        return []

    # Sort by score descending so that when we deduplicate, the better
    # clip is always encountered first and the weaker one is discarded.
    all_clips.sort(key=lambda c: c.score, reverse=True)

    merged: list[Clip] = []
    for candidate in all_clips:
        candidate_sec = candidate.start.to_seconds()
        is_duplicate  = any(
            abs(candidate_sec - kept.start.to_seconds()) < 30
            for kept in merged
        )
        if not is_duplicate:
            merged.append(candidate)

    return merged


# ─── Scoring / Re-ranking ─────────────────────────────────────────────────────

def score_results(clips: list[Clip], top_n: int) -> list[Clip]:
    """
    Sort merged clips by score, take the top_n, and assign clean rank numbers.

    Returns a new list — does not mutate the input.
    """
    sorted_clips = sorted(clips, key=lambda c: c.score, reverse=True)[:top_n]

    return [
        Clip(
            rank   = i + 1,
            start  = c.start,
            end    = c.end,
            title  = c.title,
            reason = c.reason,
            score  = c.score,
        )
        for i, c in enumerate(sorted_clips)
    ]


# ─── Public Entry Point ───────────────────────────────────────────────────────

def analyze_transcript(
    transcript: Transcript,
    prompt_type: str = "viral",
) -> Analysis:
    """
    Full pipeline: chunk → ask Gemini → parse → merge → score → Analysis.

    Always returns an Analysis object.
    If Gemini fails entirely, Analysis.clips will be empty and the caller
    (clipper.py) should show an appropriate message.
    """
    chunks       = chunk_transcript(transcript)
    total_chunks = len(chunks)

    if not chunks:
        print("⚠️  Transcript is empty — nothing to analyze.")
        return Analysis(
            analysis_version = config.ANALYSIS_VERSION,
            ai_model         = config.AI_MODEL,
            video_id         = transcript.video_id,
            platform         = transcript.platform,
        )

    print(f"\n🤖 Analyzing transcript in {total_chunks} chunk(s) [{prompt_type}]...\n")

    responses: list[AIResponse] = []

    for i, chunk in enumerate(chunks):
        print(f"   Chunk {i + 1}/{total_chunks}  ({len(chunk.splitlines())} lines)...")

        prompt   = get_prompt(prompt_type, chunk, chunk_index=i, total_chunks=total_chunks)
        response = ask_ai(prompt, chunk_index=i)

        if response.error:
            print(f"   ⚠️  Chunk {i + 1} error: {response.error}")
        else:
            clips = parse_response(response)
            print(f"   ✅  Chunk {i + 1}: {len(clips)} clip(s) found")

        responses.append(response)

        # Polite rate-limiting between chunks
        if i < total_chunks - 1:
            time.sleep(1)

    # Merge, deduplicate, rank
    all_clips    = merge_results(responses)
    final_clips  = score_results(all_clips, top_n=config.TOP_CLIPS_COUNT)

    print(f"\n🏆 {len(final_clips)} clip(s) ready after merge + scoring.\n")

    return Analysis(
        analysis_version = config.ANALYSIS_VERSION,
        ai_model         = config.AI_MODEL,
        video_id         = transcript.video_id,
        platform         = transcript.platform,
        analyzed_at      = datetime.now(),
        clips            = final_clips,
        chunk_responses  = responses,
    )
