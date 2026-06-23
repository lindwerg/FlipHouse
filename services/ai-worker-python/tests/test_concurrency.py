"""Unit coverage for the shared bounded thread-pool fan-out (ASK #6 Speed)."""

from __future__ import annotations

import logging

from fliphouse_worker.concurrency import (
    MAX_CAPTION_WORKERS,
    MAX_RENDER_WORKERS,
    ordered_threadpool_map,
    strict_ordered_threadpool_map,
)


def test_worker_caps_are_small_bounded_constants():
    # Small enough that an N-clip job never forks N native encoders on a 2-vCPU box.
    assert MAX_RENDER_WORKERS == 4
    assert MAX_CAPTION_WORKERS == 4


def test_ordered_map_empty_returns_list_without_executor():
    called: list[int] = []
    assert ordered_threadpool_map(lambda x: called.append(x), []) == []
    assert called == []  # no executor constructed, fn never called


def test_ordered_map_preserves_input_order_over_shuffled_input():
    shuffled = [3, 1, 2, 0]
    # fn returns the value; order of results must match INPUT order, not finish order.
    assert ordered_threadpool_map(lambda x: x, shuffled) == shuffled


def test_ordered_map_executes_and_clamps_below_item_count():
    assert ordered_threadpool_map(lambda x: x * 2, [1, 2, 3], max_workers=1) == [2, 4, 6]


def test_ordered_map_contains_crash_to_none_and_warns(caplog):
    def fn(x):
        if x == 1:
            raise RuntimeError("unexpected")
        return x

    with caplog.at_level(logging.WARNING):
        out = ordered_threadpool_map(fn, [1, 2])
    assert out == [None, 2]  # the crash is contained, the rest survive
    assert any("task crashed" in r.message for r in caplog.records)


def test_strict_map_empty_returns_list():
    assert strict_ordered_threadpool_map(lambda x: x, []) == []


def test_strict_map_preserves_order_and_clamps():
    assert strict_ordered_threadpool_map(lambda x: x * 2, [1, 2, 3], max_workers=1) == [2, 4, 6]


def test_strict_map_propagates_exception_not_contained():
    def fn(x):
        if x == 1:
            raise RuntimeError("fatal")
        return x

    import pytest

    with pytest.raises(RuntimeError, match="fatal"):
        strict_ordered_threadpool_map(fn, [1, 2])
