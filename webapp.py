"""
webapp.py — ClipperOS Flask frontend v1.4.2

Changes from v1.4.1:
  - api_download_clip:  passes on_progress + on_done callbacks → real progress
  - api_download_full:  same
  - api_download_audio: same
  - job.result now includes output_path (absolute path of created file)
  - POST /api/open-folder  opens the containing folder in the OS file manager
  Everything else is IDENTICAL to v1.4.1.
"""

import os
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from flask import Flask, jsonify, redirect, request, send_file

CLIPPER_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, CLIPPER_ROOT)
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://127.0.0.1:3000").rstrip("/")

from config import (APP_NAME, APP_VERSION, HISTORY_FILE, DEFAULT_QUALITY,
                    BASE_DOWNLOAD_FOLDER, AI_PROVIDER, AI_MODEL,
                    GEMINI_API_KEY, OPENROUTER_API_KEY)
from downloader import download_full, download_clip, _run_with_ydl, _base_opts
from utils import detect_platform, clean_filename, ensure_platform_folder
from job_store import get_job as get_persisted_job, list_jobs as list_persisted_jobs
from job_store import save_job as save_persisted_job

TRANSCRIPT_AVAILABLE = False
AI_AVAILABLE = False

try:
    from transcript.transcript import (
        download_transcript, clean_transcript,
        save_transcript, load_transcript,
        transcript_exists, _extract_video_id,
    )
    TRANSCRIPT_AVAILABLE = True
except ImportError:
    pass

try:
    from cache.cache import load_analysis, save_analysis, is_stale
    from ai.ai import analyze_transcript
    AI_AVAILABLE = TRANSCRIPT_AVAILABLE
except ImportError:
    pass

# ── Auth module ───────────────────────────────────────────────────────────────
AUTH_AVAILABLE     = False
_auth_get_status   = None
_auth_connect      = None
_auth_disconnect   = None
_auth_get_browsers = None
_save_cookies_file = None

try:
    from auth import (
        get_status   as auth_get_status,
        connect      as auth_connect,
        disconnect   as auth_disconnect,
        get_browsers as auth_get_browsers,
    )
    _auth_get_status   = auth_get_status
    _auth_connect      = auth_connect
    _auth_disconnect   = auth_disconnect
    _auth_get_browsers = auth_get_browsers
    AUTH_AVAILABLE = True
except ImportError as _e:
    import warnings
    warnings.warn(f"ClipperOS: auth core unavailable — {_e}. Downloads will work anonymously.")

try:
    from auth.cookies_file import save_cookies_file as _save_cookies_file_fn
    _save_cookies_file = _save_cookies_file_fn
except ImportError:
    _save_cookies_file = None

app = Flask(__name__)

JOBS: dict[str, dict] = {}
JOBS_LOCK = threading.Lock()
_LAST_JOB_PERSIST: dict[str, float] = {}
_JOB_PERSIST_INTERVAL = 2.0


# ─── Error decoder ────────────────────────────────────────────────────────────

def decode_ytdlp_error(returncode: int, stderr: str = "", detail: str = "") -> str:
    combined = f"{stderr} {detail}".lower()
    if "sign in to confirm" in combined or ("bot" in combined and "youtube" in combined):
        return ("YouTube rejected this request or requires verification. "
                "The PO-token provider may be unavailable or YouTube may be "
                "blocking this server IP. Please try again later.")
    if "private video" in combined:
        return "This video is private and can't be downloaded."
    if "video unavailable" in combined:
        return "Video unavailable — it may have been deleted or region-locked."
    if "requested format is not available" in combined:
        return (f"That quality isn't available. Try 720p instead."
                f"{(' (' + detail[:120] + ')') if detail else ''}")
    if ("sign in to confirm" in combined or "not a bot" in combined
            or "requires verification" in combined or "botguard" in combined
            or "po token" in combined):
        return ("YouTube rejected this request or requires verification. "
                "The PO-token provider may be unavailable or YouTube may be "
                "blocking this server IP. Please try again later.")
    if "ffmpeg" in combined and ("not found" in combined or "not install" in combined):
        return "Audio processing is unavailable. Check the media tools installation and restart ClipperOS."
    if returncode == 1 and detail:
        return f"Download failed: {detail[:300]}"
    if returncode == 1:
        return "The video couldn't be downloaded. Check that the URL is correct and the video is public."
    if returncode == 2:
        return "The download options were invalid. Please try again."
    if detail:
        return f"Download failed (exit {returncode}): {detail[:300]}"
    return "Download failed. Try a different quality or URL."


