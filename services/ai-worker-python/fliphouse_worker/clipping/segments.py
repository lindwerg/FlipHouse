"""Dynamic-reframe segmentation (P2 reframe steps 3+4).

A single ffmpeg ``crop`` is geometrically constant while active, so a clip that
TRACKs a speaker for part of its span and shows the WHOLE frame (centered fill)
for a b-roll part cannot be one render. This module turns a per-sample
:class:`CropTrajectory` into an ordered list of :class:`RenderSegment`s — each a
contiguous time interval with ONE :class:`CropBox` — which ``render.py`` renders
independently and concatenates. A debounced FSM (asymmetric hysteresis) decides
TRACK↔GENERAL per keyframe so a single dropped/extra face never flips the mode;
short segments are merged and transition boundaries snap to scene cuts.

Founder mandate: TRACK runs fill the frame with a 9:16 SPEAKER crop (speaker/union/
STACK). GENERAL/b-roll runs now CONTAIN the WHOLE source frame — fit it inside
1080×1920 with the margins filled by a blurred cover-zoom — so nothing is cropped out
(founder: "чтобы всё входило"); the GENERAL center-column crop is retired. Every
emitted box is still ``CROP_MODE`` (CONTAIN is a CROP-family layout, NOT blur-pad), so
the fail-closed ``BLURPAD`` render guard is unaffected. The absolute no-keyframe
fail-safe stays a centered crop. PURE.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import median

from .crop_geometry import (
    BLURPAD_MODE,
    CROP_MODE,
    TRACK_MARK,
    CropBox,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    compute_contain_box,
    compute_crop_box,
    compute_stack_box,
)

N_DROP_SAMPLES: int = 3  # 1.5s @2Hz of "no face" before TRACK→GENERAL (sticky to tracking)
N_ACQUIRE_SAMPLES: int = 2  # 1.0s @2Hz of "face" before GENERAL→TRACK (quicker to re-acquire)
MIN_SEGMENT_DURATION_S: float = 0.75  # merge anything shorter into a neighbour
# Opening-stability floor: the FIRST segment must hold its framing at least this long, or
# it is absorbed forward into the second — so a clip never opens on a ~1s transient mode
# (3 samples @2Hz ≥ the worst-case causal transient). Scoped to index 0 ONLY; the interior
# ``MIN_SEGMENT_DURATION_S`` floor stays 0.75s so legitimate short interior shots survive.
OPENING_MIN_SEGMENT_S: float = 1.5
# A run renders as a split-screen STACK only when at least this fraction of its TRACK
# keyframes are split (carry panels) — one transient split frame never flips the run.
STACK_RUN_FRACTION: float = 0.5


@dataclass(frozen=True)
class RenderSegment:
    """A contiguous clip-relative interval rendered with one crop window."""

    start_s: float  # clip-relative seconds (0.0 = clip start)
    end_s: float
    box: CropBox

    @property
    def span(self) -> float:
        return self.end_s - self.start_s


def _block_bounds(
    keyframes: Sequence[CropKeyframe], scene_cut_times: Sequence[float]
) -> list[tuple[int, int]]:
    """Partition keyframe indices into ``[(first, last), ...]`` blocks split at scene cuts.

    A block boundary falls between consecutive keyframes ``i`` and ``i+1`` when a scene cut
    ``c`` lies in ``[kf[i].t, kf[i+1].t]`` — the SAME cut-in-window predicate
    :func:`_transition_boundary` uses, so vote-blocks and boundary-snapping always agree.
    No cuts → one block spanning the whole clip. PURE.
    """
    n = len(keyframes)
    blocks: list[tuple[int, int]] = []
    start = 0
    for i in range(n - 1):
        t0, t1 = keyframes[i].t, keyframes[i + 1].t
        if any(t0 <= c <= t1 for c in scene_cut_times):
            blocks.append((start, i))
            start = i + 1
    blocks.append((start, n - 1))
    return blocks


def resolve_mode_timeline(
    keyframes: Sequence[CropKeyframe],
    *,
    scene_cut_times: Sequence[float] = (),
) -> tuple[str, ...]:
    """Per-keyframe TRACK/GENERAL → NON-CAUSAL per-keyframe CROP_MODE/BLURPAD_MODE label.

    The mode label is only ever TRACK (``CROP_MODE``) vs GENERAL (``BLURPAD_MODE``): both
    render as a CROP-family box (speaker column vs full-frame CONTAIN) — the label only
    decides the framing, never whether to blur-pad. The whole clip is available at render
    time, so the decision is NON-CAUSAL: keyframes are partitioned into scene-cut-delimited
    BLOCKS and every sample in a block adopts the block's MAJORITY raw label. This kills the
    start-of-clip "скачет" transient — a 1-2 sample mis-moded head can never define the
    opening run because it is outvoted by its block. Genuine mode changes still land crisply
    because each scene-cut block votes independently. Ties break toward ``CROP_MODE``
    (speaker-tracking is the safer default for the talking-head product). Empty input →
    empty tuple. PURE.
    """
    if not keyframes:
        return ()

    def _raw(kf: CropKeyframe) -> str:
        # ONLY a genuine speaker-tracked (TRACK) keyframe votes CROP (a 9:16 speaker
        # column). GENERAL (faceless/edge/crowd) AND CONTEXT_CONTAIN (a face-bearing
        # cinematic WIDE shot whose tight column would slice the scene) BOTH render as
        # the full-frame CONTAIN graph, so both vote BLURPAD_MODE — the CONTAIN/GENERAL
        # side of the non-causal block majority. A transient context blip is thus
        # outvoted and can never define the opening run (no start-of-clip jump).
        return CROP_MODE if kf.mode == TRACK_MARK else BLURPAD_MODE

    raws = [_raw(kf) for kf in keyframes]
    out: list[str] = [""] * len(keyframes)
    for first, last in _block_bounds(keyframes, scene_cut_times):
        n_crop = sum(1 for i in range(first, last + 1) if raws[i] == CROP_MODE)
        n_total = last - first + 1
        # Majority vote; tie (2*n_crop == n_total) breaks toward CROP_MODE.
        label = CROP_MODE if 2 * n_crop >= n_total else BLURPAD_MODE
        for i in range(first, last + 1):
            out[i] = label
    return tuple(out)


def _transition_boundary(t_last: float, t_next: float, scene_cut_times: Sequence[float]) -> float:
    """Boundary between two runs: the sample midpoint, unless a scene cut falls in
    ``[t_last, t_next]`` — then snap to the cut nearest that midpoint (the mode
    flip lands exactly on the visible cut, not mid-shot)."""
    mid = (t_last + t_next) / 2.0
    in_window = [c for c in scene_cut_times if t_last <= c <= t_next]
    return min(in_window, key=lambda c: abs(c - mid)) if in_window else mid


def _collapse_runs(modes: Sequence[str]) -> list[tuple[int, int, str]]:
    """Run-length collapse → ``[(first_idx, last_idx, mode), ...]``."""
    runs: list[tuple[int, int, str]] = []
    start = 0
    for i in range(1, len(modes)):
        if modes[i] != modes[start]:
            runs.append((start, i - 1, modes[start]))
            start = i
    runs.append((start, len(modes) - 1, modes[start]))
    return runs


def _backfill_opening(segs: list[dict], opening_min_s: float) -> list[dict]:
    """Absorb a too-short OPENING segment forward into the next so the clip opens stable.

    Even with the non-causal vote a genuinely short FIRST block (a ~1s cold-open before
    the first cut) could still flash a mode the clip immediately leaves. If the first
    segment is shorter than ``opening_min_s`` AND its mode differs from the second's, it is
    merged forward into the second (the second's start backfilled to 0.0, seg0 dropped) —
    the existing idx==0 merge path, but on the higher opening-specific floor. Interior
    segments are untouched (their floor stays ``MIN_SEGMENT_DURATION_S``). PURE.
    """
    if len(segs) > 1:
        first = segs[0]
        if first["end"] - first["start"] < opening_min_s and first["mode"] != segs[1]["mode"]:
            segs[1]["start"] = first["start"]
            del segs[0]
    return segs


def _merge_short(segs: list[dict], min_segment_s: float) -> list[dict]:
    """Merge any segment shorter than ``min_segment_s`` into a neighbour (previous
    preferred; the first into the next), then coalesce same-mode neighbours."""
    while len(segs) > 1:
        idx = next((i for i, s in enumerate(segs) if s["end"] - s["start"] < min_segment_s), None)
        if idx is None:
            break
        if idx > 0:
            segs[idx - 1]["end"] = segs[idx]["end"]
        else:
            segs[1]["start"] = segs[0]["start"]
        del segs[idx]
        i = 0
        while i < len(segs) - 1:
            if segs[i]["mode"] == segs[i + 1]["mode"]:
                segs[i]["end"] = segs[i + 1]["end"]
                segs[i]["centers"] = segs[i]["centers"] + segs[i + 1]["centers"]
                segs[i]["faces"] = segs[i]["faces"] + segs[i + 1]["faces"]
                segs[i]["panel_sets"] = segs[i]["panel_sets"] + segs[i + 1]["panel_sets"]
                segs[i]["n_track"] = segs[i]["n_track"] + segs[i + 1]["n_track"]
                del segs[i + 1]
            else:
                i += 1
    return segs


def _run_face(centers: list[float], faces: list[FaceBox]) -> FaceBox | None:
    """The representative active-subject box for a run: the (smoothed) subject box whose
    center is nearest the run's median center. ``None`` when the run carried no face.
    This box SIZES the 9:16 window (upper-third, min-zoom clamped); the median center
    positions it horizontally. PURE."""
    if not faces:
        return None
    if not centers:
        return faces[0]
    target = median(centers)
    return min(faces, key=lambda f: abs(f.center_x - target))


def _stack_panels_for_run(
    panel_sets: list[tuple[FaceBox, ...]], n_track: int
) -> tuple[FaceBox, ...]:
    """The per-speaker faces to split-screen for a run, or ``()`` to keep one window.

    ``panel_sets`` are the split keyframes' panel tuples (non-split TRACK keyframes
    contribute nothing). A run is a STACK only when a MAJORITY (``STACK_RUN_FRACTION``)
    of its TRACK keyframes are split — one transient split frame can't flip a steady
    single-window run. The representative panels are the LAST agreeing sample's (a
    stable, recent framing). PURE.
    """
    if not panel_sets or len(panel_sets) < STACK_RUN_FRACTION * n_track:
        return ()
    return panel_sets[-1]


def _box_for_run(
    traj: CropTrajectory,
    mode: str,
    centers: list[float],
    faces: list[FaceBox],
    panel_sets: list[tuple[FaceBox, ...]],
    n_track: int,
) -> CropBox:
    """Resolve a run's :class:`CropBox` — a CROP-family box (never blur-pad).

    GENERAL/b-roll runs CONTAIN the WHOLE source frame (fit inside 1080×1920, margins
    filled by a blurred cover-zoom) so nothing is cropped out (founder: "чтобы всё
    входило"). TRACK runs that a majority of samples mark as a split → a vertical
    split-screen STACK (each speaker its own EXACT ``target_w:(target_h/n)`` panel);
    otherwise the classic single-window speaker crop of the active-SUBJECT box (single
    face or union), centered on the run's median tracked center. CONTAIN, STACK, and
    SINGLE are all ``CROP_MODE`` (never blur-pad). PURE.
    """
    if mode == BLURPAD_MODE:
        return compute_contain_box(traj.source_width, traj.source_height)
    panels = _stack_panels_for_run(panel_sets, n_track)
    if panels:
        return compute_stack_box(panels, traj.source_width, traj.source_height)
    # The subject box SIZES the 9:16 window (upper-third, min-zoom clamped); the run's
    # median SMOOTHED center positions it horizontally.
    centre = median(centers) if centers else None
    return compute_crop_box(
        traj.source_width, traj.source_height, centre, face=_run_face(centers, faces)
    )


def build_render_segments(
    traj: CropTrajectory,
    *,
    clip_duration: float,
    scene_cut_times: Sequence[float] = (),
    min_segment_s: float = MIN_SEGMENT_DURATION_S,
) -> tuple[RenderSegment, ...]:
    """:class:`CropTrajectory` → ordered :class:`RenderSegment`s covering ``[0, clip_duration]``.

    No keyframes → ONE center-crop segment (fail-safe). A single-mode trajectory →
    exactly ONE segment (the render fast path). Otherwise: debounced mode timeline
    → run-length intervals (boundaries = sample midpoints, snapped to scene cuts)
    → short-segment merge → boxes (TRACK→speaker column on the run's median centre;
    GENERAL/b-roll→full-frame CONTAIN with a blurred margin fill so nothing is cropped
    out). EVERY box is ``CROP_MODE`` — never blur-pad. PURE.
    """
    kfs = traj.keyframes
    if not kfs:
        center = compute_crop_box(traj.source_width, traj.source_height, center_x=None)
        return (RenderSegment(0.0, clip_duration, center),)

    modes = resolve_mode_timeline(kfs, scene_cut_times=scene_cut_times)
    runs = _collapse_runs(modes)

    boundaries = [0.0]
    for ri in range(len(runs) - 1):
        boundaries.append(
            _transition_boundary(kfs[runs[ri][1]].t, kfs[runs[ri + 1][0]].t, scene_cut_times)
        )
    boundaries.append(clip_duration)

    segs = [
        {
            "start": boundaries[ri],
            "end": boundaries[ri + 1],
            "mode": mode,
            "centers": [
                kfs[k].center_x for k in range(s_i, e_i + 1) if kfs[k].center_x is not None
            ],
            "faces": [kfs[k].face for k in range(s_i, e_i + 1) if kfs[k].face is not None],
            # Split keyframes' panel tuples, and the TRACK-keyframe count of the run, so
            # the run only STACKs when a majority of its TRACK samples were split.
            "panel_sets": [kfs[k].panels for k in range(s_i, e_i + 1) if kfs[k].panels],
            "n_track": sum(1 for k in range(s_i, e_i + 1) if kfs[k].mode == TRACK_MARK),
        }
        for ri, (s_i, e_i, mode) in enumerate(runs)
    ]
    # Opening stability FIRST (raises the floor for index 0 only), THEN the interior
    # short-segment merge + coalesce — so if the opening is absorbed into the second and the
    # second then matches the third, the coalesce loop inside ``_merge_short`` still joins them.
    segs = _backfill_opening(segs, OPENING_MIN_SEGMENT_S)
    segs = _merge_short(segs, min_segment_s)

    return tuple(
        RenderSegment(
            s["start"],
            s["end"],
            _box_for_run(traj, s["mode"], s["centers"], s["faces"], s["panel_sets"], s["n_track"]),
        )
        for s in segs
    )
