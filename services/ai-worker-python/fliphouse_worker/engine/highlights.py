"""Find the most viral-worthy highlights in a transcript.

Logic ported from SamurAIGPT/AI-Youtube-Shorts-Generator:
  - content-type / density detection
  - chunking for long videos with overlap
  - virality-criteria prompt
  - score-based dedupe with overlap suppression

The LLM call is injected via the required ``llm_fn`` argument — there is no
hardcoded or paid provider in our tree (the upstream MuAPI default is dropped).
``llm_fn`` is wired to our OpenRouter adapter in a later step.
"""

import json
import logging
import re
from collections.abc import Callable

logger = logging.getLogger(__name__)

LLMFn = Callable[[str], str]
# Reliable recall seam: prompt -> already-parsed strict-JSON highlights dict.
HighlightFn = Callable[[str], dict]


CONTENT_TYPE_PROMPT = """Analyze this video transcript sample and classify the content type.
Choose one: podcast, interview, tutorial, lecture, commentary, debate, vlog, other.
Also estimate content density: low (mostly filler/chit-chat), medium, or high (dense info/stories).
Respond with JSON only: {"content_type": "...", "density": "..."}"""


VIRALITY_CRITERIA = """
Virality signals to prioritize (ranked by impact):
1. HOOK MOMENTS — statements that create immediate curiosity ("The secret is...", "Nobody talks about...", "I was completely wrong about...")
2. РАЗНОС / HOT-TAKE — a blunt verdict, a takedown, a system or myth being torn apart, someone getting exposed, a fight-starting claim delivered with force. This is the single highest-converting kind of clip — hunt for it
3. OPINION BOMBS — strong, polarizing or counter-intuitive statements that pick a side and trigger agree/disagree (NOT measured "it depends" takes)
4. EMOTIONAL PEAKS — genuine surprise, laughter, anger, vulnerability, excitement; raw unscripted reactions; high-arousal only (awe/anger/outrage/amusement beat calm/sadness)
5. REVELATION MOMENTS — surprising facts, stats, or confessions that reframe how the viewer thinks; a shocking number
6. QUOTABLE ONE-LINERS — a single declarative sentence that works as a standalone quote-card / screenshot; the clip's best line should be caption-worthy
7. CONFLICT/TENSION — disagreement, pushback, or a problem being confronted head-on
8. STORY PEAKS — the climax or twist of an anecdote; the payoff moment
9. PRACTICAL VALUE — a concrete tip, hack, or insight the viewer can immediately apply (lowest weight — a useful explainer rarely goes viral on its own)

AVOID (these are FLAT, not viral): calm balanced explainers, hedged "it depends / pros and cons" takes, setup-only fragments with no landed line, polite agreement, logistics, recaps, and quiet consensus. Correctness is NOT virality — do not surface a clip just because it is informative.
"""


