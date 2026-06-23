"""Speaker-region selection for the vertical reframe (P2-2.4 render).

MVP CPU path: a PROVIDER SEAM detects faces per sampled frame — PRIMARY is YuNet
(``cv2.FaceDetectorYN``, OpenCV Zoo, MIT) which handles PROFILE/small faces well
and returns 5 landmarks; the FALLBACK is MediaPipe BlazeFace short-range (no
landmarks), mirroring the GigaAM→whisper pattern. Sampled at ``SAMPLE_FPS`` →
per-frame active-face pick that PREFERS a frontal (camera-facing) face over a
larger turned/profile head + stickiness + switch cooldown (anti ping-pong) →
:func:`smoothing.build_trajectory` (One-Euro center + asymmetric zoom + scene-cut
snap on PRECOMPUTED cut times passed as data — never a per-clip rescan). 2-3
co-present faces crop their UNION (everyone kept); when they can't share one 9:16
and NOBODY faces the camera we stay on the wider 2-shot rather than punch into a
profile; only a faceless / edge-of-frame / true-crowd sample falls back to GENERAL.

The GPU-precise path (LR-ASD / TalkNet on Modal/Replicate) is stubbed behind
``PHASE3_GPU_ASD`` and flagged-not-called. The render pipeline talks only to the
:class:`SpeakerRegionSelector` Protocol, so Phase 3 drops in without a refactor.

``_sample_faces_yunet`` / ``_sample_faces_mediapipe`` / ``_sample_faces_primary``
and ``_probe_src_dims`` are the impure boundaries (lazy-import cv2/onnx/mediapipe /
call ffprobe); all are injectable seams faked in unit tests so the suite runs 100%
offline (no real cv2/onnx in tests).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from .crop_geometry import CropTrajectory, FaceBox
from .frontality import Landmarks, is_frontal
from .smoothing import RawSample, build_trajectory

SAMPLE_FPS: float = 2.0
STICKINESS_BONUS: float = 3.0
STICKY_RADIUS_FRAC: float = 0.12
SWITCH_COOLDOWN_FRAMES: int = 8
# Score multiplier applied to a FRONTAL face (facing the camera) so it wins over a
# larger turned/profile head. Founder complaint 3: the crop punched into a person
# turned away. Tuned so a frontal face beats a profile up to this many× its area.
FRONTAL_BONUS: float = 4.0
MODEL_PATH: Path = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
# YuNet (cv2.FaceDetectorYN, OpenCV Zoo, MIT) ONNX model — the PRIMARY detector.
# Bundled in the wheel package-data and the worker image; never fetched at runtime.
YUNET_MODEL_PATH: Path = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
# YuNet inference knobs (OpenCV Zoo defaults): confidence/NMS thresholds + top-K.
YUNET_SCORE_THRESHOLD: float = 0.6
YUNET_NMS_THRESHOLD: float = 0.3
YUNET_TOP_K: int = 50

# Phase-3 plug-point. False = MVP CPU heuristic path (the only live path today).
PHASE3_GPU_ASD: bool = False

SampleFacesFn = Callable[[str, float, float, float], tuple[tuple[FaceBox, ...], ...]]
ProbeDimsFn = Callable[[str], tuple[int, int]]


def _frontal_candidates(faces: Sequence[FaceBox]) -> list[FaceBox]:
    """Faces facing the camera (frontality ≥ threshold), or ALL faces if none are.

    Founder complaint 3: with one head turned away, prefer the one FACING the
    camera even when it is smaller. When at least one face is frontal we discard the
    turned/profile heads from the candidate pool entirely; when NOBODY faces the
    camera (all profiles, or a landmark-less MediaPipe provider) the pool is
    unchanged so the legacy largest-face heuristic still applies.
    """
    frontal = [f for f in faces if is_frontal(f.frontality)]
    return frontal if frontal else list(faces)


def select_active_face(
    faces: Sequence[FaceBox],
    prev_center_x: float | None,
    cooldown_left: int,
    src_w: int,
) -> tuple[FaceBox | None, int]:
    """Pick the speaking face — frontal-first, then area × stickiness, with a cooldown.

    PURE. Returns ``(chosen | None, new_cooldown)``. With no faces, returns
    ``None`` and decays the cooldown. A FRONTAL face (facing the camera) is preferred
    over a larger turned/profile head: the candidate pool is first narrowed to frontal
    faces when any exist, and frontal faces additionally carry a score bonus so a
    near-tie resolves toward the one facing camera. While cooling down after a switch,
    it sticks to the (frontal) face nearest the previous center to avoid ping-ponging.
    """
    if not faces:
        return None, max(0, cooldown_left - 1)

    sticky_radius = STICKY_RADIUS_FRAC * src_w
    candidates = _frontal_candidates(faces)

    if prev_center_x is not None and cooldown_left > 0:
        nearest = min(candidates, key=lambda f: abs(f.center_x - prev_center_x))
        return nearest, cooldown_left - 1

    def _score(f: FaceBox) -> float:
        s = f.area
        if is_frontal(f.frontality):
            s *= FRONTAL_BONUS
        if prev_center_x is not None and abs(f.center_x - prev_center_x) < sticky_radius:
            s *= STICKINESS_BONUS
        return s

    best = max(candidates, key=_score)
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


def _landmarks_from_yunet_row(
    row: object,
) -> Landmarks:  # pragma: no cover - live cv2 numpy boundary
    """Extract YuNet's 5 landmark points (right-eye … left-mouth) from a detection row.

    A YuNet detection row is ``[x, y, w, h, re_x, re_y, le_x, le_y, nose_x, nose_y,
    rm_x, rm_y, lm_x, lm_y, score]``. The 5 landmark (x, y) pairs live at offset 4.
    """
    return tuple((float(row[4 + 2 * i]), float(row[4 + 2 * i + 1])) for i in range(5))  # type: ignore[index,return-value]


def _yunet_available() -> bool:  # pragma: no cover - live cv2 capability probe
    """True when the installed OpenCV exposes ``FaceDetectorYN`` and the ONNX is present."""
    import cv2  # noqa: PLC0415

    return hasattr(cv2, "FaceDetectorYN") and YUNET_MODEL_PATH.exists()


def _sample_faces_yunet(
    src: str, start: float, end: float, sample_fps: float
) -> tuple[tuple[FaceBox, ...], ...]:  # pragma: no cover - live path, lazy-imports cv2/onnx
    """Detect faces+landmarks per sampled frame (the PRIMARY profile-aware CPU boundary).

    YuNet (``cv2.FaceDetectorYN``) handles profile/small faces far better than
    BlazeFace and returns 5 landmarks per face, which :attr:`FaceBox.frontality`
    consumes. ``setInputSize`` is updated per frame from the decoded frame shape.
    """
    import cv2  # noqa: PLC0415 — lazy: only the live render path needs OpenCV

    detector = cv2.FaceDetectorYN.create(
        str(YUNET_MODEL_PATH),
        "",
        (0, 0),
        YUNET_SCORE_THRESHOLD,
        YUNET_NMS_THRESHOLD,
        YUNET_TOP_K,
    )
    cap = cv2.VideoCapture(src)
    frames: list[tuple[FaceBox, ...]] = []
    try:
        step = 1.0 / sample_fps
        t = start
        while t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            detector.setInputSize((w, h))
            _, dets = detector.detect(frame)
            faces: list[FaceBox] = []
            if dets is not None:
                for row in dets:
                    faces.append(
                        FaceBox(
                            x=float(row[0]),
                            y=float(row[1]),
                            w=float(row[2]),
                            h=float(row[3]),
                            score=float(row[14]),
                            landmarks=_landmarks_from_yunet_row(row),
                        )
                    )
            frames.append(tuple(faces))
            t += step
    finally:
        cap.release()
    return tuple(frames)


def _sample_faces_primary(
    src: str, start: float, end: float, sample_fps: float
) -> tuple[tuple[FaceBox, ...], ...]:  # pragma: no cover - live provider-seam dispatch
    """PRIMARY → fallback face sampling: YuNet when available, else MediaPipe BlazeFace.

    Mirrors the GigaAM→whisper provider seam: the better profile-aware detector is
    primary, the proven one is the fallback. YuNet is preferred whenever the OpenCV
    build exposes ``FaceDetectorYN`` and the ONNX model is bundled; otherwise we
    degrade to MediaPipe (no landmarks → frontality unknown → legacy heuristic).
    """
    if _yunet_available():
        return _sample_faces_yunet(src, start, end, sample_fps)
    return _sample_faces_mediapipe(src, start, end, sample_fps)


def _probe_src_dims(src: str) -> tuple[int, int]:  # pragma: no cover - thin ffprobe boundary
    """Probe the source video's ``(width, height)`` via ffprobe (the live boundary)."""
    from ..video_asserts import probe_dimensions  # noqa: PLC0415

    return probe_dimensions(Path(src))


