"""Upstream LR-ASD ``evaluate_network`` adapter (DEPLOY-ONLY — GPU image only).

This is the ONE live-integration seam validated on first deploy. It wraps the stock
LR-ASD per-track scorer (``Columbia_test.evaluate_network`` in ``Junhua-Liao/LR-ASD``,
pinned at commit ``1b6dcd2d8fc2895683de6508ec6294ec47d388ca``): crop the per-frame face
video for one track, extract the synced 16 kHz MFCC audio, run the network's three
forward stages + ``lossAV.forward(out, labels=None)``, and return a per-(sampled-)frame
speaking score aligned to the track's frames.

It is intentionally kept OUT of the ``fliphouse_asd`` package (and thus out of the
100%-coverage gate) because it depends on torch/cv2/python_speech_features + the cloned
LR-ASD repo on PYTHONPATH, present only inside the Modal GPU image. Importing it in CI
fails by design; correctness is verified live via ``modal run modal_app.py`` against a
real clip, not by unit tests.

Why mirror upstream's preprocessing verbatim rather than reuse its on-disk pipeline:
the upstream ``crop_video``/``evaluate_network`` read frames/audio from a ``pycrop``
folder it writes itself, whereas we already hold the worker's per-frame face boxes and
the fetched window. We replicate the EXACT crop math (median-smoothed box, ``cropScale``
padding, 224-resize → 112 center-crop) and the EXACT network preprocessing (MFCC params,
``durationSet`` batching, the 100:25 audio:video frame ratio, the forward call order) so
the published weights see precisely the input distribution they were trained for.
"""

from __future__ import annotations

# Resolved ONLY in the GPU image (the LR-ASD repo is cloned to /opt/LR-ASD and put on
# PYTHONPATH by modal_app.gpu_image, which also installs torch/cv2/scipy/python_speech_
# features). Importing this in CI fails — by design.
import math
import os
import subprocess
import tempfile

import cv2  # type: ignore[import-not-found]
import numpy  # type: ignore[import-not-found]
import python_speech_features  # type: ignore[import-not-found]
import torch  # type: ignore[import-not-found]
from scipy import signal  # type: ignore[import-not-found]
from scipy.io import wavfile  # type: ignore[import-not-found]

# --- Upstream constants (verbatim from Columbia_test.py at the pinned commit) ----------
# The cropped face video LR-ASD consumes runs at 25 fps; MFCC runs at 100 frames/s, so
# every video frame pairs with exactly four MFCC frames. We preserve that 4:1 ratio when
# we feed the worker's sampled frames as the video sequence.
_AUDIO_HZ = 16000
_MFCC_NUMCEP = 13
_MFCC_WINLEN = 0.025
_MFCC_WINSTEP = 0.010
_MFCC_PER_VIDEO_FRAME = 4
_RESIZE = 224
_CROP = 112
# crop_video: pad bbox by ``cropScale`` and median-smooth box geometry over time.
_CROP_SCALE = 0.40
_MEDFILT_KERNEL = 13
_PAD_CONSTANT = 110
# evaluate_network: average the per-frame score over this duration set for robustness.
_DURATION_SET = (1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6)
_SCORE_ROUND_DECIMALS = 1
# Upstream batches the 25 fps crop in windows of ``duration`` seconds (= duration * 25
# video frames). We reuse 25 as the video-frames-per-duration-unit so each window matches
# the temporal extent the weights were trained on.
_FRAMES_PER_DURATION_UNIT = 25


def _device() -> str:
    """``"cuda"`` on the GPU container, else ``"cpu"`` (lets the selftest run host-side)."""
    return "cuda" if torch.cuda.is_available() else "cpu"


