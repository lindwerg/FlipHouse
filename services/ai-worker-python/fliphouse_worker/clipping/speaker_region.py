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

The GPU-precise path (LR-ASD, Junhua-Liao/LR-ASD, MIT, bundled weights — NO
pyannote) is now LIVE behind :class:`GpuAsdSpeakerRegionSelector`, selected by env
via :func:`build_speaker_region_selector` (``GPU_ASD_ENABLED`` +
``GPU_ASD_ENDPOINT`` + ``GPU_ASD_SECRET``). It runs the SAME CPU face detection,
then asks the gpu-asd Modal endpoint for a per-frame per-face SPEAKING score and
follows whoever TALKS — overriding frontal-largest so the only-profiles /
who-to-follow case picks the speaker, not a larger silent/turned head. It fails
OPEN to the CPU heuristic on any transport error. The render pipeline talks only to
the :class:`SpeakerRegionSelector` Protocol, so the lane swaps in without a refactor.

``_sample_faces_yunet`` / ``_sample_faces_mediapipe`` / ``_sample_faces_primary``
and ``_probe_src_dims`` are the impure boundaries (lazy-import cv2/onnx/mediapipe /
call ffprobe); all are injectable seams faked in unit tests so the suite runs 100%
offline (no real cv2/onnx in tests).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from .active_speaker import (
    SPEAKING_THRESHOLD as SPEAKING_BONUS_THRESHOLD,
)
from .active_speaker import (
    has_speaking_signal,
    speaking_candidates,
)
from .asd_config import AsdConfig, load_asd_config
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
# Score multiplier applied to an ASD-confirmed SPEAKER (REFRAME Phase 4). Set ABOVE
# FRONTAL_BONUS so a talking face outranks a larger frontal/silent head on a near-tie:
# active-speech is the strongest subject signal when the GPU lane supplies it.
SPEAKING_BONUS: float = 8.0
MODEL_PATH: Path = Path(__file__).parent / "models" / "blaze_face_short_range.tflite"
# YuNet (cv2.FaceDetectorYN, OpenCV Zoo, MIT) ONNX model — the PRIMARY detector.
# Bundled in the wheel package-data and the worker image; never fetched at runtime.
YUNET_MODEL_PATH: Path = Path(__file__).parent / "models" / "face_detection_yunet_2023mar.onnx"
# YuNet inference knobs (OpenCV Zoo defaults): confidence/NMS thresholds + top-K.
YUNET_SCORE_THRESHOLD: float = 0.6
YUNET_NMS_THRESHOLD: float = 0.3
YUNET_TOP_K: int = 50

# Retired Phase-3 plug-point marker, kept False for back-compat exports. The GPU ASD
# lane is now env-selected at runtime (``GPU_ASD_ENABLED``), not a module constant;
# this stays False so callers that branched on "stub not live" keep the CPU default.
PHASE3_GPU_ASD: bool = False

SampleFacesFn = Callable[[str, float, float, float], tuple[tuple[FaceBox, ...], ...]]
ProbeDimsFn = Callable[[str], tuple[int, int]]


def _candidate_pool(faces: Sequence[FaceBox]) -> list[FaceBox]:
    """The faces eligible to win the active-face pick — ASD-speaking-first, else frontal.

    Priority (REFRAME Phase 4): when the GPU LR-ASD lane scored this frame AND at
    least one face is SPEAKING, the pool is narrowed to the talking faces — the crop
    follows whoever talks, OVERRIDING frontal-largest (this resolves the only-profiles
    / silent-bigger-head case the CPU heuristic cannot). Absent any speaker signal we
    fall through to the proven CPU rule: prefer frontal faces, or all faces when none
    face the camera (or a landmark-less provider gives no frontality).
    """
    if has_speaking_signal(faces):
        talking = speaking_candidates(faces)
        if talking:
            return talking
    return _frontal_candidates(faces)


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
    candidates = _candidate_pool(faces)

    if prev_center_x is not None and cooldown_left > 0:
        nearest = min(candidates, key=lambda f: abs(f.center_x - prev_center_x))
        return nearest, cooldown_left - 1

    def _score(f: FaceBox) -> float:
        s = f.area
        # An ASD-confirmed speaker outranks a larger frontal/silent head: the bonus is
        # set above FRONTAL_BONUS so a talking face beats a bigger frontal one on a
        # near-tie, mirroring how FRONTAL_BONUS lets a frontal face beat a bigger profile.
        if f.speaking is not None and f.speaking >= SPEAKING_BONUS_THRESHOLD:
            s *= SPEAKING_BONUS
        elif is_frontal(f.frontality):
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
        return _trajectory_from_frames(frames, cuts, src_w, src_h, self._sample_fps)


