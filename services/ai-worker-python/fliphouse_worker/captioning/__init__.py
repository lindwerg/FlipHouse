"""Caption burn-in (P2 step 5): Russian word-highlight subtitles → reframed 9:16 clips.

The reframe stage emits ranked 1080×1920 clips at ``t=0``; this leg slices the
ASR ``word_segments`` to each clip window, groups the words into 1–3-word lines,
renders a libass-native ``\\k`` karaoke ``.ass`` (white base, active-word flip),
and burns it in with a single LGPL-clean ``libopenh264`` ffmpeg pass. Every pure
builder (slice/offset, line grouping, ASS text, ffmpeg argv) is unit-tested to
100%; the only impure boundary is the injected ffmpeg burn seam.
"""
