"""
webapp.py — ClipperOS Flask frontend v1.3

New in this version:
  - Audio-only download (/api/download/audio)
  - Transcript-only download (/api/transcript)
  - Better error messages (yt-dlp exit code decoded)
  - Download history with parsed metadata (/api/history)
  - AI clip cards already have download buttons (handled in JS)
"""

import os
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from flask import Flask, jsonify, render_template, request

CLIPPER_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CLIPPER_ROOT)

from config import APP_NAME, APP_VERSION, HISTORY_FILE, DEFAULT_QUALITY
from downloader import download_full, download_clip, _run_with_retry
from utils import detect_platform, clean_filename, ensure_platform_folder

try:
    from transcript.transcript import (
        download_transcript, clean_transcript,
        save_transcript, load_transcript,
        transcript_exists, _extract_video_id,
    )
    from cache.cache import load_analysis, save_analysis, is_stale
    from ai.ai import analyze_transcript
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

app = Flask(__name__)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()


# ─── Error decoder ────────────────────────────────────────────────────────────

def decode_ytdlp_error(returncode, stderr=""):
    """Turn a yt-dlp exit code + stderr into a human-readable message."""
    stderr = stderr or ""
    if "Sign in to confirm" in stderr or "bot" in stderr.lower():
        return "YouTube blocked this request (bot detection). Try again in a few minutes or use a different URL."
    if "Private video" in stderr:
        return "This video is private and can't be downloaded."
    if "Video unavailable" in stderr:
        return "Video unavailable — it may have been deleted or region-locked."
    if "Requested format is not available" in stderr:
        return "That quality isn't available for this video. Try 720p instead."
    if "ffmpeg" in stderr.lower():
        return "ffmpeg is not installed. Run: pkg install ffmpeg"
    if returncode == 1:
        return "yt-dlp couldn't download this video. Check the URL is correct and the video is public."
    if returncode == 2:
        return "Bad options passed to yt-dlp. This is a ClipperOS bug — please report it."
    return f"Download failed (yt-dlp exit code {returncode}). Try a different quality or URL."


# ─── Job helpers ──────────────────────────────────────────────────────────────

def new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id":         job_id,
            "type":       job_type,
            "status":     "running",
            "message":    "Starting...",
            "progress":   0,
            "result":     None,
            "error":      None,
            "created_at": datetime.now().strftime("%H:%M:%S"),
        }
    return job_id


def update_job(job_id: str, **kwargs):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)


def run_ytdlp_capture(command: list) -> tuple[int, str]:
    """Run yt-dlp, capture stderr for error decoding. Returns (returncode, stderr)."""
    try:
        result = subprocess.run(command, capture_output=True, text=True)
        return result.returncode, result.stderr
    except FileNotFoundError:
        return -1, "yt-dlp not found"
    except Exception as e:
        return -1, str(e)


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html",
                           app_name=APP_NAME,
                           app_version=APP_VERSION,
                           ai_available=AI_AVAILABLE)


@app.route("/api/detect", methods=["POST"])
def api_detect():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"platform": "unknown"})
    return jsonify({"platform": detect_platform(url)})


# ── Video clip ────────────────────────────────────────────────────────────────

@app.route("/api/download/clip", methods=["POST"])
def api_download_clip():
    data     = request.json or {}
    url      = data.get("url", "").strip()
    start    = data.get("start", "").strip()
    end      = data.get("end", "").strip()
    filename = clean_filename(data.get("filename", "clip"))
    quality  = data.get("quality", DEFAULT_QUALITY)

    if not url:   return jsonify({"error": "Paste a video URL first."}), 400
    if not start: return jsonify({"error": "Enter a start time (HH:MM:SS)."}), 400
    if not end:   return jsonify({"error": "Enter an end time (HH:MM:SS)."}), 400

    # Basic timestamp format check
    ts_re = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
    if not ts_re.match(start): return jsonify({"error": f"Start time '{start}' isn't valid. Use HH:MM:SS format."}), 400
    if not ts_re.match(end):   return jsonify({"error": f"End time '{end}' isn't valid. Use HH:MM:SS format."}), 400

    job_id = new_job("clip")

    def run():
        update_job(job_id, message=f"Clipping {start} → {end}...", progress=10)
        result = download_clip(url, start, end, filename, quality)
        if result and result.returncode == 0:
            update_job(job_id, status="done", progress=100,
                       message=f"Saved as {filename}",
                       result={"filename": filename, "quality": quality})
        else:
            code = result.returncode if result else -1
            update_job(job_id, status="error", error=decode_ytdlp_error(code))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Full video ────────────────────────────────────────────────────────────────