class SpeakerRegionSelector(Protocol):
    """The render pipeline's only contract for speaker tracking (Phase-3 drop-in seam)."""

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory: ...


class HeuristicSpeakerRegionSelector:
    """MVP CPU heuristic selector (the live, flag-off path).

    Runs the YuNet→MediaPipe provider seam (:func:`_sample_faces_primary`) by
    default: profile-aware YuNet when available, MediaPipe BlazeFace as the fallback.
    """

    def __init__(
        self,
        *,
        _sample_faces: SampleFacesFn = _sample_faces_primary,
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
            # Thread the active face (for center stickiness) AND every co-present face
            # box downstream, so the smoother can fit the single head OR the union of
            # 2-3 co-present heads (multi-person kept, not center-cropped).
            samples.append(
                RawSample(
                    t=t,
                    center_x=cx,
                    face_count=len(faces),
                    face=chosen,
                    faces=tuple(faces),
                )
            )
        return build_trajectory(samples, cuts, src_w, src_h)


class GpuAsdSpeakerRegionSelector:
    """Phase-3 LR-ASD/TalkNet selector (Modal/Replicate). Intentionally inert in the MVP."""

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory:
        # PHASE3_GPU_ASD plug-point — flagged-not-called. Explicit raise (never assert),
        # so it survives ``python -O``. Asserted-False by test_asd_gpu_path_is_flagged_not_called.
        raise NotImplementedError("PHASE3: route to Modal/Replicate")


# Back-compat alias: the live heuristic selector used to be MediaPipe-only; it now
# runs the YuNet→MediaPipe seam. Callers (render.py) keep the historical name.
MediapipeSpeakerRegionSelector = HeuristicSpeakerRegionSelector
