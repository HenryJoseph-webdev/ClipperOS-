import os
import sys

from downloader import download_full, download_clip, list_formats
from utils import clean_filename, detect_platform, ensure_platform_folder
from config import APP_NAME, APP_VERSION, HISTORY_FILE, DEFAULT_QUALITY
from transcript.transcript import (
    download_transcript, clean_transcript,
    save_transcript, load_transcript,
    delete_transcript, transcript_exists,
)
CACHE_AVAILABLE = False
AI_AVAILABLE = False

try:
    from cache.cache import (
        load_analysis, save_analysis,
        is_stale, delete_analysis,
    )
    CACHE_AVAILABLE = True
except ImportError:
    pass

try:
    from ai.ai import analyze_transcript
    from ai.prompts import PROMPT_TYPES, DEFAULT_PROMPT_TYPE
    AI_AVAILABLE = CACHE_AVAILABLE
except ImportError:
    PROMPT_TYPES = {}
    DEFAULT_PROMPT_TYPE = "viral"


# ─── Banner ───────────────────────────────────────────────────────────────────

def print_banner():
    os.system("clear")
    print("=" * 48)
    print(f"🚀  {APP_NAME} v{APP_VERSION}")
    print("=" * 48)
    print("  1. 🎬  Download Clip (manual timestamps)")
    print("  2. 📥  Download Full Video")
    print("  3. 📋  List Available Formats")
    print("  4. 🤖  AI Clip Finder")
    print("  5. 📄  Manage Transcripts")
    print("  6. 📝  View Download History")
    print("  7. ❌  Exit")
    print("=" * 48)


# ─── Shared Input Helpers ─────────────────────────────────────────────────────

def get_url() -> str:
    url      = input("\n📹 Video / Stream URL: ").strip()
    platform = detect_platform(url)
    folder   = ensure_platform_folder(platform)
    print(f"   🏷️  Platform : {platform.upper()}")
    print(f"   📁 Saving to: {folder}")
    return url


def get_filename(prompt: str = "📝 Output Filename: ") -> str:
    raw  = input(prompt).strip()
    name = clean_filename(raw)
    if name != raw:
        print(f"   ✏️  Cleaned  → {name}")
    return name


def pick_quality() -> str:
    print(f"\n🎞️  Select Quality  (default: {DEFAULT_QUALITY}):")
    print("  1. 720p")
    print("  2. 1080p")
    print("  3. 1440p")
    q = input("Choice [1/2/3] or Enter for default: ").strip()
    return {"1": "720p", "2": "1080p", "3": "1440p"}.get(q, DEFAULT_QUALITY)


def pick_prompt_type() -> str:
    types = list(PROMPT_TYPES.keys())
    print("\n🎯  What kind of clips are you looking for?")
    for i, t in enumerate(types, 1):
        print(f"  {i}. {t.capitalize()}")
    choice = input(f"Choice [1-{len(types)}] or Enter for default ({DEFAULT_PROMPT_TYPE}): ").strip()
    try:
        return types[int(choice) - 1]
    except (ValueError, IndexError):
        return DEFAULT_PROMPT_TYPE


def show_result(result, url: str, filename: str):
    print()
    if result is None:
        print("❌ Download could not start — see error above.")
        return
    if result.returncode == 0:
        platform = detect_platform(url)
        folder   = ensure_platform_folder(platform)
        print("✅ Done!")
        print(f"📁 Saved to : {folder}/{filename}.*")
        print(f"📝 Logged to: {HISTORY_FILE}")
    else:
        print(f"❌ Failed after retries. (exit code: {result.returncode})")
        print("   Tip: Choose option 3 to check available formats for this URL.")


# ─── History ──────────────────────────────────────────────────────────────────

def view_history():
    if not os.path.exists(HISTORY_FILE):
        print("\n📭 No download history yet.\n")
        return
    print("\n📝 Download History  (last 30 entries)\n")
    print("-" * 80)
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in (lines[-30:] if lines else ["  (empty)"]):
            print(" ", line.rstrip())
    except OSError as e:
        print(f"❌ Could not read history: {e}")
    print("-" * 80)
    print()


# ─── AI Clip Finder ───────────────────────────────────────────────────────────

def show_clips(clips) -> None:
    """Print the ranked clip list."""
    print()
    print("=" * 60)
    print(f"  🏆  Top {len(clips)} Clips")
    print("=" * 60)
    for c in clips:
        print(f"\n  #{c.rank}  {c.title}")
        print(f"       ⏱️  {c.start} → {c.end}  ({c.duration_str()})")
        print(f"       ⭐ Score: {c.score}/10")
        print(f"       💡 {c.reason}")
    print()