# ─── Job helpers ──────────────────────────────────────────────────────────────

def new_job(job_type: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    now = datetime.now().strftime("%H:%M:%S")
    job = {
        "id":         job_id,
        "type":       job_type,
        "status":     "running",
        "message":    "Starting...",
        "progress":   0,
        "result":     None,
        "error":      None,
        "created_at": now,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
        _persist_job(job, force=True)
    return job_id


def update_job(job_id: str, **kwargs):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(kwargs)
            JOBS[job_id]["updated_at"] = datetime.now().isoformat(timespec="seconds")
            force = (
                kwargs.get("status") in {"queued", "running", "done", "error"}
                or "error" in kwargs
                or "result" in kwargs
            )
            _persist_job(JOBS[job_id], force=force)


def _persist_job(job: dict, force: bool = False) -> bool:
    now = time.monotonic()
    if not force and now - _LAST_JOB_PERSIST.get(job["id"], 0.0) < _JOB_PERSIST_INTERVAL:
        return True
    try:
        save_persisted_job(job)
    except Exception as exc:
        print(f"   ⚠️  Could not persist job {job['id']}: {exc}")
        return False
    _LAST_JOB_PERSIST[job["id"]] = now
    return True


def _get_job(job_id: str):
    with JOBS_LOCK:
        active_job = JOBS.get(job_id)
    if active_job is not None:
        return active_job

    try:
        job = get_persisted_job(job_id)
    except Exception as exc:
        print(f"   ⚠️  Could not read persisted job {job_id}: {exc}")
        job = None
    if job is not None:
        return job
    return None


def _list_jobs():
    try:
        return list_persisted_jobs()
    except Exception as exc:
        print(f"   ⚠️  Could not read persisted jobs: {exc}")
        with JOBS_LOCK:
            jobs = list(JOBS.values())
        jobs.sort(key=lambda job: job["created_at"], reverse=True)
        return jobs[:20]


def run_ytdlp_capture(command: list) -> tuple[int, str]:
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
    return redirect(FRONTEND_URL)


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

    ts_re = re.compile(r"^\d{1,2}:\d{2}:\d{2}$")
    if not ts_re.match(start):
        return jsonify({"error": f"Start time '{start}' isn't valid. Use HH:MM:SS."}), 400
    if not ts_re.match(end):
        return jsonify({"error": f"End time '{end}' isn't valid. Use HH:MM:SS."}), 400

    job_id = new_job("clip")

    def run():
        update_job(job_id, message=f"Clipping {start} → {end}...", progress=5)

        # ── Real progress callbacks ──────────────────────────────────────────
        def on_progress(pct: int, msg: str):
            update_job(job_id, progress=pct, message=msg)

        def on_done(filepath: str):
            update_job(job_id, message="Finalising...", progress=97)

        result = download_clip(url, start, end, filename, quality,
                               on_progress=on_progress, on_done=on_done)

        if result and result.returncode == 0:
            output_path = result.output_path or ""
            update_job(job_id, status="done", progress=100,
                       message=f"Saved — {os.path.basename(output_path) or filename}",
                       result={
                           "filename":    filename,
                           "quality":     quality,
                           "output_path": output_path,
                           "folder":      os.path.dirname(output_path) if output_path else "",
                       })
        else:
            code   = result.returncode if result else -1
            detail = result.stderr if result and result.stderr else ""
            update_job(job_id, status="error",
                       error=decode_ytdlp_error(code, detail=detail), detail=detail)

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
        update_job(job_id, message="Starting download...", progress=5)

        def on_progress(pct: int, msg: str):
            update_job(job_id, progress=pct, message=msg)

        def on_done(filepath: str):
            update_job(job_id, message="Finalising...", progress=97)

        result = download_full(url, filename, quality,
                               on_progress=on_progress, on_done=on_done)

        if result and result.returncode == 0:
            output_path = result.output_path or ""
            update_job(job_id, status="done", progress=100,
                       message=f"Saved — {os.path.basename(output_path) or filename}",
                       result={
                           "filename":    filename,
                           "quality":     quality,
                           "output_path": output_path,
                           "folder":      os.path.dirname(output_path) if output_path else "",
                       })
        else:
            code   = result.returncode if result else -1
            detail = result.stderr if result and result.stderr else ""
            update_job(job_id, status="error",
                       error=decode_ytdlp_error(code, detail=detail), detail=detail)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Audio only ────────────────────────────────────────────────────────────────

@app.route("/api/download/audio", methods=["POST"])
def api_download_audio():
    data     = request.json or {}
    url      = data.get("url", "").strip()
    filename = clean_filename(data.get("filename", "audio"))
    fmt      = data.get("format", "mp3")

    if not url:
        return jsonify({"error": "Paste a video URL first."}), 400
    if fmt not in ("mp3", "m4a", "wav", "opus"):
        return jsonify({"error": "Unsupported audio format. Choose mp3, m4a, wav, or opus."}), 400

    job_id   = new_job("audio")
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)

    def run():
        update_job(job_id, message=f"Extracting {fmt.upper()} audio...", progress=5)

        def on_progress(pct: int, msg: str):
            update_job(job_id, progress=pct, message=msg)

        def on_done(filepath: str):
            update_job(job_id, message="Converting audio...", progress=97)

        from downloader import _make_progress_hook
        opts = {
            **_base_opts(),
            "format":          "bestaudio/best",
            "paths":           {"home": folder},
            "outtmpl":         {"default": f"{filename}.%(ext)s"},
            "postprocessors":  [{
                "key":              "FFmpegExtractAudio",
                "preferredcodec":   fmt,
                "preferredquality": "0",
            }],
            "progress_hooks":      [_make_progress_hook(f"Extracting {fmt.upper()}")],
            "postprocessor_hooks": [],
        }

        result = _run_with_ydl(opts, [url], f"Audio extraction ({fmt})",
                               on_progress=on_progress, on_done=on_done)

        if result and result.returncode == 0:
            output_path = result.output_path or ""
            update_job(job_id, status="done", progress=100,
                       message=f"Saved — {os.path.basename(output_path) or filename + '.' + fmt}",
                       result={
                           "filename":    f"{filename}.{fmt}",
                           "format":      fmt,
                           "folder":      folder,
                           "output_path": output_path,
                       })
        else:
            code   = result.returncode if result else -1
            detail = result.stderr if result and result.stderr else ""
            if "ffmpeg" in detail.lower():
                msg = "Audio extraction is unavailable. Check the media tools installation and restart ClipperOS."
            elif code == -1 and "not installed" in detail:
                msg = "The download service is unavailable. Check the installation and restart ClipperOS."
            else:
                msg = decode_ytdlp_error(code, detail=detail)
            update_job(job_id, status="error", error=msg, detail=detail)

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Open folder ───────────────────────────────────────────────────────────────

@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    """
    Open a folder in the OS file manager.
    If a file path is given, open its containing folder and select the file
    (Windows only via 'explorer /select,path').

    Security: the path must be inside BASE_DOWNLOAD_FOLDER.
    """
    data        = request.json or {}
    raw_path    = data.get("path", "").strip()
    select_file = data.get("select_file", False)   # True → highlight file in Explorer

    if not raw_path:
        return jsonify({"ok": False, "error": "No path provided."}), 400

    abs_path    = os.path.abspath(raw_path)
    base        = os.path.abspath(BASE_DOWNLOAD_FOLDER)

    # Security: reject anything outside the ClipperOS download folder
    if not abs_path.startswith(base):
        return jsonify({"ok": False, "error": "Path is outside the ClipperOS download folder."}), 403

    if not os.path.exists(abs_path):
        return jsonify({"ok": False, "error": "Path does not exist on disk."}), 404

    try:
        import platform as _platform
        system = _platform.system()

        if system == "Windows":
            if select_file and os.path.isfile(abs_path):
                # Open Explorer and highlight the file
                subprocess.Popen(["explorer", "/select,", abs_path])
            else:
                folder = abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)
                subprocess.Popen(["explorer", folder])

        elif system == "Darwin":
            if select_file and os.path.isfile(abs_path):
                subprocess.Popen(["open", "-R", abs_path])
            else:
                folder = abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)
                subprocess.Popen(["open", folder])

        else:
            # Linux — use xdg-open on the folder
            folder = abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)
            subprocess.Popen(["xdg-open", folder])

        return jsonify({"ok": True})

    except Exception as exc:
        return jsonify({"ok": False, "error": "Could not open the download folder."}), 500


