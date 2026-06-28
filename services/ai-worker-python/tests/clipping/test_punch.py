"""P3-A7: pure tests for the hook punch-zoom envelope + the zoompan chain it emits."""

from __future__ import annotations

import pytest

from fliphouse_worker.clipping.punch import (
    DURATION_MAX_S,
    DURATION_MIN_S,
    HOOK_PUNCH,
    Z_MAX,
    PunchZoom,
    PunchZoomError,
    _num,
    _z_of_t,
    punch_zoom_chain,
)

# The exact zoompan node for HOOK_PUNCH at 30fps onto a 1080x1920 canvas (spec §3).
_HOOK_NODE = (
    "zoompan=z='(1+(1.1-1)*pow(1-clip(on/(30*0.25),0,1),3))'"
    ":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    ":d=1:s=1080x1920:fps=30"
)


def test_hook_punch_defaults_match_researched_values() -> None:
    assert HOOK_PUNCH.z_open == 1.10
    assert HOOK_PUNCH.z_hold == 1.0
    assert HOOK_PUNCH.duration_s == 0.25


def test_punch_zoom_chain_is_pinned_byte_for_byte() -> None:
    assert punch_zoom_chain(1080, 1920, 30.0, HOOK_PUNCH) == _HOOK_NODE


@pytest.mark.parametrize(
    "kwargs",
    [
        {"z_open": 0.9},  # below z_hold floor of 1.0
        {"z_open": 1.20},  # above Z_MAX
        {"z_open": 1.0, "z_hold": 1.05},  # z_open < z_hold
        {"z_open": 1.1, "z_hold": 0.9},  # z_hold below 1.0
        {"z_open": 1.1, "duration_s": 0.04},  # below DURATION_MIN_S
        {"z_open": 1.1, "duration_s": 1.5},  # above DURATION_MAX_S
    ],
)
def test_punch_zoom_rejects_impossible_envelopes(kwargs: dict) -> None:
    with pytest.raises(PunchZoomError):
        PunchZoom(**kwargs)


def test_punch_zoom_accepts_the_valid_extremes() -> None:
    PunchZoom(z_open=Z_MAX)  # at the ceiling
    PunchZoom(z_open=1.0, z_hold=1.0, duration_s=DURATION_MIN_S)  # degenerate but legal
    PunchZoom(z_open=1.05, z_hold=1.05, duration_s=DURATION_MAX_S)  # hold-tight at the floor


def test_z_of_t_settles_from_open_to_hold() -> None:
    assert _z_of_t(HOOK_PUNCH, 0.0) == pytest.approx(1.10)
    assert _z_of_t(HOOK_PUNCH, HOOK_PUNCH.duration_s) == pytest.approx(1.0)
    # clamped past the duration → stays settled, never inverts.
    assert _z_of_t(HOOK_PUNCH, 2 * HOOK_PUNCH.duration_s) == pytest.approx(1.0)


def test_envelope_stays_in_frame_for_all_t() -> None:
    # The realized centered window is (iw - iw/Z)/2 offset, iw/Z wide. For Z>=1 the offset is
    # >=0 and the window <= iw, so the window is ALWAYS inside the base box — not just at the
    # endpoints. Sample densely across [0, 2*duration] (covers the clamp tail).
    iw, ih = 608, 1080
    n = 256
    for i in range(n + 1):
        t = (2.0 * HOOK_PUNCH.duration_s) * i / n
        z = _z_of_t(HOOK_PUNCH, t)
        assert HOOK_PUNCH.z_hold <= z <= HOOK_PUNCH.z_open
        x_off = (iw - iw / z) / 2
        y_off = (ih - ih / z) / 2
        assert x_off >= 0.0 and y_off >= 0.0
        assert iw / z <= iw and ih / z <= ih


def test_num_formatter_is_deterministic_and_avoids_scientific_notation() -> None:
    assert _num(1.0) == "1"
    assert _num(1.1) == "1.1"
    assert _num(0.25) == "0.25"
    assert _num(30.0) == "30"
    assert _num(29.97) == "29.97"
    # At both duration bounds the emitted value never goes to exponent form.
    assert "e" not in _num(DURATION_MIN_S)
    assert "e" not in _num(DURATION_MAX_S)


def test_punch_zoom_is_frozen() -> None:
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        HOOK_PUNCH.z_open = 1.5  # type: ignore[misc]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
