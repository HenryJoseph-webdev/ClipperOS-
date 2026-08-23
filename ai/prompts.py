"""
ai/prompts.py

All Gemini prompt strings live here and nowhere else.
ai.py imports from this file — it never builds prompt strings itself.

Why a separate file:
  - Prompts grow. Fast.
  - Tweaking a prompt should never mean touching AI logic.
  - Different prompt types (viral, educational, funny) stay organised.
  - Easy to A/B test: swap a prompt, bump ANALYSIS_VERSION, re-run.
"""

from config import TOP_CLIPS_COUNT


# ─── JSON Schema (shown to Gemini in every prompt) ────────────────────────────
#
# Defining the schema once here keeps every prompt consistent.
# If you ever add a field (e.g. "clip_type"), add it here and it
# propagates to all prompts automatically.

_CLIP_SCHEMA = """
{
  "clips": [
    {
      "rank":   1,
      "start":  "HH:MM:SS",
      "end":    "HH:MM:SS",
      "title":  "Short punchy title for the clip",
      "reason": "Why this moment is engaging / viral",
      "score":  9.8
    }
  ]
}
"""

# ─── Shared rules appended to every prompt ────────────────────────────────────
#
# These constraints protect against the most common Gemini failures:
#   - timestamps that don't exist in the transcript
#   - clips shorter than 15 s (not useful) or longer than 3 min (too long)
#   - score inflation (everything 9.5+)
#   - prose mixed into the JSON response

_SHARED_RULES = f"""
Rules:
- Return valid JSON only. No markdown. No code fences. No explanation text.
- Use ONLY timestamps that appear in the transcript. Do not invent timestamps.
- Each clip must be between 15 seconds and 3 minutes long.
- Scores must use the full 1–10 range. Reserve 9+ for truly exceptional moments.
- rank must start at 1 and be unique per clip.
- If fewer than {TOP_CLIPS_COUNT} strong moments exist, return fewer. Do not pad with weak clips.
"""


# ─── Prompts ──────────────────────────────────────────────────────────────────

def viral_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """
    Main prompt. Finds the most shareable, high-engagement moments.
    Used for: general clip finding, Twitch highlights, YouTube moments.
    """
    context = (
        f"(Chunk {chunk_index + 1} of {total_chunks})"
        if total_chunks > 1
        else ""
    )

    return f"""You are an expert short-form content editor who has studied thousands of viral clips.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} most engaging moments — \
moments that would make someone stop scrolling, watch to the end, and share immediately.

Look for:
- Unexpected reactions or outbursts
- Funny misunderstandings or awkward moments
- Impressive or shocking moments
- Genuine emotion (hype, anger, disbelief, laughter)
- Quotable lines that stand alone without context

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


def interesting_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """Find surprising, unusual, fascinating, or highly engaging moments."""
    context = f"(Chunk {chunk_index + 1} of {total_chunks})" if total_chunks > 1 else ""
    return f"""You are an expert content editor finding the most interesting moments in long-form video.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} most surprising, unusual, fascinating, controversial, or highly engaging moments.

Look for unexpected facts, revelations, twists, unusual stories, compelling disagreements, and moments that create curiosity.

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


def funny_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """
    Comedy-focused prompt. Prioritises laughs over raw virality.
    """
    context = (
        f"(Chunk {chunk_index + 1} of {total_chunks})"
        if total_chunks > 1
        else ""
    )

    return f"""You are a comedy editor who specialises in finding hilarious moments in streams and videos.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} funniest moments — \
moments that will make someone laugh out loud, rewatch, and send to a friend.

Look for:
- Jokes that land perfectly
- Accidental comedy or self-own moments
- Misunderstandings that escalate
- Reactions that are disproportionate to what happened
- Timing that makes an ordinary sentence hilarious

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


def educational_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """
    Educational / insight-focused prompt.
    Best for podcasts, interviews, tutorials, documentary content.
    """
    context = (
        f"(Chunk {chunk_index + 1} of {total_chunks})"
        if total_chunks > 1
        else ""
    )

    return f"""You are a content strategist who specialises in extracting knowledge-dense moments from long-form video.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} most insightful moments — \
moments that teach something, change how you think, or deliver a clear takeaway in under 3 minutes.

Look for:
- Concise explanations of complex ideas
- Surprising facts or statistics
- Strong opinions backed by reasoning
- Personal stories that illustrate a larger point
- Moments where the speaker says something genuinely new or contrarian

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


def scary_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """Find disturbing, frightening, tense, creepy, shocking, or unsettling moments."""
    context = f"(Chunk {chunk_index + 1} of {total_chunks})" if total_chunks > 1 else ""
    return f"""You are an editor finding the most frightening and unsettling moments in video.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} most disturbing, frightening, tense, creepy, shocking, or unsettling moments.

Look for danger, genuine fear, creepy stories, disturbing discoveries, ominous details, sudden shocks, and escalating tension.

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


def dramatic_clips(transcript_chunk: str, chunk_index: int, total_chunks: int) -> str:
    """
    Drama / tension-focused prompt.
    Best for reaction content, debates, confrontations, sports commentary.
    """
    context = (
        f"(Chunk {chunk_index + 1} of {total_chunks})"
        if total_chunks > 1
        else ""
    )

    return f"""You are a highlight editor who specialises in tension, drama, and emotional peaks.

Analyze this transcript {context} and find the {TOP_CLIPS_COUNT} most dramatic moments — \
moments where stakes are high, emotions are raw, or something genuinely surprising happens.

Look for:
- Confrontations or heated exchanges
- Moments of shock or disbelief
- Turning points where everything changes
- Strong emotional reactions (rage, grief, elation)
- Cliffhangers or unresolved tension

Transcript:
{transcript_chunk}

Return this exact JSON structure:
{_CLIP_SCHEMA}
{_SHARED_RULES}"""


# ─── Prompt Registry ──────────────────────────────────────────────────────────
#
# Maps a short key to its prompt function.
# ai.py uses this to select the right prompt without a chain of if/elif.
# Adding a new prompt type = add one entry here.

PROMPT_TYPES: dict[str, callable] = {
    "viral":       viral_clips,
    "interesting": interesting_clips,
    "funny":       funny_clips,
    "educational": educational_clips,
    "dramatic":    dramatic_clips,
    "scary":       scary_clips,
}

DEFAULT_PROMPT_TYPE = "viral"


def get_prompt(
    prompt_type: str,
    transcript_chunk: str,
    chunk_index: int = 0,
    total_chunks: int = 1,
) -> str:
    """
    Return the built prompt string for the given type and chunk.

    Falls back to DEFAULT_PROMPT_TYPE if the key isn't recognised.
    This is the only function ai.py needs to call.
    """
    fn = PROMPT_TYPES.get(prompt_type, PROMPT_TYPES[DEFAULT_PROMPT_TYPE])
    return fn(transcript_chunk, chunk_index, total_chunks)