def _trajectory_from_frames(
    frames: tuple[tuple[FaceBox, ...], ...],
    cuts: Sequence[float],
    src_w: int,
    src_h: int,
    sample_fps: float,
) -> CropTrajectory:
    """Shared per-frame active-face pick → smoothed trajectory (CPU + GPU-ASD lanes).

    PURE over already-sampled ``frames`` (each a tuple of per-frame faces, optionally
    ASD-enriched with :attr:`FaceBox.speaking`). Both selectors funnel through here so
    the stickiness/cooldown/union logic is identical whether the speaking signal came
    from the GPU lane or not — the ASD override lives inside ``select_active_face`` /
    ``_resolve_subject``, not in a forked loop.
    """
    samples: list[RawSample] = []
    prev_cx: float | None = None
    cooldown = 0
    for i, faces in enumerate(frames):
        t = i / sample_fps
        chosen, cooldown = select_active_face(faces, prev_cx, cooldown, src_w)
        cx = chosen.center_x if chosen is not None else None
        if chosen is not None:
            prev_cx = cx
        # Thread the active face (for center stickiness) AND every co-present face box
        # downstream, so the smoother can fit the single head OR the union of 2-3
        # co-present heads (multi-person kept, not center-cropped).
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


# ── REFRAME Phase 4: GPU active-speaker (LR-ASD) lane ─────────────────────────
# The transport boundary: given the source, the clip window, and the CPU-sampled
# face boxes per frame, return a per-frame per-face SPEAKING score in [0, 1]. The
# returned shape MUST mirror ``frames`` (one inner tuple per frame, one float per
# face in that frame). This is the ONLY impure ASD boundary; the live impl POSTs a
# signed request to the gpu-asd Modal app, and the unit suite injects a fake.
AsdTransport = Callable[
    [str, float, float, tuple[tuple[FaceBox, ...], ...]],
    tuple[tuple[float, ...], ...],
]


def _scores_match_frames(
    frames: tuple[tuple[FaceBox, ...], ...], scores: tuple[tuple[float, ...], ...]
) -> bool:
    """True when ``scores`` has exactly one float per face per frame (shape mirrors frames)."""
    if len(scores) != len(frames):
        return False
    return all(len(row) == len(faces) for row, faces in zip(scores, frames, strict=True))


def _enrich_with_speaking(
    frames: tuple[tuple[FaceBox, ...], ...], scores: tuple[tuple[float, ...], ...]
) -> tuple[tuple[FaceBox, ...], ...]:
    """Return ``frames`` with each face's :attr:`FaceBox.speaking` set from ``scores``.

    IMMUTABLE: builds new :class:`FaceBox` values (the originals are frozen). The
    speaking score is clamped to ``[0, 1]`` so a noisy endpoint value can never warp
    the downstream threshold comparison.
    """
    return tuple(
        tuple(
            FaceBox(
                x=f.x,
                y=f.y,
                w=f.w,
                h=f.h,
                score=f.score,
                landmarks=f.landmarks,
                speaking=min(1.0, max(0.0, float(s))),
            )
            for f, s in zip(faces, row, strict=True)
        )
        for faces, row in zip(frames, scores, strict=True)
    )


