"""PURE: caption_coverage — what fraction of a clip window carries burned captions.

Telemetry, NOT a gate. The reframe stage burns per-word captions sliced from the ASR
``word_segments`` to each clip window (see ``slice_and_offset_words``). If the upstream
ASR window arithmetic ever drifts absolute-vs-relative (the silent off-by-one this
metric exists to surface), the slice for a clip that DOES contain speech returns no
in-window words, the clip ships uncaptioned, and nothing fails — the paid render is
fail-open by design. ``caption_coverage`` measures the ratio of in-window SPEECH TIME
to the clip's wall duration so that dropout becomes a visible ``0.0`` in the metrics.

DEFINITION: covered speech-time / clip-window. The numerator is the union (overlaps
merged) of the sliced words' clip-relative ``[start, end]`` intervals, each clamped
into ``[0, duration]``; the denominator is the clip's wall duration. Chosen OVER
"in-window words / total candidate words" because the off-by-one drops EVERY word from
the slice, so an in-window/total ratio degenerates to ``0/0`` — the "total" is itself
the buggy slice and cannot tell "no speech here" from "speech silently lost". The
wall-duration denominator is independent of the slice, so a fully-spoken clip → ~1.0,
a fully-dropped clip → exactly 0.0, and a partial clip → the real fraction.

Fail-OPEN like the rest of captioning: coverage is ALWAYS a float in ``[0, 1]`` and
this module NEVER raises — a malformed window or word list yields ``0.0``, never an
exception that could block a clip.
"""

from __future__ import annotations

from .segments import CaptionWord, slice_and_offset_words

# (clip_start, clip_end) in SOURCE-absolute seconds — the exact pair passed to
# ``slice_and_offset_words`` (sourced from ``clip.candidate.start_time/end_time``).
ClipWindow = tuple[float, float]


def coverage_from_words(words: list[CaptionWord], clip_window: ClipWindow) -> float:
    """Merged in-window speech-time / clip duration, from an ALREADY-sliced word list.

    Consumes the SAME ``slice_and_offset_words`` result the caption ``.ass`` is built
    from (no second slice). ``words`` carry CLIP-RELATIVE timing (``start`` ∈
    ``[0, duration)``), so each is clamped into ``[0, duration]`` and overlaps merged
    so overlapping word timings can never push the ratio past 1.0. Always returns a
    float in ``[0, 1]``; NEVER raises.
    """
    try:
        clip_start, clip_end = float(clip_window[0]), float(clip_window[1])
    except (TypeError, ValueError, IndexError):
        return 0.0
    duration = clip_end - clip_start
    if duration <= 0.0:
        return 0.0

    intervals: list[tuple[float, float]] = []
    for w in words:
        try:
            lo = max(0.0, min(float(w.start), duration))
            hi = max(0.0, min(float(w.end), duration))
        except (TypeError, ValueError):
            continue
        if hi > lo:
            intervals.append((lo, hi))
    if not intervals:
        return 0.0

    intervals.sort()
    covered = 0.0
    cur_lo, cur_hi = intervals[0]
    for lo, hi in intervals[1:]:
        if lo <= cur_hi:  # overlapping or adjacent → extend the current run
            cur_hi = max(cur_hi, hi)
        else:
            covered += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
    covered += cur_hi - cur_lo

    return max(0.0, min(1.0, covered / duration))


def caption_coverage(word_segments: object, clip_window: ClipWindow) -> float:
    """Fraction of ``clip_window`` carrying burned-in caption speech, in ``[0, 1]``.

    Slices ``word_segments`` to the window ONCE via the canonical
    ``slice_and_offset_words`` and measures merged in-window speech-time / clip
    duration. PURE and fail-OPEN: any malformed input → ``0.0``, never raises.
    """
    try:
        clip_start, clip_end = float(clip_window[0]), float(clip_window[1])
    except (TypeError, ValueError, IndexError):
        return 0.0
    words = slice_and_offset_words(word_segments, clip_start, clip_end)
    return coverage_from_words(words, (clip_start, clip_end))