# ── Download the finished file ─────────────────────────────────────────────────

@app.route("/api/download/file/<job_id>")
def api_download_file(job_id):
    """
    Stream a completed job's file back through the HTTP response so the
    browser saves it into the *user's own* default Downloads folder.

    This replaces server-side "open folder" — that only ever worked when
    the Flask server and the browser were on the same machine (local dev).
    In production (Render), the server's filesystem is not the tester's
    machine, so this is the only way the file actually reaches them.

    Works for both media jobs (result.output_path) and transcript jobs
    (result.file_path).
    """
    job = _get_job(job_id)

    if not job:
        return jsonify({"error": "Job not found."}), 404
    if job.get("status") != "done":
        return jsonify({"error": "This job hasn't finished yet."}), 409

    result    = job.get("result") or {}
    file_path = result.get("output_path") or result.get("file_path")
    if not file_path:
        return jsonify({"error": "No file is associated with this job."}), 404

    abs_path = os.path.abspath(file_path)
    base     = os.path.abspath(BASE_DOWNLOAD_FOLDER)

    # Security: only ever serve files inside ClipperOS's own download tree
    # (this also covers TRANSCRIPT_BASE, since it's nested under it).
    if not (abs_path == base or abs_path.startswith(base + os.sep)):
        return jsonify({"error": "File is outside the allowed download folder."}), 403

    if not os.path.isfile(abs_path):
        return jsonify({"error": "File no longer exists on the server."}), 404

    return send_file(
        abs_path,
        as_attachment=True,
        download_name=os.path.basename(abs_path),
        conditional=True,
    )


