"""Content checks for the hook→payoff ARC + completeness prompt additions (Phase 3).

The arc/completeness guidance is the mechanism that makes the scorer reward a clip
that opens AND closes its own loop and penalize one that starts/ends mid-thought —
the founder's "мысль должна быть закончена" requirement. These tests pin that the
guidance (and RU hook patterns) is present in BOTH scoring prompts and in the
highlight-selection prompt, so a future edit can't silently drop it.
"""

from fliphouse_worker.engine.highlights import HIGHLIGHT_SYSTEM_PROMPT
from fliphouse_worker.scoring.prompt import MEDIA_SYSTEM_PROMPT, SYSTEM_PROMPT


def test_text_prompt_has_arc_and_completeness_gate():
    assert "ARC & COMPLETENESS" in SYSTEM_PROMPT
    assert "HOOK-ONLY" in SYSTEM_PROMPT and "FULL ARC" in SYSTEM_PROMPT
    assert "cap payoff at 40" in SYSTEM_PROMPT  # broken-edge hard gate
    assert "ARC" in SYSTEM_PROMPT.split("rationale (STRING", 1)[1].split("\n", 1)[0]


def test_media_prompt_mirrors_arc_and_completeness_gate():
    assert "ARC & COMPLETENESS" in MEDIA_SYSTEM_PROMPT
    assert "cap payoff at 40" in MEDIA_SYSTEM_PROMPT
    assert "HOOK-ONLY" in MEDIA_SYSTEM_PROMPT and "FULL ARC" in MEDIA_SYSTEM_PROMPT


def test_text_prompt_has_ru_hook_patterns():
    assert "RU hook patterns" in SYSTEM_PROMPT
    assert "никто не говорит" in SYSTEM_PROMPT  # a concrete RU hook cue
    assert "так, давайте" in SYSTEM_PROMPT  # a concrete RU dead-hook cue


def test_highlight_prompt_demands_complete_arc_and_sentence_edges():
    assert "COMPLETE HOOK→PAYOFF ARC" in HIGHLIGHT_SYSTEM_PROMPT
    assert "SENTENCE EDGES" in HIGHLIGHT_SYSTEM_PROMPT
    assert "никто не говорит" in HIGHLIGHT_SYSTEM_PROMPT  # RU hook cue in selection too
