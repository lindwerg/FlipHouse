"""WebM scoring clips + LGPL-clean vertical delivery render (P2-S6, P2-2.4)."""

from .caption_band import CaptionBand, detect_caption_band, detect_clip_caption_band
from .crop_geometry import (
    CropBox,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    compute_crop_box,
)
from .cutter import (
    CLIP_VIDEO_MIME,
    DEFAULT_FINALIST_PRESET,
    SAFE_FINALIST_PRESET,
    ClipTooLargeError,
    FinalistPreset,
    cut_clip,
)
from .manifest import ClipEntry, RenderManifest
from .preflight import assert_clip_codecs
from .render import render_vertical_clips
from .render_preflight import assert_render_codecs, assert_startup_codecs
from .segments import RenderSegment, build_render_segments
from .speaker_region import (
    PHASE3_GPU_ASD,
    GpuAsdSpeakerRegionSelector,
    HeuristicSpeakerRegionSelector,
    MediapipeSpeakerRegionSelector,
    SpeakerRegionSelector,
    build_speaker_region_selector,
)

__all__ = [
    "CLIP_VIDEO_MIME",
    "DEFAULT_FINALIST_PRESET",
    "PHASE3_GPU_ASD",
    "SAFE_FINALIST_PRESET",
    "CaptionBand",
    "ClipEntry",
    "ClipTooLargeError",
    "CropBox",
    "FinalistPreset",
    "CropKeyframe",
    "CropTrajectory",
    "FaceBox",
    "GpuAsdSpeakerRegionSelector",
    "HeuristicSpeakerRegionSelector",
    "MediapipeSpeakerRegionSelector",
    "RenderManifest",
    "RenderSegment",
    "SpeakerRegionSelector",
    "assert_clip_codecs",
    "assert_render_codecs",
    "assert_startup_codecs",
    "build_render_segments",
    "build_speaker_region_selector",
    "compute_crop_box",
    "cut_clip",
    "detect_caption_band",
    "detect_clip_caption_band",
    "render_vertical_clips",
]