@app.route("/api/download/full", methods=["POST"])
def api_download_full():
    data     = request.json or {}
    url      = data.get("url", "").strip()
    filename = clean_filename(data.get("filename", "video"))
    quality  = data.get("quality", DEFAULT_QUALITY)

    if not url: return jsonify({"error": "Paste a video URL first."}), 400

    job_id = new_job("full")

    def run():
        update_job(job_id, message="Downloading full video...", progress=10)
        result = download_full(url, filename, quality)
        if result and result.returncode == 0:
            update_job(job_id, status="done", progress=100,
                       message=f"Saved as {filename}",
                       result={"filename": filename, "quality": quality})
        else:
            code = result.returncode if result else -1
            update_job(job_id, status="error", error=decode_ytdlp_error(code))

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Audio only ────────────────────────────────────────────────────────────────

@app.route("/api/download/audio", methods=["POST"])
def api_download_audio():
    data     = request.json or {}
    url      = data.get("url", "").strip()
    filename = clean_filename(data.get("filename", "audio"))
    fmt      = data.get("format", "mp3")   # mp3 | m4a | wav | opus

    if not url: return jsonify({"error": "Paste a video URL first."}), 400
    if fmt not in ("mp3", "m4a", "wav", "opus"):
        return jsonify({"error": "Unsupported audio format. Choose mp3, m4a, wav, or opus."}), 400

    job_id   = new_job("audio")
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)

    def run():
        update_job(job_id, message=f"Extracting audio as {fmt.upper()}...", progress=10)

        command = [
            "yt-dlp",
            "-f", "bestaudio",
            "--extract-audio",
            "--audio-format", fmt,
            "--audio-quality", "0",
            "-P", folder,
            "-o", f"{filename}.%(ext)s",
            "--newline",
            url,
        ]

        returncode, stderr = run_ytdlp_capture(command)
        if returncode == 0:
            update_job(job_id, status="done", progress=100,
                       message=f"Saved as {filename}.{fmt}",
                       result={"filename": f"{filename}.{fmt}", "format": fmt, "folder": folder})
        else:
            if returncode == -1 and "yt-dlp not found" in stderr:
                msg = "yt-dlp is not installed. Run: pip install yt-dlp"
            elif "ffmpeg" in stderr.lower():
                msg = "ffmpeg is required for audio extraction. Run: pkg install ffmpeg"
            else:
                msg = decode_ytdlp_error(returncode, stderr)
            update_job(job_id, status="error", error=msg)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Transcript only ───────────────────────────────────────────────────────────

