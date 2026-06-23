"""Unit coverage for engine/segmenter.py — pure, no ffmpeg/network.

The segmenter walks a transcript IN ORDER into contiguous, gap-aware,
boundary-snapped windows and grades nothing (scoring happens downstream). These
tests pin its determinism: ordering, gap splits, the target duration band, the
shared-snapper reuse, the empty case, and CandidateClip field population.
"""

from fliphouse_worker.dsp import LocalSignals, Pause
from fliphouse_worker.engine.recall import dsp_prior_score, refine_boundaries
from fliphouse_worker.engine.segmenter import (
    SEGMENT_GAP_S,
    TARGET_MAX_S,
    TARGET_MIN_S,
    linear_segments,
)


def _signals(pauses=()):
    return LocalSignals(pauses=tuple(pauses), energy_peaks_s=(), scene_cuts=(), audio_flags=())


def _seg(start, end, text="word word word"):
    return {"start": start, "end": end, "text": text}


def _transcript(segments, duration=None):
    dur = duration if duration is not None else (segments[-1]["end"] if segments else 0.0)
    return {"segments": segments, "duration": dur}


def test_empty_segments_returns_empty():
    assert linear_segments(_transcript([]), _signals()) == ()


def test_missing_segments_key_returns_empty():
    assert linear_segments({"duration": 10.0}, _signals()) == ()


def test_windows_in_strictly_increasing_start_order():
    # Three runs separated by big gaps; each run ~40s (over target_min 15).
    segs = [
        _seg(0, 40),
        _seg(100, 140),
        _seg(200, 240),
    ]
    out = linear_segments(_transcript(segs), _signals(), gap_s=5.0)
    starts = [c.start_time for c in out]
    assert starts == sorted(starts)
    assert len(out) == 3


def test_gap_splits_into_two_windows_without_spanning_the_gap():
    segs = [_seg(0, 40), _seg(60, 100)]  # 20s gap >> SEGMENT_GAP_S
    out = linear_segments(_transcript(segs), _signals())
    assert len(out) == 2
    # No emitted window straddles the [40, 60] gap.
    for c in out:
        assert not (c.start_time < 60 and c.end_time > 40 and c.start_time < 40)


def test_contiguous_run_within_gap_stays_one_window():
    # Two adjacent segments with a tiny gap (< SEGMENT_GAP_S) merge into one window.
    segs = [_seg(0, 20), _seg(20.5, 40)]
    out = linear_segments(_transcript(segs), _signals(), gap_s=SEGMENT_GAP_S)
    assert len(out) == 1
    assert out[0].start_time == 0.0
    assert out[0].end_time == 40.0


def test_long_run_splits_at_target_max():
    # One contiguous run of 1s segments far longer than TARGET_MAX_S splits into
    # multiple windows; none exceeds the band by more than one segment's worth.
    segs = [_seg(i, i + 1) for i in range(int(TARGET_MAX_S) * 3)]  # ~270s contiguous
    out = linear_segments(_transcript(segs), _signals(), gap_s=SEGMENT_GAP_S)
    assert len(out) >= 2
    for c in out[:-1]:  # every flushed-by-band window respects the cap (+1 seg slack)
        assert c.end_time - c.start_time <= TARGET_MAX_S + 1.0


def test_short_tail_run_is_dropped():
    # A full window then a sub-floor tail (< TARGET_MIN_S) after a gap → tail dropped.
    segs = [_seg(0, 40), _seg(100, 110)]  # tail is 10s, below 15
    out = linear_segments(_transcript(segs), _signals())
    assert len(out) == 1
    assert out[0].start_time == 0.0


def test_single_short_run_yields_nothing():
    segs = [_seg(0, 10)]  # below TARGET_MIN_S → not a clip
    assert linear_segments(_transcript(segs), _signals()) == ()


def test_boundary_snapping_matches_shared_refine_boundaries():
    # word_segments carry a sentence-end gap so refine_boundaries actually shifts;
    # the emitted window must equal a DIRECT refine_boundaries call (shared snapper).
    word_segments = [
        {
            "words": [
                {"word": "Hello.", "start": 0.0, "end": 0.5},
                {"word": "World", "start": 2.0, "end": 40.0},
            ]
        }
    ]
    segs = [_seg(0.0, 40.0)]
    pauses = (Pause(0.4, 1.9),)
    sig = _signals(pauses)
    out = linear_segments(_transcript(segs, duration=40.0), sig, word_segments=word_segments)
    assert len(out) == 1
    words = [w for ws in word_segments for w in ws["words"]]
    expected = refine_boundaries(0.0, 40.0, words, pauses, 40.0)
    assert (out[0].start_time, out[0].end_time) == expected


def test_candidate_fields_populated():
    segs = [_seg(0, 40, text="The hook lands here and keeps going strong indeed now")]
    sig = _signals()
    out = linear_segments(_transcript(segs), sig)
    assert len(out) == 1
    c = out[0]
    assert c.llm_score == 0.0
    assert c.dsp_prior == dsp_prior_score(c.start_time, c.end_time, sig)
    assert c.text_excerpt  # non-empty excerpt from the transcript
    assert c.title == "The hook lands here and keeps going strong"  # first 8 words


def test_title_empty_when_first_segment_text_blank():
    # A run whose first segment has no text still emits a window (title falls back to "").
    segs = [_seg(0, 20, text=""), _seg(20, 40, text="later words")]
    out = linear_segments(_transcript(segs), _signals(), gap_s=SEGMENT_GAP_S)
    assert len(out) == 1
    assert out[0].title == ""


def test_uses_target_min_default_constant():
    # Sanity: the default band keeps windows inside refine_boundaries' valid range.
    assert TARGET_MIN_S >= 15.0
    assert TARGET_MAX_S <= 180.0


def test_target_band_resolves_to_15_60():
    # The viral sweet spot: target window is exactly 15–60s after the clamp guards.
    assert TARGET_MIN_S == 15.0
    assert TARGET_MAX_S == 60.0