HIGHLIGHT_SYSTEM_PROMPT = """You are an elite short-form video editor who has studied thousands of viral clips on TikTok, Instagram Reels, and YouTube Shorts. You know exactly what makes viewers stop scrolling, watch to the end, and share.

{virality_criteria}

Content type: {content_type} | Density: {density}

Your task: identify the most viral-worthy highlights from the transcript.

Rules:
- Every highlight must open with a strong HOOK — a line that grabs attention within the first 3 seconds. RU hooks that work: a number/stat ("я потерял миллион"), negation ("никто не говорит"), a secret frame ("на самом деле", "мало кто знает"), a contradiction ("я был неправ"), a question, or stakes. A bland RU opener ("так, давайте", "ну, в общем", "сегодня поговорим о") is NOT a hook
- Every highlight must be a COMPLETE HOOK→PAYOFF ARC: the opening hook promises something, the middle builds it, and the clip RESOLVES that same promise inside its own boundaries (a stated answer, lesson, punchline, or twist). Reject a hook-only fragment that opens a gap it never closes, and a payoff-only fragment whose setup lives outside the window
- Duration sweet spot: 15-60 seconds. Go shorter (15-29s) only for a perfect standalone one-liner. Go longer (61-180s) only when a story arc needs full context to land
- Boundaries must land on SENTENCE EDGES: start on the first word of a sentence and end on the last word of a sentence. Never start or end on a mid-thought connective ("и поэтому…", "так что…", "а потом…", "и тогда я…"). Never cut mid-sentence or mid-thought — each clip must feel complete and self-contained
- end_phrase DISCIPLINE (CRITICAL — most common failure): the "end_phrase" MUST be the last words of a GRAMMATICALLY COMPLETE sentence. It must end on a real full stop (a landed statement, question, or exclamation). It must NEVER end on a connective, preposition, conjunction, or any dangling/unfinished clause — if a listener would expect more words after it, it is WRONG. Concrete RU examples:
  - BAD (mid-sentence, dangling — NEVER do this): "…для тех, кто" · "…именно поэтому" · "…и мы" · "…что" · "…который" · "…на самом деле" · "…потому что" · "…так что"
  - GOOD (a finished sentence — ALWAYS do this): "…поставьте лайк." · "…это гибрид." · "…я потерял всё." · "…мощности." · "…вот в чём секрет."
  If the natural end of the thought is a few words further on, EXTEND the clip to include them rather than cutting on a connective.
- start_phrase DISCIPLINE: the "start_phrase" MUST be the FIRST words of a FRESH sentence — never start mid-clause, mid-list, or on a connective ("и…", "а…", "но…", "потому что…", "который…"). The first word should open a new thought, not continue a prior one.
- For each highlight, also return "start_phrase" and "end_phrase": copy them VERBATIM from the transcript (exact words, in order, no paraphrase). "start_phrase" is the first few words the clip opens on; "end_phrase" is the last few words the clip ends on, and MUST be the final words of a COMPLETE sentence/thought — never a mid-thought connective. These anchor the boundaries to the real audio
- Clips must not overlap significantly with each other
- Score 0-100 on viral potential (not general quality)
- {num_clips_instruction}
- For each highlight, identify the single best "hook_sentence" — the opening line that would make someone stop scrolling
- Explain in one sentence why this clip is viral ("virality_reason")

Respond ONLY with valid JSON (no markdown, no explanation):
{{"highlights":[{{"title":"string","start_time":float,"end_time":float,"start_phrase":"string","end_phrase":"string","score":int,"hook_sentence":"string","virality_reason":"string"}}]}}"""


CHUNK_SIZE_SECONDS = 720  # 12-min chunks: shorter output → far less length-truncation
LONG_VIDEO_THRESHOLD = 1800  # chunk videos longer than 30 min
CHUNK_OVERLAP_SECONDS = 60
MAX_HIGHLIGHT_API_ATTEMPTS = 3


