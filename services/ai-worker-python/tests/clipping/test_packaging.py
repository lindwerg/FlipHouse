"""Meta-test: the clipping package must be declared so `pip install .` ships it.

Without this, `from ..clipping import ...` (in engine/scoring_fanout.py) raises
ModuleNotFoundError on the Railway build, where the source tree is installed, not
run in place.
"""

import tomllib
from pathlib import Path

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_clipping_package_declared():
    packages = _pyproject()["tool"]["setuptools"]["packages"]
    assert "fliphouse_worker.clipping" in packages


def test_reframe_extra_declared():
    extras = _pyproject()["project"]["optional-dependencies"]
    assert "reframe" in extras
    assert any("mediapipe" in dep for dep in extras["reframe"])


def test_blazeface_model_shipped_as_package_data():
    pkg_data = _pyproject()["tool"]["setuptools"]["package-data"]
    assert "models/*.tflite" in pkg_data["fliphouse_worker.clipping"]


def test_vendored_blazeface_model_present():
    model = (
        Path(__file__).resolve().parents[2]
        / "fliphouse_worker"
        / "clipping"
        / "models"
        / "blaze_face_short_range.tflite"
    )
    assert model.is_file() and model.stat().st_size > 0


def test_render_public_api_imports_clean():
    from fliphouse_worker.clipping import (  # noqa: F401
        PHASE3_GPU_ASD,
        CaptionBand,
        ClipEntry,
        RenderManifest,
        RenderSegment,
        assert_render_codecs,
        build_render_segments,
        compute_crop_box,
        detect_caption_band,
        render_vertical_clips,
    )


def test_clipping_import_has_no_engine_cycle():
    # render.py imports SelectedClip only under TYPE_CHECKING; both packages must
    # import cleanly in either order without a circular-import error.
    import fliphouse_worker.clipping  # noqa: F401
    from fliphouse_worker.engine import cascade  # noqa: F401

    assert hasattr(cascade, "select_clips")