def _decode_frames(clip_path: str) -> tuple[list, float]:
    """Decode every frame of the fetched window into a list of BGR arrays + the fps."""
    cap = cv2.VideoCapture(clip_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames: list = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    return frames, fps


def _source_frame_index(sample_idx: int, clip_fps: float, sample_fps: float) -> int:
    """Map a track sampled-frame index back to its decoded-frame index in the window."""
    return int(round(sample_idx * (clip_fps / sample_fps)))


def _smoothed_geometry(boxes: list[dict]) -> dict:
    """Median-smooth per-frame box center (x, y) and half-size (s) — upstream crop math."""
    sizes = numpy.array([max(b["x1"] - b["x0"], b["y1"] - b["y0"]) / 2 for b in boxes])
    cxs = numpy.array([(b["x0"] + b["x1"]) / 2 for b in boxes])
    cys = numpy.array([(b["y0"] + b["y1"]) / 2 for b in boxes])
    return {
        "s": signal.medfilt(sizes, kernel_size=_MEDFILT_KERNEL),
        "x": signal.medfilt(cxs, kernel_size=_MEDFILT_KERNEL),
        "y": signal.medfilt(cys, kernel_size=_MEDFILT_KERNEL),
    }


def _crop_face(image, cx: float, cy: float, half: float):
    """Pad + crop one face exactly as upstream ``crop_video`` does (cropScale padding)."""
    pad = int(half * (1 + 2 * _CROP_SCALE))
    padded = numpy.pad(
        image,
        ((pad, pad), (pad, pad), (0, 0)),
        "constant",
        constant_values=(_PAD_CONSTANT, _PAD_CONSTANT),
    )
    my = cy + pad
    mx = cx + pad
    face = padded[
        int(my - half) : int(my + half * (1 + 2 * _CROP_SCALE)),
        int(mx - half * (1 + _CROP_SCALE)) : int(mx + half * (1 + _CROP_SCALE)),
    ]
    return cv2.resize(face, (_RESIZE, _RESIZE))


def _video_feature(clip_path: str, track: dict, sample_fps: float) -> numpy.ndarray:
    """Build the LR-ASD video tensor source: one 112x112 grayscale crop per track frame."""
    decoded, clip_fps = _decode_frames(clip_path)
    frame_indices = sorted(track["frames"])
    boxes = [track["frames"][i] for i in frame_indices]
    geom = _smoothed_geometry(boxes)
    crops: list = []
    half_window = _RESIZE // 2
    crop_lo = half_window - _CROP // 2
    crop_hi = half_window + _CROP // 2
    for n, sample_idx in enumerate(frame_indices):
        src = _source_frame_index(sample_idx, clip_fps, sample_fps)
        src = min(max(src, 0), len(decoded) - 1)
        resized = _crop_face(decoded[src], geom["x"][n], geom["y"][n], geom["s"][n])
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        crops.append(gray[crop_lo:crop_hi, crop_lo:crop_hi])
    return numpy.array(crops)


def _extract_audio_wav(clip_path: str, start: float, end: float, dst: str) -> None:
    """Extract mono 16 kHz PCM audio for the track's time span (upstream ffmpeg recipe)."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            clip_path,
            "-ac",
            "1",
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(_AUDIO_HZ),
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            dst,
        ],
        check=True,
        capture_output=True,
    )


def _audio_feature(clip_path: str, track: dict, sample_fps: float) -> numpy.ndarray:
    """MFCC for the track's time span, keyed to the SAMPLED video fps (100:25 ratio held).

    Upstream couples 100 MFCC frames to 25 video frames. We resample the dense (100 Hz)
    MFCC to ``_MFCC_PER_VIDEO_FRAME`` rows per SAMPLED video frame so the same 4:1 ratio
    holds for the worker's ``sample_fps`` cadence the network is fed here.
    """
    frame_indices = sorted(track["frames"])
    span_start = frame_indices[0] / sample_fps
    span_end = (frame_indices[-1] + 1) / sample_fps
    with tempfile.TemporaryDirectory(prefix="asd-aud-") as tmp:
        wav_path = os.path.join(tmp, "track.wav")
        _extract_audio_wav(clip_path, span_start, span_end, wav_path)
        _, audio = wavfile.read(wav_path)
    dense = python_speech_features.mfcc(
        audio,
        _AUDIO_HZ,
        numcep=_MFCC_NUMCEP,
        winlen=_MFCC_WINLEN,
        winstep=_MFCC_WINSTEP,
    )
    target_rows = len(frame_indices) * _MFCC_PER_VIDEO_FRAME
    if dense.shape[0] == 0:
        return numpy.zeros((target_rows, _MFCC_NUMCEP), dtype=dense.dtype)
    idx = numpy.linspace(0, dense.shape[0] - 1, num=target_rows).round().astype(int)
    return dense[idx, :]


def _forward_scores(audio_feat: numpy.ndarray, video_feat: numpy.ndarray, net) -> list[float]:
    """Run the network over ``_DURATION_SET`` and average → one score per video frame.

    Mirrors ``Columbia_test.evaluate_network`` semantics: trim audio/video to a common
    frame length holding the ``_MFCC_PER_VIDEO_FRAME`` (4:1) ratio, batch the sequence
    into windows, call the three forward stages, then ``lossAV.forward(out, labels=None)``
    (which returns one speaking score per video frame). Upstream measures the duration
    window in 25 fps "seconds"; here the video sequence is the worker's SAMPLED frames,
    so a window is ``duration * _FRAMES_PER_DURATION_UNIT`` sampled frames, paired with
    four MFCC rows each — the same temporal coupling the weights were trained under.
    """
    length = min(audio_feat.shape[0] // _MFCC_PER_VIDEO_FRAME, video_feat.shape[0])
    if length <= 0:
        return [0.0] * video_feat.shape[0]
    audio_feat = audio_feat[: length * _MFCC_PER_VIDEO_FRAME, :]
    video_feat = video_feat[:length, :, :]
    device = _device()
    all_scores: list = []
    for duration in _DURATION_SET:
        window = duration * _FRAMES_PER_DURATION_UNIT
        batch = int(math.ceil(length / window))
        scores: list = []
        with torch.no_grad():
            for i in range(batch):
                v_lo, v_hi = i * window, (i + 1) * window
                a_lo = v_lo * _MFCC_PER_VIDEO_FRAME
                a_hi = v_hi * _MFCC_PER_VIDEO_FRAME
                input_a = torch.FloatTensor(audio_feat[a_lo:a_hi, :]).unsqueeze(0).to(device)
                input_v = torch.FloatTensor(video_feat[v_lo:v_hi, :, :]).unsqueeze(0).to(device)
                embed_a = net.model.forward_audio_frontend(input_a)
                embed_v = net.model.forward_visual_frontend(input_v)
                out = net.model.forward_audio_visual_backend(embed_a, embed_v)
                score = net.lossAV.forward(out, labels=None)
                scores.extend(score)
        all_scores.append(scores)
    averaged = numpy.round(
        numpy.mean(numpy.array(all_scores), axis=0), _SCORE_ROUND_DECIMALS
    ).astype(float)
    return [float(s) for s in averaged]


def _pad_to_track(scores: list[float], track: dict) -> list[float]:
    """Pad/truncate the per-frame scores to exactly one value per track frame."""
    want = len(track["frames"])
    if len(scores) >= want:
        return scores[:want]
    return scores + [0.0] * (want - len(scores))


def evaluate_track(clip_path: str, track: dict, net) -> list[float]:
    """Return the per-sampled-frame speaking score for one face ``track``.

    DEPLOY-ONLY. Bridges our track dict (``{"frames": {sample_idx: box}, ...}``) to the
    upstream LR-ASD scorer: build the 112x112 face-crop sequence + synced MFCC for the
    track, run the network over ``_DURATION_SET``, and return one score per track frame
    (sorted-frame-index order) so ``lr_asd_runner._score_tracks`` can zip it back on.
    A track too short to crop returns all-silent scores rather than raising — the worker
    fails OPEN on any non-2xx, so a real grid of zeros is safer than a 500 for a thin
    track inside an otherwise-scorable window.
    """
    frame_indices = sorted(track["frames"])
    if not frame_indices:
        return []
    sample_fps = track.get("sample_fps")
    if sample_fps is None or sample_fps <= 0:
        raise ValueError("track is missing a positive sample_fps for audio sync")
    video_feat = _video_feature(clip_path, track, sample_fps)
    if video_feat.shape[0] == 0:
        return [0.0] * len(frame_indices)
    audio_feat = _audio_feature(clip_path, track, sample_fps)
    scores = _forward_scores(audio_feat, video_feat, net)
    return _pad_to_track(scores, track)
