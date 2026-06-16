"""render_preflight — libopenh264 + aac presence gate, fail-closed on absence."""

import pytest

from fliphouse_worker.clipping.render_preflight import assert_render_codecs


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