@app.route("/api/transcript", methods=["POST"])
def api_transcript():
    if not AI_AVAILABLE:
        return jsonify({"error": "Transcript module not available. Check your ClipperOS installation."}), 503

    data = request.json or {}
    url  = data.get("url", "").strip()

    if not url: return jsonify({"error": "Paste a video URL first."}), 400

    job_id = new_job("transcript")

    def run():
        try:
            platform = detect_platform(url)
            video_id = _extract_video_id(url)

            if transcript_exists(video_id, platform):
                transcript = load_transcript(video_id, platform)
                update_job(job_id, status="done", progress=100,
                           message=f"Loaded saved transcript ({transcript.word_count()} words)",
                           result={
                               "video_id":   video_id,
                               "platform":   platform,
                               "word_count": transcript.word_count(),
                               "file_path":  transcript.file_path,
                               "title":      transcript.title,
                               "preview":    transcript.content[:600] + ("..." if len(transcript.content) > 600 else ""),
                               "cached":     True,
                           })
                return

            update_job(job_id, message="Downloading transcript...", progress=20)
            transcript = download_transcript(url)

            if transcript is None:
                update_job(job_id, status="error",
                           error=(
                               "No captions found for this video. "
                               "ClipperOS can only download transcripts from videos that have "
                               "captions enabled. Try a different video, or check if captions "
                               "are available on YouTube by clicking the CC button."
                           ))
                return

            update_job(job_id, message="Processing transcript...", progress=70)
            transcript = clean_transcript(transcript)
            save_transcript(transcript)

            update_job(job_id, status="done", progress=100,
                       message=f"Transcript saved ({transcript.word_count()} words)",
                       result={
                           "video_id":   video_id,
                           "platform":   platform,
                           "word_count": transcript.word_count(),
                           "file_path":  transcript.file_path,
                           "title":      transcript.title,
                           "preview":    transcript.content[:600] + ("..." if len(transcript.content) > 600 else ""),
                           "cached":     False,
                       })

        except Exception as exc:
            update_job(job_id, status="error",
                       error=f"Unexpected error: {str(exc)}. Try restarting ClipperOS.")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── AI analyze ────────────────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if not AI_AVAILABLE:
        return jsonify({"error": "AI module unavailable. Make sure GEMINI_API_KEY is set in config.py and restart."}), 503

    data        = request.json or {}
    url         = data.get("url", "").strip()
    prompt_type = data.get("prompt_type", "viral")

    if not url: return jsonify({"error": "Paste a video URL first."}), 400

    job_id = new_job("ai")

    def run():
        try:
            platform = detect_platform(url)
            video_id = _extract_video_id(url)

            if not is_stale(video_id, platform):
                update_job(job_id, message="Loading cached analysis...", progress=30)
                analysis = load_analysis(video_id, platform)
                if analysis and analysis.clips:
                    clips = [c.to_dict() for c in analysis.top()]
                    update_job(job_id, status="done", progress=100,
                               message=f"Found {len(clips)} clips (cached)",
                               result={"clips": clips, "cached": True,
                                       "video_id": video_id, "url": url})
                    return

            update_job(job_id, message="Downloading transcript...", progress=15)
            transcript = None

            if transcript_exists(video_id, platform):
                transcript = load_transcript(video_id, platform)
                update_job(job_id, message="Loaded saved transcript.", progress=30)
            else:
                transcript = download_transcript(url)
                if transcript is None:
                    update_job(job_id, status="error",
                               error=(
                                   "No captions found for this video. "
                                   "ClipperOS uses captions to find clips. "
                                   "Try a video with CC/subtitles enabled."
                               ))
                    return
                transcript = clean_transcript(transcript)
                save_transcript(transcript)
                update_job(job_id, message=f"Transcript ready ({transcript.word_count()} words).", progress=35)

            update_job(job_id, message=f"Analyzing with Gemini [{prompt_type}]...", progress=40)
            analysis = analyze_transcript(transcript, prompt_type=prompt_type)

            if not analysis.clips:
                update_job(job_id, status="error",
                           error=(
                               "Gemini didn't find any clips in this transcript. "
                               "Try a different clip style (funny, dramatic, educational) "
                               "or use a longer video with more content."
                           ))
                return

            save_analysis(analysis)
            clips = [c.to_dict() for c in analysis.top()]
            update_job(job_id, status="done", progress=100,
                       message=f"Found {len(clips)} clips",
                       result={"clips": clips, "cached": False,
                               "video_id": video_id, "url": url})

        except Exception as exc:
            update_job(job_id, status="error",
                       error=f"Analysis failed: {str(exc)}. Check your Gemini API key and internet connection.")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Job status & list ─────────────────────────────────────────────────────────

@app.route("/api/job/<job_id>")
def api_job_status(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "Job not found. It may have been cleared."}), 404
    return jsonify(job)


@app.route("/api/jobs")
def api_jobs():
    with JOBS_LOCK:
        jobs = list(JOBS.values())
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jsonify(jobs[:20])


# ── History ───────────────────────────────────────────────────────────────────

@app.route("/api/history")
def api_history():
    if not os.path.exists(HISTORY_FILE):
        return jsonify([])
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            lines = [l.rstrip() for l in f.readlines() if l.strip()]

        parsed = []
        for line in reversed(lines[-50:]):
            # Format: [2026-07-08 14:22:01] CLIP | YOUTUBE   | filename [start → end] | url
            m = re.match(
                r"\[(.+?)\]\s+(\w+)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(.+)$",
                line
            )
            if m:
                parsed.append({
                    "time":     m.group(1),
                    "kind":     m.group(2),
                    "platform": m.group(3),
                    "name":     m.group(4).strip(),
                    "url":      m.group(5).strip(),
                    "raw":      line,
                })
            else:
                parsed.append({"raw": line, "time": "", "kind": "", "platform": "", "name": line, "url": ""})

        return jsonify(parsed)
    except OSError:
        return jsonify([])


if __name__ == "__main__":
    print(f"ClipperOS Web UI running at http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