# ── Transcript ────────────────────────────────────────────────────────────────

@app.route("/api/transcript", methods=["POST"])
def api_transcript():
    if not TRANSCRIPT_AVAILABLE:
        return jsonify({"error": "Transcript service is currently unavailable."}), 503
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
                           result={"video_id": video_id, "platform": platform,
                                   "word_count": transcript.word_count(),
                                   "file_path": transcript.file_path, "title": transcript.title,
                                   "preview": transcript.content[:600] + ("..." if len(transcript.content) > 600 else ""),
                                   "cached": True})
                return
            update_job(job_id, message="Downloading transcript...", progress=20)
            transcript = download_transcript(url)
            if transcript is None:
                update_job(job_id, status="error",
                           error="No captions found. Try a video with CC/subtitles enabled.")
                return
            update_job(job_id, message="Processing transcript...", progress=70)
            transcript = clean_transcript(transcript)
            save_transcript(transcript)
            update_job(job_id, status="done", progress=100,
                       message=f"Transcript saved ({transcript.word_count()} words)",
                       result={"video_id": video_id, "platform": platform,
                               "word_count": transcript.word_count(),
                               "file_path": transcript.file_path, "title": transcript.title,
                               "preview": transcript.content[:600] + ("..." if len(transcript.content) > 600 else ""),
                               "cached": False})
        except Exception as exc:
            update_job(job_id, status="error", error="Transcript processing failed. Please try again.")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── AI analyze ────────────────────────────────────────────────────────────────

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    if not AI_AVAILABLE:
        return jsonify({"error": "AI module unavailable. Check the configured AI provider and credentials."}), 503
    data        = request.json or {}
    url         = data.get("url", "").strip()
    # ``category`` is the first-class AI Analytics contract. Keep accepting
    # the older prompt_type name for existing clients.
    prompt_type = str(data.get("category") or data.get("prompt_type") or "interesting").strip().lower()
    if not url: return jsonify({"error": "Paste a video URL first."}), 400
    job_id = new_job("ai")

    def run():
        try:
            platform = detect_platform(url)
            video_id = _extract_video_id(url)
            # Historical cache files predate category-aware analysis. Only
            # reuse them for the legacy viral mode; every Analytics category
            # must receive a fresh category-specific Gemini prompt. The
            # transcript cache below remains shared by all categories.
            if prompt_type == "viral" and not is_stale(video_id, platform):
                update_job(job_id, message="Loading cached analysis...", progress=30)
                analysis = load_analysis(video_id, platform)
                if analysis and analysis.clips:
                    clips = [c.to_dict() for c in analysis.top()]
                    update_job(job_id, status="done", progress=100,
                               message=f"Found {len(clips)} clips (cached)",
                               result={"clips": clips, "cached": True, "category": prompt_type,
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
                               error="No captions found. Try a video with CC/subtitles enabled.")
                    return
                transcript = clean_transcript(transcript)
                save_transcript(transcript)
                update_job(job_id, message=f"Transcript ready ({transcript.word_count()} words).", progress=35)
            update_job(job_id, message=f"Analyzing transcript [{prompt_type}]...", progress=40)
            analysis = analyze_transcript(transcript, prompt_type=prompt_type)
            if not analysis.clips:
                failures = [response for response in analysis.chunk_responses if response.error]
                if failures:
                    priority = {"quota": 0, "authentication": 1, "provider": 2,
                                "network": 3, "http": 4, "parse": 5}
                    failure = sorted(failures, key=lambda item: priority.get(item.error_kind, 99))[0]
                    messages = {
                        "quota": "AI usage is temporarily unavailable. Try again later.",
                        "authentication": "AI analysis is not configured correctly. Check the app credentials.",
                        "provider": "AI analysis is currently unavailable. Try again later.",
                        "network": "Could not reach the AI service. Check the network connection and try again.",
                        "http": "The AI service returned an error. Try again later.",
                        "parse": "The AI service returned a response that could not be processed.",
                    }
                    update_job(job_id, status="error", error=messages.get(failure.error_kind, failure.error),
                               error_kind=failure.error_kind, error_status=failure.http_status)
                    return
                update_job(job_id, status="error",
                           error="No clips were found. Try a different category or a longer captioned video.")
                return
            save_analysis(analysis)
            clips = [c.to_dict() for c in analysis.top()]
            update_job(job_id, status="done", progress=100,
                       message=f"Found {len(clips)} clips",
                       result={"clips": clips, "cached": False, "category": prompt_type,
                               "video_id": video_id, "url": url})
        except Exception as exc:
            update_job(job_id, status="error",
                       error=f"Analysis failed: {exc}. Check the configured AI provider and internet connection.")

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


# ── Job status & list ─────────────────────────────────────────────────────────

@app.route("/api/job/<job_id>")
def api_job_status(job_id):
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)


