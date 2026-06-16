"""Labeled-clip dataset for the virality eval-harness (P2-S1).

Founder has no hand-labeled clips yet, so this ships a BOOTSTRAP seed set —
short transcript snippets whose virality is fairly unambiguous, with reference
``human_score`` (0-100). It is a starting baseline, NOT ground truth: real
labels arrive later (e.g. founder 👍/👎 in the dashboard) via ``load_clips``.
The seed lets the harness machinery run and be tested today.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LabeledClip:
    clip_id: str
    text: str
    human_score: int  # human virality judgment, 0-100


# Bootstrap seed: clearly-boring → clearly-viral. Founder corrects/replaces later.
SEED_CLIPS: tuple[LabeledClip, ...] = (
    LabeledClip("seed-01", "Так, давайте сверим расписание встреч на следующую неделю.", 5),
    LabeledClip("seed-02", "Сегодня погода нормальная, ничего особенного не произошло.", 10),
    LabeledClip("seed-03", "В общем, я думаю, что в целом подход был довольно стандартным.", 18),
    LabeledClip("seed-04", "Был один забавный случай на работе, расскажу коротко.", 38),
    LabeledClip(
        "seed-05", "Я долго не понимал, почему это не работает — а причина оказалась простой.", 45
    ),
    LabeledClip("seed-06", "И вот тут он сказал то, после чего в комнате повисла тишина.", 68),
    LabeledClip("seed-07", "Я попробовал это за 7 дней — результат меня реально шокировал.", 74),
    LabeledClip("seed-08", "Все думают, что нужно работать больше. Это убивает ваш бизнес.", 82),
    LabeledClip("seed-09", "Я потерял миллион долларов за один день. И вот что я понял.", 92),
    LabeledClip(
        "seed-10", "Никогда не делайте этого со своими деньгами. Я узнал на своём счёте.", 88
    ),
)


def load_clips(path: str | Path) -> list[LabeledClip]:
    """Load a labeled-clip dataset from JSON (list of {clip_id, text, human_score})."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("dataset must be a JSON list of clip objects")
    return [
        LabeledClip(clip_id=item["clip_id"], text=item["text"], human_score=item["human_score"])
        for item in raw
    ]
