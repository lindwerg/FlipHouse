"""WebM scoring clips + LGPL-clean vertical delivery render (P2-S6, P2-2.4)."""

from .crop_geometry import (
    CropBox,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    compute_crop_box,
)
from .cutter import CLIP_VIDEO_MIME, ClipTooLargeError, cut_clip
from .manifest import ClipEntry, RenderManifest
from .preflight import assert_clip_codecs
from .render import render_vertical_clips
from .render_preflight import assert_render_codecs
from .speaker_region import (
    PHASE3_GPU_ASD,
    GpuAsdSpeakerRegionSelector,
    MediapipeSpeakerRegionSelector,
    SpeakerRegionSelector,
)

__all__ = [
    "CLIP_VIDEO_MIME",
    "PHASE3_GPU_ASD",
    "ClipEntry",
    "ClipTooLargeError",
    "CropBox",
    "CropKeyframe",
    "CropTrajectory",
    "FaceBox",
    "GpuAsdSpeakerRegionSelector",
    "MediapipeSpeakerRegionSelector",
    "RenderManifest",
    "SpeakerRegionSelector",
    "assert_clip_codecs",
    "assert_render_codecs",
    "compute_crop_box",
    "cut_clip",
    "render_vertical_clips",
]