@app.route("/api/jobs")
def api_jobs():
    return jsonify(_list_jobs())


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
            m = re.match(r"\[(.+?)\]\s+(\w+)\s*\|\s*(\w+)\s*\|\s*(.+?)\s*\|\s*(.+)$", line)
            if m:
                parsed.append({"time": m.group(1), "kind": m.group(2), "platform": m.group(3),
                                "name": m.group(4).strip(), "url": m.group(5).strip(), "raw": line})
            else:
                parsed.append({"raw": line, "time": "", "kind": "", "platform": "", "name": line, "url": ""})
        return jsonify(parsed)
    except OSError:
        return jsonify([])


# ═══════════════════════════════════════════════════
# AUTH ROUTES — unchanged from v1.4.1
# ═══════════════════════════════════════════════════

@app.route("/api/auth/status")
def api_auth_status():
    if not AUTH_AVAILABLE:
        return jsonify({"available": False, "connected": False, "provider": "none",
                        "message": "Authentication is currently unavailable.", "browsers": [],
                        "browser": None, "profile": None, "error": None})
    try:
        status = _auth_get_status()
        raw_browsers = _auth_get_browsers()
        normalised = []
        for b in raw_browsers:
            if isinstance(b, str):
                normalised.append({"id": b, "label": b.capitalize()})
            elif isinstance(b, dict):
                normalised.append({"id":    b.get("id") or b.get("name") or b.get("value", ""),
                                   "label": b.get("label") or b.get("name", "").capitalize()})
        status["browsers"]    = normalised
        status["available"]   = True
        status["api_version"] = 2
        return jsonify(status)
    except Exception as exc:
        return jsonify({"available": True, "connected": False, "provider": "none",
                        "message": "Could not load auth status.", "browsers": [],
                        "browser": None, "profile": None, "error": str(exc)})


