"""render_preflight — libopenh264 + aac presence gate, fail-closed on absence."""

import pytest

from fliphouse_worker.clipping.render_preflight import (
    assert_render_codecs,
    assert_startup_codecs,
)


def test_passes_when_required_encoders_present():
    listing = "V..... libopenh264 ...\nA..... aac ...\n"
    assert_render_codecs(_run_fn=lambda: listing)  # no raise = pass


def test_raises_on_missing_libopenh264():
    listing = "V..... libx264 ...\nA..... aac ...\n"  # GPL build, no openh264
    with pytest.raises(RuntimeError, match="libopenh264"):
        assert_render_codecs(_run_fn=lambda: listing)


def test_raises_on_missing_aac():
    listing = "V..... libopenh264 ...\n"
    with pytest.raises(RuntimeError, match="aac"):
        assert_render_codecs(_run_fn=lambda: listing)


def test_startup_runs_finalist_then_delivery_when_both_pass():
    calls = []
    assert_startup_codecs(
        _finalist_fn=lambda: calls.append("finalist"),
        _delivery_fn=lambda: calls.append("delivery"),
    )
    assert calls == ["finalist", "delivery"]  # finalist asserted first, both ran


def test_startup_propagates_finalist_failure_before_delivery():
    """A libvpx-less image (finalist leg raises) fails boot without reaching delivery."""

    def _boom():
        raise RuntimeError("ffmpeg missing required encoders: ['libvpx-vp9']")

    delivery_ran = []
    with pytest.raises(RuntimeError, match="libvpx-vp9"):
        assert_startup_codecs(
            _finalist_fn=_boom,
            _delivery_fn=lambda: delivery_ran.append(True),
        )
    assert delivery_ran == []  # short-circuited before the delivery check


def test_startup_propagates_delivery_failure():
    def _boom():
        raise RuntimeError("ffmpeg missing required delivery encoders: ['libopenh264']")

    with pytest.raises(RuntimeError, match="libopenh264"):
        assert_startup_codecs(_finalist_fn=lambda: None, _delivery_fn=_boom)
