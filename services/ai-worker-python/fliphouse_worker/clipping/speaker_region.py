"""Speaker-region selection for the vertical reframe (P2-2.4 render).

MVP CPU path: MediaPipe BlazeFace short-range (Tasks ``FaceDetector``, VIDEO mode,
CPU, headless) sampled at ``SAMPLE_FPS`` → per-frame largest-face pick with
stickiness + a switch cooldown (anti ping-pong) → :func:`smoothing.build_trajectory`
(One-Euro + scene-cut snap on PRECOMPUTED cut times passed as data — never a
per-clip rescan) → blur-pad GENERAL on a faceless or group-shot clip.

The GPU-precise path (LR-ASD / TalkNet on Modal/Replicate) is stubbed behind
``PHASE3_GPU_ASD`` and flagged-not-called. The render pipeline talks only to the
:class:`SpeakerRegionSelector` Protocol, so Phase 3 drops in without a refactor.

``_sample_faces_mediapipe`` and ``_probe_src_dims`` are the impure boundaries
(lazy-import mediapipe/cv2 / call ffprobe); both are injectable seams faked in
unit tests so the suite runs 100% offline.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from .crop_geometry import CropTrajectory, FaceBox
from .smoothing import RawSample, build_trajectory

SAMPLE_FPS: float = 2.0
STICKINESS_BONUS: float = 3.0
STICKY_RADIUS_FRAC: float = 0.12
SWITCH_COOLDOWN_FRAMES: int = 8
MODEL_PATH: Path = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"

# Phase-3 plug-point. False = MVP CPU heuristic path (the only live path today).
PHASE3_GPU_ASD: bool = False

SampleFacesFn = Callable[[str, float, float, float], tuple[tuple[FaceBox, ...], ...]]
ProbeDimsFn = Callable[[str], tuple[int, int]]


def select_active_face(
    faces: Sequence[FaceBox],
    prev_center_x: float | None,
    cooldown_left: int,
    src_w: int,
) -> tuple[FaceBox | None, int]:
    """Pick the speaking face — largest area × stickiness, with a switch cooldown.

    PURE. Returns ``(chosen | None, new_cooldown)``. With no faces, returns
    ``None`` and decays the cooldown. While cooling down after a switch, it sticks
    to the face nearest the previous center to avoid ping-ponging between heads.
    """
    if not faces:
        return None, max(0, cooldown_left - 1)

    sticky_radius = STICKY_RADIUS_FRAC * src_w

    if prev_center_x is not None and cooldown_left > 0:
        nearest = min(faces, key=lambda f: abs(f.center_x - prev_center_x))
        return nearest, cooldown_left - 1

    def _score(f: FaceBox) -> float:
        s = f.area
        if prev_center_x is not None and abs(f.center_x - prev_center_x) < sticky_radius:
            s *= STICKINESS_BONUS
        return s

    best = max(faces, key=_score)
    switched = prev_center_x is None or abs(best.center_x - prev_center_x) >= sticky_radius
    new_cooldown = SWITCH_COOLDOWN_FRAMES if switched else max(0, cooldown_left - 1)
    return best, new_cooldown


def _sample_faces_mediapipe(
    src: str, start: float, end: float, sample_fps: float
) -> tuple[tuple[FaceBox, ...], ...]:  # pragma: no cover - live path, lazy-imports mediapipe/cv2
    """Detect faces per sampled frame over ``src[start:end]`` (the live CPU boundary)."""
    import cv2  # noqa: PLC0415 — lazy: only the live render path needs OpenCV/MediaPipe
    import mediapipe as mp  # noqa: PLC0415
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision

    options = mp_vision.FaceDetectorOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(MODEL_PATH)),
        running_mode=mp_vision.RunningMode.VIDEO,
    )
    cap = cv2.VideoCapture(src)
    frames: list[tuple[FaceBox, ...]] = []
    try:
        with mp_vision.FaceDetector.create_from_options(options) as detector:
            step = 1.0 / sample_fps
            t = start
            while t < end:
                cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
                ok, frame = cap.read()
                if not ok:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = detector.detect_for_video(image, int(t * 1000.0))
                faces: list[FaceBox] = []
                for det in result.detections:
                    bb = det.bounding_box
                    score = det.categories[0].score if det.categories else 1.0
                    faces.append(
                        FaceBox(
                            x=float(bb.origin_x),
                            y=float(bb.origin_y),
                            w=float(bb.width),
                            h=float(bb.height),
                            score=float(score),
                        )
                    )
                frames.append(tuple(faces))
                t += step
    finally:
        cap.release()
    return tuple(frames)


def _probe_src_dims(src: str) -> tuple[int, int]:  # pragma: no cover - thin ffprobe boundary
    """Probe the source video's ``(width, height)`` via ffprobe (the live boundary)."""
    from ..video_asserts import probe_dimensions  # noqa: PLC0415

    return probe_dimensions(Path(src))


class SpeakerRegionSelector(Protocol):
    """The render pipeline's only contract for speaker tracking (Phase-3 drop-in seam)."""

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory: ...


class MediapipeSpeakerRegionSelector:
    """MVP CPU heuristic selector (the live, flag-off path)."""

    def __init__(
        self,
        *,
        _sample_faces: SampleFacesFn = _sample_faces_mediapipe,
        _probe_dims_fn: ProbeDimsFn = _probe_src_dims,
        sample_fps: float = SAMPLE_FPS,
    ) -> None:
        self._sample_faces = _sample_faces
        self._probe_dims_fn = _probe_dims_fn
        self._sample_fps = sample_fps

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory:
        """Sample faces → per-frame active-face pick → smoothed scene-aware trajectory."""
        src_w, src_h = self._probe_dims_fn(src)
        frames = self._sample_faces(src, start, end, self._sample_fps)
        cuts = [c - start for c in scene_cut_times if start <= c < end]

        samples: list[RawSample] = []
        prev_cx: float | None = None
        cooldown = 0
        for i, faces in enumerate(frames):
            t = i / self._sample_fps
            chosen, cooldown = select_active_face(faces, prev_cx, cooldown, src_w)
            cx = chosen.center_x if chosen is not None else None
            if chosen is not None:
                prev_cx = cx
            # Thread the FULL active-face box (not just its center) downstream so a
            # later zoom/size-aware crop can fit the head; Phase 0 only carries it.
            samples.append(RawSample(t=t, center_x=cx, face_count=len(faces), face=chosen))
        return build_trajectory(samples, cuts, src_w, src_h)


class GpuAsdSpeakerRegionSelector:
    """Phase-3 LR-ASD/TalkNet selector (Modal/Replicate). Intentionally inert in the MVP."""

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory:
        # PHASE3_GPU_ASD plug-point — flagged-not-called. Explicit raise (never assert),
        # so it survives ``python -O``. Asserted-False by test_asd_gpu_path_is_flagged_not_called.
        raise NotImplementedError("PHASE3: route to Modal/Replicate")
