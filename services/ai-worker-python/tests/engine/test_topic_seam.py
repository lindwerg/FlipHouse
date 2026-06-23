"""Unit coverage for engine/topic_seam.py — the (stubbed) topic-coherence seam.

The real multilingual-e5 TextTiling break is deferred this increment; what ships
is a clean injectable seam with an inert default. These tests pin that the default
never forces a break (so segmenter behavior is unchanged) and that the documented
similarity floor constant is present for the future live wiring.
"""

from fliphouse_worker.engine.topic_seam import TOPIC_SIM_FLOOR, no_topic_break


def test_no_topic_break_is_always_false():
    assert no_topic_break("any run text", "any next text") is False
    assert no_topic_break("", "") is False


def test_topic_sim_floor_is_a_sane_cosine_threshold():
    assert 0.0 < TOPIC_SIM_FLOOR < 1.0