def _parse_json_loose(raw: str) -> dict:
    """Models sometimes wrap JSON in markdown fences — strip and parse."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1:
            return json.loads(text[start : end + 1])
        raise


def _coerce_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object, default: int = 0) -> int:
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _sanitize_highlights(raw_highlights: object, duration: float) -> list[dict]:
    """Normalize model output into the expected shape; skip invalid entries."""
    if not isinstance(raw_highlights, list):
        return []

    max_end = duration if duration > 0 else float("inf")
    cleaned: list[dict] = []
    for item in raw_highlights:
        if not isinstance(item, dict):
            continue

        start = _coerce_float(item.get("start_time"), default=-1.0)
        end = _coerce_float(item.get("end_time"), default=-1.0)
        if start < 0 or end <= start:
            continue

        if max_end != float("inf"):
            start = min(start, max_end)
            end = min(end, max_end)
            if end <= start:
                continue

        cleaned.append(
            {
                "title": str(item.get("title") or "Untitled Highlight").strip(),
                "start_time": start,
                "end_time": end,
                # Verbatim phrase anchors (dormant-path resilience): default '' when
                # the model omits them, so the float bounds stay the required locator
                # and old behavior is preserved. Carried through for align.py.
                "start_phrase": str(item.get("start_phrase") or "").strip(),
                "end_phrase": str(item.get("end_phrase") or "").strip(),
                "score": max(0, min(100, _coerce_int(item.get("score"), default=0))),
                "hook_sentence": str(item.get("hook_sentence") or "").strip(),
                "virality_reason": str(item.get("virality_reason") or "").strip(),
            }
        )

    return cleaned


def detect_content_type(transcript: dict, *, llm_fn: LLMFn) -> dict[str, str]:
    segments = transcript.get("segments", [])
    sample = " ".join(s["text"] for s in segments[:25])[:3000]
    prompt = f"{CONTENT_TYPE_PROMPT}\n\nTranscript sample:\n{sample}"
    try:
        raw = llm_fn(prompt)
        return _parse_json_loose(raw)
    except Exception:
        return {"content_type": "other", "density": "medium"}


def build_transcript_text(transcript: dict) -> str:
    segments = transcript.get("segments", [])
    return "\n".join(f"[{s['start']:.1f}s] {s['text'].strip()}" for s in segments)


def chunk_transcript(transcript: dict) -> list[dict]:
    """Split a long transcript into overlapping chunks with CHUNK-RELATIVE timestamps.

    REGRESSION GUARD (real [7,1,0,0,0,0,0] coverage collapse): the segment times
    handed to the model MUST be rebased to the chunk origin. The model reads those
    times in ``build_transcript_text`` and returns highlight times on the SAME
    scale; ``_sanitize_highlights`` then clamps against ``chunk["duration"]``
    (relative) and ``get_highlights`` re-adds ``_offset``. If segments stayed
    ABSOLUTE, the model would return absolute times, the clamp would crush every
    chunk-2+ highlight to ``end<=start`` (dropped), and only chunk 1 (offset 0,
    where absolute==relative) would survive — exactly the observed failure.
    """
    segments = transcript.get("segments", [])
    duration = transcript.get("duration", segments[-1]["end"] if segments else 0)
    chunks = []
    start = 0
    while start < duration:
        end = min(start + CHUNK_SIZE_SECONDS, duration)
        chunk_segs = [
            {**s, "start": s["start"] - start, "end": s["end"] - start}
            for s in segments
            if s["start"] >= start and s["end"] <= end + CHUNK_OVERLAP_SECONDS
        ]
        if chunk_segs:
            chunk = dict(transcript)
            chunk["segments"] = chunk_segs
            # Bound the sanitize clamp to the real (relative) content end so a
            # highlight in the overlap tail isn't crushed; offset re-added later.
            chunk["duration"] = max(s["end"] for s in chunk_segs)
            chunk["_offset"] = start
            chunks.append(chunk)
        start += CHUNK_SIZE_SECONDS - CHUNK_OVERLAP_SECONDS
    return chunks


def call_highlight_api(
    transcript_text: str,
    content_info: dict,
    duration: float,
    num_clips: int,
    is_chunk: bool = False,
    *,
    llm_fn: LLMFn | None = None,
    highlight_fn: HighlightFn | None = None,
) -> dict:
    # Ask for ~2× the user's target so dedupe has headroom, but cap so the model
    # doesn't have to generate a huge JSON payload (which times out the model).
    target = max(num_clips * 2, 5)
    natural_max = max(2 if is_chunk else 3, int(duration / 90))
    min_clips = min(target, natural_max, 8)
    system = HIGHLIGHT_SYSTEM_PROMPT.format(
        virality_criteria=VIRALITY_CRITERIA,
        content_type=content_info.get("content_type", "other"),
        density=content_info.get("density", "medium"),
        num_clips_instruction=f"Generate at least {min_clips} highlights",
    )
    base_prompt = f"{system}\n\nTranscript:\n{transcript_text}"
    prompt = base_prompt
    last_error = "unknown"

    for attempt in range(1, MAX_HIGHLIGHT_API_ATTEMPTS + 1):
        try:
            # strict-JSON seam returns a parsed dict; the LLM call is INSIDE the
            # try so a complete_json ValueError is caught + retried, never escapes
            # to kill the whole video (the chunk loop relies on that contract).
            if highlight_fn is not None:
                parsed = highlight_fn(prompt)
            else:
                parsed = _parse_json_loose(llm_fn(prompt))
            highlights = _sanitize_highlights(parsed.get("highlights"), duration=duration)
            if highlights:
                return {"highlights": highlights}
            last_error = "no valid highlights in response"
        except (RuntimeError, ValueError) as e:
            last_error = str(e)

        if attempt < MAX_HIGHLIGHT_API_ATTEMPTS:
            logger.warning(
                "invalid model output on attempt %d/%d; retrying",
                attempt,
                MAX_HIGHLIGHT_API_ATTEMPTS,
            )
            prompt = (
                base_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON with a top-level 'highlights' array."
                + " Each item must include: title, start_time, end_time, start_phrase, end_phrase, score, hook_sentence, virality_reason."
                + " No markdown fences, no commentary."
            )

    raise RuntimeError(
        f"Highlight generator produced invalid output after {MAX_HIGHLIGHT_API_ATTEMPTS} attempts: {last_error}"
    )


def dedupe_highlights(highlights: list[dict]) -> list[dict]:
    """Drop a highlight if it overlaps >50% with a higher-scoring one already kept."""
    highlights = sorted(highlights, key=lambda x: int(x.get("score", 0)), reverse=True)
    kept: list[dict] = []
    for h in highlights:
        h_start = float(h["start_time"])
        h_end = float(h["end_time"])
        h_dur = h_end - h_start
        overlapping = False
        for k in kept:
            latest_start = max(h_start, float(k["start_time"]))
            earliest_end = min(h_end, float(k["end_time"]))
            overlap = earliest_end - latest_start
            if overlap > 0 and overlap > 0.5 * h_dur:
                overlapping = True
                break
        if not overlapping:
            kept.append(h)
    return kept


def get_highlights(
    transcript: dict,
    num_clips: int = 3,
    *,
    llm_fn: LLMFn,
    highlight_fn: HighlightFn | None = None,
    dedupe: bool = True,
) -> dict:
    """Core entry point — returns {highlights: [...]} sorted by score.

    ``llm_fn`` is required (keyword-only) for content-type detection. When
    ``highlight_fn`` is given, recall uses the reliable strict-JSON seam for the
    highlight calls (``llm_fn`` still serves the loose content-type probe). Pass
    ``dedupe=False`` to skip overlap suppression — Stage A recall (P2-S5) needs
    the full candidate set, then applies its own relaxed dedupe downstream.
    """
    duration = transcript.get("duration", 0)
    content_info = detect_content_type(transcript, llm_fn=llm_fn)
    logger.info(
        "content=%s density=%s duration=%.0fs",
        content_info.get("content_type"),
        content_info.get("density"),
        duration,
    )

    if duration >= LONG_VIDEO_THRESHOLD:
        chunks = chunk_transcript(transcript)
        logger.info("long video — splitting into %d chunks", len(chunks))
        all_highlights: list[dict] = []
        for i, chunk in enumerate(chunks):
            offset = chunk.get("_offset", 0)
            text = build_transcript_text(chunk)
            logger.info("chunk %d/%d (offset %.0fs)", i + 1, len(chunks), offset)
            try:
                result = call_highlight_api(
                    text,
                    content_info,
                    chunk["duration"],
                    num_clips=num_clips,
                    is_chunk=True,
                    llm_fn=llm_fn,
                    highlight_fn=highlight_fn,
                )
            except (RuntimeError, ValueError) as exc:
                # A single flaky chunk must NOT lose the rest of a long video — skip
                # it and continue; we fail loudly below only if EVERY chunk fails.
                logger.warning("chunk %d/%d failed (%s); skipping", i + 1, len(chunks), exc)
                continue
            for h in result.get("highlights", []):
                h["start_time"] = float(h["start_time"]) + offset
                h["end_time"] = float(h["end_time"]) + offset
                all_highlights.append(h)
        if not all_highlights:
            raise RuntimeError(f"all {len(chunks)} chunks failed to produce highlights")
        highlights = dedupe_highlights(all_highlights) if dedupe else all_highlights
    else:
        text = build_transcript_text(transcript)
        result = call_highlight_api(
            text,
            content_info,
            duration,
            num_clips=num_clips,
            llm_fn=llm_fn,
            highlight_fn=highlight_fn,
        )
        raw = result.get("highlights", [])
        highlights = dedupe_highlights(raw) if dedupe else raw

    return {"highlights": highlights}


def select_highlights(transcript: dict, *, llm_fn: LLMFn, num_clips: int = 3) -> list[dict]:
    """Public seam: transcript → ranked highlights via the injected ``llm_fn``.

    Returns ``[]`` for a transcript with no speech segments (no LLM call).
    """
    if not transcript.get("segments"):
        return []
    return get_highlights(transcript, num_clips=num_clips, llm_fn=llm_fn).get("highlights", [])