def ai_clip_finder():
    if not AI_AVAILABLE:
        print("\nAI clip finder is unavailable until its cache implementation is restored.\n")
        input("Press Enter to return to menu...")
        return

    url      = get_url()
    platform = detect_platform(url)

    # Extract video ID the same way transcript.py does
    from transcript.transcript import _extract_video_id
    video_id = _extract_video_id(url)

    # ── Check cache first ────────────────────────────────────────────────────
    if not is_stale(video_id, platform):
        print(f"\n💾 Found cached analysis for {video_id}.")
        use_cache = input("   Use it? [Y/n]: ").strip().lower()
        if use_cache != "n":
            analysis = load_analysis(video_id, platform)
            if analysis and analysis.clips:
                show_clips(analysis.top())
                _offer_clip_download(analysis.clips, url)
                return

    # ── Get transcript ───────────────────────────────────────────────────────
    transcript = None

    if transcript_exists(video_id, platform):
        print(f"\n📄 Found saved transcript for {video_id}.")
        use_saved = input("   Use it? [Y/n]: ").strip().lower()
        if use_saved != "n":
            transcript = load_transcript(video_id, platform)

    if transcript is None:
        print("\n📄 Downloading transcript...")
        transcript = download_transcript(url)

        if transcript is None:
            print("\n❌ No transcript available for this video.")
            print("   ClipperOS can only analyze videos that have captions.")
            input("\n↩️  Press Enter to return to menu...")
            return

        transcript = clean_transcript(transcript)
        save_transcript(transcript)

    if transcript.is_empty():
        print("❌ Transcript is empty — nothing to analyze.")
        input("\n↩️  Press Enter to return to menu...")
        return

    print(f"\n📊 Transcript ready  ({transcript.word_count()} words)")

    # ── Pick prompt type ─────────────────────────────────────────────────────
    prompt_type = pick_prompt_type()

    # ── Run AI analysis ──────────────────────────────────────────────────────
    analysis = analyze_transcript(transcript, prompt_type=prompt_type)

    if not analysis.clips:
        print("\n❌ AI returned no clips. Try a different prompt type or video.")
        input("\n↩️  Press Enter to return to menu...")
        return

    # ── Cache result ─────────────────────────────────────────────────────────
    save_analysis(analysis)

    # ── Show results ─────────────────────────────────────────────────────────
    show_clips(analysis.top())
    _offer_clip_download(analysis.clips, url)


def _offer_clip_download(clips, url: str):
    """Ask the user to pick a clip number and download it."""
    print("-" * 60)
    choice = input(
        f"Download a clip? Enter number [1-{len(clips)}] or Enter to skip: "
    ).strip()

    if not choice:
        return

    try:
        index = int(choice) - 1
        clip  = sorted(clips, key=lambda c: c.rank)[index]
    except (ValueError, IndexError):
        print("❌ Invalid choice.")
        return

    print(f"\n🎬 Selected: {clip.title}")
    print(f"   {clip.start} → {clip.end}  ({clip.duration_str()})")

    filename = get_filename("📝 Output Filename: ")
    quality  = pick_quality()

    print(f"\n🚀 Downloading clip...\n")
    result = download_clip(url, clip.start.raw, clip.end.raw, filename, quality)
    show_result(result, url, filename)
    input("\n↩️  Press Enter to return to menu...")


# ─── Transcript Manager ───────────────────────────────────────────────────────

def transcript_manager():
    os.system("clear")
    print("=" * 48)
    print("  📄  Transcript Manager")
    print("=" * 48)
    print("  1. Download transcript for a URL")
    print("  2. Delete a transcript")
    print("  3. Back to main menu")
    print("=" * 48)

    choice = input("\nChoice: ").strip()

    if choice == "1":
        url        = get_url()
        platform   = detect_platform(url)
        from transcript.transcript import _extract_video_id
        video_id   = _extract_video_id(url)

        if transcript_exists(video_id, platform):
            print(f"\n📄 Transcript already exists for {video_id}.")
            overwrite = input("   Re-download? [y/N]: ").strip().lower()
            if overwrite != "y":
                return

        transcript = download_transcript(url)
        if transcript:
            transcript = clean_transcript(transcript)
            save_transcript(transcript)
            print(f"\n✅ Transcript saved  ({transcript.word_count()} words)")
        input("\n↩️  Press Enter to continue...")

    elif choice == "2":
        url      = get_url()
        platform = detect_platform(url)
        from transcript.transcript import _extract_video_id
        video_id = _extract_video_id(url)
        delete_transcript(video_id, platform)
        if CACHE_AVAILABLE:
            delete_analysis(video_id, platform)
        input("\n↩️  Press Enter to continue...")


# ─── Main Loop ────────────────────────────────────────────────────────────────

def main():
    while True:
        print_banner()
        choice = input("\nChoose an option: ").strip()

        # ── 1. Download Clip ──────────────────────────────────────────────────
        if choice == "1":
            url      = get_url()
            start    = input("⏱️  Start Time (HH:MM:SS): ").strip()
            end      = input("⏱️  End Time   (HH:MM:SS): ").strip()
            filename = get_filename()
            quality  = pick_quality()
            print(f"\n🚀 Clipping {start} → {end} at {quality}...\n")
            result = download_clip(url, start, end, filename, quality)
            show_result(result, url, filename)
            input("\n↩️  Press Enter to return to menu...")

        # ── 2. Full Video ─────────────────────────────────────────────────────
        elif choice == "2":
            url      = get_url()
            filename = get_filename()
            quality  = pick_quality()
            print(f"\n🚀 Downloading full video at {quality}...\n")
            result = download_full(url, filename, quality)
            show_result(result, url, filename)
            input("\n↩️  Press Enter to return to menu...")

        # ── 3. List Formats ───────────────────────────────────────────────────
        elif choice == "3":
            url = get_url()
            ok  = list_formats(url)
            if not ok:
                print("❌ Could not retrieve formats.")
            input("\n↩️  Press Enter to return to menu...")

        # ── 4. AI Clip Finder ─────────────────────────────────────────────────
        elif choice == "4":
            ai_clip_finder()

        # ── 5. Transcript Manager ─────────────────────────────────────────────
        elif choice == "5":
            transcript_manager()

        # ── 6. History ────────────────────────────────────────────────────────
        elif choice == "6":
            view_history()
            input("↩️  Press Enter to return to menu...")

        # ── 7. Exit ───────────────────────────────────────────────────────────
        elif choice == "7":
            print("\n👋 Bye!\n")
            break

        else:
            print("❌ Invalid option — try 1 to 7.")
            input("\n↩️  Press Enter to return to menu...")


if __name__ == "__main__":
    main()
