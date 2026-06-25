"""Frozen champion-vs-challenger cutover snapshot — runs OFFLINE in CI (EVAL-2).

The live ``evaluate_cutover`` paths only fire behind ``FLIPHOUSE_LIVE_GEMINI`` with
a paid key, so a ranking-logic or gate regression would never be caught by the
normal gate. This test pins a real champion(text-only)-vs-challenger(native-A/V)
ranking decision on a committed golden snapshot and replays the gate with no
network and no ffmpeg, so CI is the regression guard the live tests cannot be.

The snapshot (``fixtures/cutover_snapshot.json``) is a representative 40-clip set:
the text-only champion tracks the human ranking only weakly (Spearman ≈ 0.58,
text is blind to visual/audio hooks) while the native-A/V challenger tracks it
almost perfectly (≈ 0.996). With n=40 the margin clears the MDE and the seeded
bootstrap CI excludes 0, so the gate must keep PROMOTING. If the cascade,
metrics, or gate logic regresses, the decision flips and this test goes red.
"""

import json
from pathlib import Path

from fliphouse_worker.eval import LabeledClip, evaluate_cutover

_SNAPSHOT = Path(__file__).parent / "fixtures" / "cutover_snapshot.json"


def _load_snapshot() -> dict:
    return json.loads(_SNAPSHOT.read_text(encoding="utf-8"))


def test_frozen_cutover_snapshot_promotes_av_over_text():
    snap = _load_snapshot()
    clips = [
        LabeledClip(c["clip_id"], f"clip {c['clip_id']}", c["human_score"]) for c in snap["clips"]
    ]
    champion = {c["clip_id"]: c["champion"] for c in snap["clips"]}
    challenger = {c["clip_id"]: c["challenger"] for c in snap["clips"]}
    gate = snap["gate"]

    report = evaluate_cutover(
        champion,
        challenger,
        clips,
        min_spearman=gate["min_spearman"],
        min_dispersion=gate["min_dispersion"],
        min_delta_spearman=gate["min_delta_spearman"],
        min_n=gate["min_n"],
        n_bootstrap=gate["n_bootstrap"],
        # rng=None → resolves to the internal seeded Random(0) → reproducible in CI.
    )

    # The frozen decision: A/V beats text-only and the gate promotes.
    assert report.promoted is snap["expected"]["promoted"]
    assert report.reason == snap["expected"]["reason"]
    # The signal that justifies the promotion: the challenger ranks strictly better.
    assert report.challenger_report.spearman > report.champion_report.spearman
    # Significance: the seeded bootstrap CI for ΔSpearman must exclude 0.
    assert report.delta_ci_low > 0.0


def test_frozen_cutover_is_reproducible_across_runs():
    # The seeded default rng must make the offline gate byte-stable run to run,
    # so a green CI today stays green tomorrow on the same snapshot.
    snap = _load_snapshot()
    clips = [LabeledClip(c["clip_id"], "t", c["human_score"]) for c in snap["clips"]]
    champion = {c["clip_id"]: c["champion"] for c in snap["clips"]}
    challenger = {c["clip_id"]: c["challenger"] for c in snap["clips"]}
    gate = snap["gate"]
    kw = dict(
        min_spearman=gate["min_spearman"],
        min_dispersion=gate["min_dispersion"],
        min_delta_spearman=gate["min_delta_spearman"],
        min_n=gate["min_n"],
        n_bootstrap=gate["n_bootstrap"],
    )
    a = evaluate_cutover(champion, challenger, clips, **kw)
    b = evaluate_cutover(champion, challenger, clips, **kw)
    assert a.delta_ci_low == b.delta_ci_low
    assert a.delta_ci_high == b.delta_ci_high
    assert a.promoted == b.promoted