@app.route("/api/auth/connect", methods=["POST"])
def api_auth_connect():
    if not AUTH_AVAILABLE:
        return jsonify({"connected": False, "error": "Authentication is currently unavailable."}), 503
    data     = request.json or {}
    provider = data.get("provider", "cookies_file")
    browser  = data.get("browser", "").strip()
    profile  = data.get("profile", "").strip() or None
    if provider == "browser_cookies" and not browser:
        return jsonify({"connected": False, "error": "Select a browser to connect with."}), 400
    try:
        result = _auth_connect(provider, browser=browser, profile=profile) \
                 if provider == "browser_cookies" \
                 else _auth_connect(provider)
        return jsonify(result)
    except Exception as exc:
        return jsonify({"connected": False, "provider": provider,
                        "error": f"Connect failed: {exc}", "detail": str(exc)})


@app.route("/api/auth/cookies", methods=["POST"])
def api_auth_upload_cookies():
    if not AUTH_AVAILABLE:
        return jsonify({"ok": False, "error": "Authentication is currently unavailable."}), 503
    if _save_cookies_file is None:
        return jsonify({"ok": False, "error": "Cookie upload is currently unavailable."}), 503
    upload = request.files.get("cookies")
    if upload is None or not upload.filename:
        return jsonify({"ok": False, "error": "No file uploaded."}), 400
    if not upload.filename.lower().endswith(".txt"):
        return jsonify({"ok": False, "error": "Upload a .txt cookies file."}), 400
    try:
        data = upload.read()
        _save_cookies_file(data)
        result = _auth_connect("cookies_file")
        return jsonify({"ok": result.get("connected", False), **result})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc), "connected": False})
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Upload failed: {exc}", "connected": False})


@app.route("/api/auth/disconnect", methods=["POST"])
def api_auth_disconnect():
    if not AUTH_AVAILABLE:
        return jsonify({"connected": False, "message": "Authentication is currently unavailable."})
    try:
        return jsonify(_auth_disconnect())
    except Exception as exc:
        return jsonify({"connected": False, "error": "Could not disconnect authentication."}), 500


# ─── Entrypoint ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    selected_key = OPENROUTER_API_KEY if AI_PROVIDER == "openrouter" else GEMINI_API_KEY
    print(f"AI runtime: provider={AI_PROVIDER}, model={AI_MODEL}, key_configured={bool(selected_key)}")
    print(f"ClipperOS Web UI running on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