class GpuAsdSpeakerRegionSelector:
    """REFRAME Phase 4 active-speaker selector — LR-ASD (Junhua-Liao/LR-ASD, MIT) lane.

    Fixes the profile / who-to-follow case: follow whoever is SPEAKING, not a larger
    silent/turned head. It runs the SAME CPU face detection as the heuristic selector
    (boxes + landmarks), then calls the gpu-asd endpoint via an injected transport for
    a per-frame per-face SPEAKING score, attaches it to each face, and lets the shared
    active-face logic pick the talker (overriding frontal-largest when ASD resolves).

    FAIL-OPEN to the CPU path: if the transport raises, returns a malformed shape, or
    yields no usable signal, the selector falls back to the heuristic selector so a GPU
    hiccup never breaks a paid render. The network boundary is the only impure seam;
    the unit suite drives it with a fake transport (no real network/GPU).
    """

    def __init__(
        self,
        *,
        asd_transport: AsdTransport,
        _sample_faces: SampleFacesFn = _sample_faces_primary,
        _probe_dims_fn: ProbeDimsFn = _probe_src_dims,
        sample_fps: float = SAMPLE_FPS,
        _fallback: SpeakerRegionSelector | None = None,
    ) -> None:
        self._asd_transport = asd_transport
        self._sample_faces = _sample_faces
        self._probe_dims_fn = _probe_dims_fn
        self._sample_fps = sample_fps
        self._fallback = _fallback or HeuristicSpeakerRegionSelector(
            _sample_faces=_sample_faces,
            _probe_dims_fn=_probe_dims_fn,
            sample_fps=sample_fps,
        )

    def select_speaker_region(
        self, src: str, start: float, end: float, scene_cut_times: Sequence[float]
    ) -> CropTrajectory:
        """Sample faces → GPU LR-ASD speaking scores → speaker-tracked trajectory.

        Fail-open: any transport error or shape mismatch falls back to the CPU
        heuristic selector (which re-samples faces and tracks frontal-largest).
        """
        src_w, src_h = self._probe_dims_fn(src)
        frames = self._sample_faces(src, start, end, self._sample_fps)
        try:
            scores = self._asd_transport(src, start, end, frames)
        except Exception:  # noqa: BLE001 - a GPU/network fault must never break the render
            return self._fallback.select_speaker_region(src, start, end, scene_cut_times)
        if not _scores_match_frames(frames, scores):
            return self._fallback.select_speaker_region(src, start, end, scene_cut_times)
        enriched = _enrich_with_speaking(frames, scores)
        cuts = [c - start for c in scene_cut_times if start <= c < end]
        return _trajectory_from_frames(enriched, cuts, src_w, src_h, self._sample_fps)


def _live_asd_transport(config: AsdConfig) -> AsdTransport:  # pragma: no cover - real network
    """Build the production ASD transport: a signed POST to the gpu-asd Modal app.

    Founder-gated live path — pulls httpx and hits the real GPU endpoint, so it is
    never exercised in CI (the unit suite injects a fake ``AsdTransport``). It mirrors
    the GigaAM webhook signing exactly: ``sha256=hex(hmacSHA256(secret, ts.body))``.
    """
    import hashlib  # noqa: PLC0415
    import hmac  # noqa: PLC0415
    import json  # noqa: PLC0415
    import time  # noqa: PLC0415

    import httpx  # type: ignore[import-not-found]  # noqa: PLC0415

    def transport(
        src: str,
        start: float,
        end: float,
        frames: tuple[tuple[FaceBox, ...], ...],
    ) -> tuple[tuple[float, ...], ...]:
        body = json.dumps(
            {
                "proxy_url": src,
                "start": start,
                "end": end,
                "sample_fps": SAMPLE_FPS,
                "frames": [
                    [{"x": f.x, "y": f.y, "w": f.w, "h": f.h} for f in faces] for faces in frames
                ],
            }
        ).encode("utf-8")
        ts = str(int(time.time()))
        sig = hmac.new(
            config.secret.encode("utf-8"), ts.encode("utf-8") + b"." + body, hashlib.sha256
        ).hexdigest()
        resp = httpx.post(
            config.endpoint.rstrip("/") + "/score",
            content=body,
            headers={
                "content-type": "application/json",
                "x-fliphouse-signature": f"sha256={sig}",
                "x-fliphouse-timestamp": ts,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        scores = resp.json()["scores"]
        return tuple(tuple(float(s) for s in row) for row in scores)

    return transport


def build_speaker_region_selector(
    env: object | None = None,
    *,
    _transport_factory: Callable[[AsdConfig], AsdTransport] = _live_asd_transport,
) -> SpeakerRegionSelector:
    """Pick the selector from env: GPU LR-ASD when enabled+configured, else CPU heuristic.

    The ONE wiring seam ``render.py`` should call instead of hard-coding a selector.
    When ``GPU_ASD_ENABLED`` is truthy AND the endpoint+secret are present
    (:func:`asd_config.load_asd_config`), it returns the
    :class:`GpuAsdSpeakerRegionSelector` wired to the live signed transport; otherwise
    it returns the proven :class:`HeuristicSpeakerRegionSelector` and never touches the
    network. ``_transport_factory`` is injected so the unit suite asserts the enabled
    branch with a FAKE transport (no httpx, no GPU).
    """
    config = load_asd_config(env)  # type: ignore[arg-type]
    if not config.enabled:
        return HeuristicSpeakerRegionSelector()
    return GpuAsdSpeakerRegionSelector(asd_transport=_transport_factory(config))


# Back-compat alias: the live heuristic selector used to be MediaPipe-only; it now
# runs the YuNet→MediaPipe seam. Callers (render.py) keep the historical name.
MediapipeSpeakerRegionSelector = HeuristicSpeakerRegionSelector
