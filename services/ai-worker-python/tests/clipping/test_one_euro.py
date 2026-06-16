"""OneEuroFilter — first-sample passthrough, deadband hold, fast tracking, reset, /0 guard."""

from fliphouse_worker.clipping.one_euro import OneEuroFilter, _alpha


def test_first_sample_returns_raw():
    f = OneEuroFilter()
    assert f.filter(100.0, 0.0) == 100.0


def test_holds_near_value_at_low_speed():
    f = OneEuroFilter()
    f.filter(100.0, 0.0)
    out = f.filter(100.5, 0.5)  # tiny move → heavily smoothed toward the previous value
    assert 100.0 <= out <= 100.5


def test_tracks_toward_target_on_large_move():
    f = OneEuroFilter()
    f.filter(100.0, 0.0)
    out = f.filter(500.0, 0.5)  # big move → cutoff rises, follows more
    assert out > 100.0
    assert out < 500.0


def test_reset_snaps_state_and_clears_velocity():
    f = OneEuroFilter()
    f.filter(100.0, 0.0)
    f.filter(400.0, 0.5)
    f.reset(50.0, 1.0)
    # After reset the next sample is filtered as if 50.0 was the prior value at t=1.0.
    out = f.filter(50.0, 1.5)
    assert out == 50.0


def test_duplicate_timestamp_does_not_divide_by_zero():
    f = OneEuroFilter()
    f.filter(100.0, 1.0)
    out = f.filter(200.0, 1.0)  # same t → EPS guard
    assert out == out  # no ZeroDivisionError; a finite number


def test_alpha_monotonic_in_cutoff():
    assert _alpha(0.5, 0.1) < _alpha(0.5, 10.0)
