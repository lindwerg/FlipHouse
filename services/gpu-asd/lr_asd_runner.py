"""LR-ASD inference runner (DEPLOY-ONLY — runs on the Modal GPU, never in CI).

Lives at the service root (not inside ``fliphouse_asd``) so the package's
100%-coverage gate never measures it: it imports torch/cv2/scenedetect/LR-ASD, all
present only in the GPU image. ``modal_app.Scorer`` calls :func:`score_window`.

The heavy lifting reuses the stock LR-ASD ``Columbia_test`` preprocessing (S3FD
detect → IOU track → 224x224 crop → MFCC) and ``evaluate_network`` scorer; this
module's job is the GLUE: drive that pipeline over a fetched clip window, then
PROJECT the per-track per-frame LR-ASD scores back onto the WORKER's per-(frame,
face) boxes — so the returned grid mirrors the worker's ``frames`` shape exactly and
each score lands on the right face.

Kept deliberately small and free of clever abstractions; correctness of the score
projection (IOU + frame-index match) is what matters, and it is verified live via
``modal run modal_app.py`` against a real clip, not by unit tests.
"""

from __future__ import annotations

import os
import tempfile

# These imports resolve ONLY inside the GPU image (torch/cv2 + the cloned LR-ASD repo
# on PYTHONPATH). Importing this module in CI would fail — which is why it is never
# collected by the package's pytest gate.
import cv2  # type: ignore[import-not-found]
import numpy  # type: ignore[import-not-found]

# IOU below which a worker box is considered "not this LR-ASD track" → score 0.0.
_MATCH_IOU = 0.3
# Default speaking score for a worker face that no LR-ASD track covers (silent/unknown).
_DEFAULT_SCORE = 0.0


def _detect_and_track(clip_path: str, detector, sample_fps: float):
    """Run S3FD per decoded frame and IOU-track into face tracks (stock LR-ASD logic).

    Returns a list of tracks; each track is ``{"frames": {frame_idx: box}, ...}`` where
    ``box`` is ``{"x0","y0","x1","y1"}`` in source pixels. Sampling at ``sample_fps``
    aligns the LR-ASD frame indices with the worker's sampled frames.
    """
    cap = cv2.VideoCapture(clip_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, int(round(fps / sample_fps)))
    tracks: list[dict] = []
    frame_idx = 0
    sample_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_idx % step == 0:
            boxes = detector.detect_faces(frame, conf_th=0.9, scales=[0.25])
            _assign_to_tracks(tracks, boxes, sample_idx)
            sample_idx += 1
        frame_idx += 1
    cap.release()
    return tracks


def _assign_to_tracks(tracks: list[dict], boxes, sample_idx: int) -> None:
    """Greedily extend existing tracks by IOU, else open a new track (per-frame)."""
    for box in boxes:
        x0, y0, x1, y1, _conf = box[:5]
        cand = {"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}
        best = None
        best_iou = _MATCH_IOU
        for track in tracks:
            last_idx = max(track["frames"])
            if sample_idx - last_idx > 10:
                continue
            iou = _box_iou(track["frames"][last_idx], cand)
            if iou > best_iou:
                best, best_iou = track, iou
        if best is None:
            tracks.append({"frames": {sample_idx: cand}})
        else:
            best["frames"][sample_idx] = cand


def _box_iou(a: dict, b: dict) -> float:
    ix0, iy0 = max(a["x0"], b["x0"]), max(a["y0"], b["y0"])
    ix1, iy1 = min(a["x1"], b["x1"]), min(a["y1"], b["y1"])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = (
        (a["x1"] - a["x0"]) * (a["y1"] - a["y0"])
        + (b["x1"] - b["x0"]) * (b["y1"] - b["y0"])
        - inter
    )
    return inter / union if union > 0 else 0.0


def _score_tracks(clip_path: str, tracks: list[dict], net) -> dict:
    """Run LR-ASD ``evaluate_network`` per track → ``{track_index: {frame_idx: score}}``.

    Thin wrapper over the stock LR-ASD scorer; the per-track score list is aligned back
    to the track's sampled frame indices. The crop/MFCC details follow the upstream
    ``Columbia_test`` preprocessing exactly (kept verbatim there to preserve accuracy).
    """
    import lr_asd_eval  # bundled helper that calls the upstream evaluate_network

    out: dict[int, dict[int, float]] = {}
    for ti, track in enumerate(tracks):
        frame_indices = sorted(track["frames"])
        scores = lr_asd_eval.evaluate_track(clip_path, track, net)
        out[ti] = {fi: float(s) for fi, s in zip(frame_indices, scores, strict=False)}
    return out


def _project_scores(req, tracks: list[dict], track_scores: dict, iou_fn) -> list[list[float]]:
    """Map per-track LR-ASD scores onto the worker's per-(frame, face) boxes by IOU."""
    grid: list[list[float]] = []
    for fi, frame in enumerate(req.frames):
        row: list[float] = []
        for box in frame:
            row.append(_score_for_box(fi, box, tracks, track_scores, iou_fn))
        grid.append(row)
    return grid


def _score_for_box(fi: int, box, tracks: list[dict], track_scores: dict, iou_fn) -> float:
    """Best-IOU LR-ASD track score for one worker box at sampled frame ``fi``."""
    best_score = _DEFAULT_SCORE
    best_iou = _MATCH_IOU
    for ti, track in enumerate(tracks):
        if fi not in track["frames"]:
            continue
        iou = iou_fn(track["frames"][fi], box)
        if iou > best_iou and fi in track_scores.get(ti, {}):
            best_iou = iou
            best_score = track_scores[ti][fi]
    return best_score


def score_window(req, net, detector, fetch_fn, iou_fn) -> list[list[float]]:
    """Fetch the clip window, run S3FD+LR-ASD, project scores onto the worker boxes."""
    with tempfile.TemporaryDirectory(prefix="asd-") as tmp:
        clip_path = os.path.join(tmp, "window.mp4")
        fetch_fn(req.proxy_url, req.start, req.end, clip_path)
        tracks = _detect_and_track(clip_path, detector, req.sample_fps)
        track_scores = _score_tracks(clip_path, tracks, net)
        return _project_scores(req, tracks, track_scores, iou_fn)


# Silence "imported but unused" for numpy — kept as an explicit GPU-image dep marker
# (the stock LR-ASD crop/MFCC path uses it; re-exported so the import is load-bearing).
_NUMPY = numpy
