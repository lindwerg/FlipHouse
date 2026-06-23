"""Pure-function tests for the deterministic viral-banger signals (P2 clipping-mvp).

These signals are a cheap CPU prior that nudges punchy/разнос clips up the
ranking. They are fully deterministic, so every band is pinned exactly here.
"""

from dataclasses import dataclass

from fliphouse_worker.scoring.viral_signals import (
    ENERGY_SATURATION_EVENTS,
    MAX_VIRAL_BONUS,
    ViralSignal,
    energy_density,
    hook_strength,
    quotable,
    viral_signal,
)

# ── lightweight DSP-signals stand-ins (match the LocalSignals attribute seam) ──


@dataclass(frozen=True)
class _Flag:
    t: float
    laughter_conf: float


@dataclass(frozen=True)
class _Signals:
    energy_peaks_s: tuple[float, ...] = ()
    audio_flags: tuple[_Flag, ...] = ()


# ── hook_strength ────────────────────────────────────────────────────────────


def test_hook_strength_empty_text_is_zero():
    assert hook_strength("") == 0.0
    assert hook_strength("   ") == 0.0


def test_hook_strength_number_in_opening():
    assert hook_strength("Я потерял 1000000 долларов за день") >= 0.25


def test_hook_strength_negation_frame():
    assert hook_strength("Никто не говорит вам эту правду о деньгах") > 0.0


def test_hook_strength_question_opening():
    assert hook_strength("Знаешь, почему ты до сих пор беден?") >= 0.15


def test_hook_strength_stacks_multiple_families_but_clamps_to_one():
    # secret + negation + contradiction + number + stakes → raw sum > 1, clamped.
    text = "Секрет: никто не знал, оказалось я потерял 100 миллионов"
    assert hook_strength(text) == 1.0


def test_hook_strength_dead_opener_is_penalized_to_zero():
    # "так, давайте" is a dead admin opener → penalty drives it to 0.
    assert hook_strength("Так, давайте сверим расписание встреч") == 0.0


def test_hook_strength_penalty_offsets_a_real_signal():
    # A dead opener that also contains a number: 0.25 (number) - 0.4 (dead) → 0.
    assert hook_strength("Так, давайте 5 минут поговорим") == 0.0


def test_hook_strength_only_scans_the_opening_window():
    # A hook word far past the opening window does NOT count.
    tail_hook = "слово " * 20 + "никто"
    assert hook_strength(tail_hook) == 0.0


# ── quotable ─────────────────────────────────────────────────────────────────


def test_quotable_short_declarative_line_scores_one():
    assert quotable("Деньги не делают тебя счастливым. Они делают тебя свободным.") == 1.0


def test_quotable_run_on_with_no_short_phrase_scores_zero():
    long_phrase = " ".join("слово" for _ in range(30))
    assert quotable(long_phrase) == 0.0


def test_quotable_too_short_fragments_score_zero():
    assert quotable("Да. Нет. Что?") == 0.0  # each phrase < QUOTABLE_MIN_WORDS


def test_quotable_empty_text_scores_zero():
    assert quotable("") == 0.0


# ── energy_density ───────────────────────────────────────────────────────────


def test_energy_density_zero_when_span_degenerate():
    assert energy_density(10.0, 10.0, _Signals(energy_peaks_s=(10.0,))) == 0.0


def test_energy_density_counts_in_span_peaks():
    sig = _Signals(energy_peaks_s=(5.0, 12.0, 50.0))  # two inside [0, 20]
    assert energy_density(0.0, 20.0, sig) == round(2 / ENERGY_SATURATION_EVENTS, 6)


def test_energy_density_counts_laughter_flags():
    sig = _Signals(audio_flags=(_Flag(t=3.0, laughter_conf=0.5), _Flag(t=4.0, laughter_conf=0.1)))
    # only the >= 0.2 laughter flag counts.
    assert energy_density(0.0, 10.0, sig) == round(1 / ENERGY_SATURATION_EVENTS, 6)


def test_energy_density_saturates_at_one():
    peaks = tuple(float(i) for i in range(ENERGY_SATURATION_EVENTS + 5))
    assert energy_density(0.0, 100.0, _Signals(energy_peaks_s=peaks)) == 1.0


def test_energy_density_none_signals_is_zero():
    # A text-only run injects None signals — the DSP term must read 0, not raise.
    assert energy_density(0.0, 20.0, None) == 0.0


# ── viral_signal fusion ──────────────────────────────────────────────────────


def test_viral_signal_is_a_dataclass_with_all_subsignals():
    sig = viral_signal("Никто не говорит вам правду", 0.0, 20.0, _Signals())
    assert isinstance(sig, ViralSignal)
    assert 0.0 <= sig.bonus <= MAX_VIRAL_BONUS


def test_viral_signal_maxed_clip_earns_the_full_cap():
    text = "Секрет: никто не знал, оказалось я потерял 100 миллионов. Это ложь."
    peaks = tuple(float(i) for i in range(ENERGY_SATURATION_EVENTS + 1))
    sig = viral_signal(text, 0.0, 100.0, _Signals(energy_peaks_s=peaks))
    assert sig.hook_strength == 1.0
    assert sig.quotable == 1.0
    assert sig.energy_density == 1.0
    assert sig.bonus == MAX_VIRAL_BONUS  # weights sum to 1.0 → full cap


def test_viral_signal_flat_clip_earns_no_bonus():
    # A dead opener, one long run-on phrase >14 words (no quote-card line), and no
    # DSP → every sub-signal is 0, so the bonus is exactly 0.
    flat = (
        "Так, давайте сверим расписание встреч на следующую неделю и обсудим "
        "все детали проекта подробно вместе со всей нашей командой"
    )
    sig = viral_signal(flat, 0.0, 20.0, _Signals())
    assert sig.hook_strength == 0.0
    assert sig.quotable == 0.0
    assert sig.bonus == 0.0


def test_viral_signal_is_deterministic():
    a = viral_signal("Я потерял миллион за день. Вот урок.", 0.0, 25.0, _Signals())
    b = viral_signal("Я потерял миллион за день. Вот урок.", 0.0, 25.0, _Signals())
    assert a == b
