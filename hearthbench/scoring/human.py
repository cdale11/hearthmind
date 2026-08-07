"""HearthBench A4.3 — Tier 3: human rating (calibration ground truth).

"A blind-pairwise page over stored outputs; reports judge<->human
agreement." The checklist names a page (A12.9, `hearthbench/ui`'s own
future work — not built here, not this pass's scope) and a report
(judge<->human agreement). This module ships the real, storable data
model a page would read/write, and the real agreement computation a
report would show — both fully testable and useful (a human rater
could already drive this today via a small script) without waiting on
A12's web UI to exist.

Deliberately "blind": `HumanRatingTask` never carries which adapter
produced candidate "a" vs. "b" — `candidate_a_source`/`candidate_b_
source` are recorded for later analysis but a real UI must not surface
them to the rater before a choice is made (a UI concern, out of scope
here; this module can't enforce it, only avoid tempting it by keeping
the fields separate from whatever a rating page would render).

Storage is a plain append-only JSONL file, same convention every other
durable log in this project already uses (`hearthmind.llm.recorder`'s
own archive shape) — one line per real human decision, never rewritten
in place.

Import isolation (A1.2): stdlib only.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

RatingChoice = str
"""One of `"a"`, `"b"`, `"tie"` — deliberately a plain string, not an
enum, so a stored JSONL line never depends on importing this module to
read back (same "plain JSON on disk, no pickled Python objects"
discipline the recorder archive already holds)."""

_VALID_CHOICES = frozenset({"a", "b", "tie"})


@dataclass
class HumanRatingTask:
    """One blind-pairwise comparison unit — two candidate outputs for
    the SAME underlying case, with no visible adapter identity. `task_
    id` is the caller's own stable identifier (e.g. a hash of
    `case_id + candidate_a_source + candidate_b_source`); this module
    doesn't compute one, since a real UI's own task-queue mechanics
    (dedup, assignment, expiry) are out of scope here."""

    task_id: str
    case_id: str
    prompt_text: str
    candidate_a_text: str
    candidate_b_text: str
    candidate_a_source: str
    """Which adapter/run produced candidate A — real bookkeeping data,
    NOT for the rater's eyes (see module docstring)."""
    candidate_b_source: str
    judge_score_a: float | None = None
    """This case's Tier 2 judge composite for candidate A, if one was
    computed — carried alongside so `judge_human_agreement` can later
    compare a judge's implied preference against what the human
    actually chose, without a second join against judge results."""
    judge_score_b: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HumanRatingTask":
        return cls(
            task_id=data["task_id"], case_id=data["case_id"], prompt_text=data.get("prompt_text", ""),
            candidate_a_text=data.get("candidate_a_text", ""), candidate_b_text=data.get("candidate_b_text", ""),
            candidate_a_source=data.get("candidate_a_source", ""), candidate_b_source=data.get("candidate_b_source", ""),
            judge_score_a=data.get("judge_score_a"), judge_score_b=data.get("judge_score_b"),
        )


@dataclass
class HumanRating:
    """One rater's real decision on one `HumanRatingTask`."""

    task_id: str
    rater_id: str
    choice: RatingChoice
    timestamp: float = field(default_factory=time.time)
    confidence: float | None = None
    """Optional self-reported `[0, 1]` confidence — a future UI's own
    call whether to collect it; agreement computation below works
    fine without it."""
    note: str | None = None

    def __post_init__(self) -> None:
        if self.choice not in _VALID_CHOICES:
            raise ValueError(f"HumanRating.choice must be one of {sorted(_VALID_CHOICES)}, got {self.choice!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "HumanRating":
        return cls(
            task_id=data["task_id"], rater_id=data["rater_id"], choice=data["choice"],
            timestamp=float(data.get("timestamp", time.time())),
            confidence=data.get("confidence"), note=data.get("note"),
        )


def append_rating(path: "str | Path", rating: HumanRating) -> None:
    """The one write path — append-only, one JSON line per real human
    decision, never rewritten. `path`'s parent directory is created if
    missing (same "the archive dir need not pre-exist" convenience as
    `hearthmind.llm.recorder`'s own archive writer)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rating.to_dict()) + "\n")


def load_ratings(path: "str | Path") -> list:
    """Every rating ever appended to `path`, in file order. A missing
    file degrades to an empty list (no ratings collected yet is a
    real, valid state, not an error) — same convention `review_pack.
    iter_examples` already holds for a not-yet-created archive."""
    p = Path(path)
    if not p.exists():
        return []
    ratings = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            ratings.append(HumanRating.from_dict(json.loads(line)))
    return ratings


def judge_implied_choice(task: HumanRatingTask, tie_margin: float = 0.05) -> RatingChoice | None:
    """The judge's own implied preference for a task, derived from its
    stored `judge_score_a`/`judge_score_b` — `"a"`/`"b"` when the gap
    exceeds `tie_margin`, `"tie"` when the two scores are close enough
    to call a wash, `None` when either judge score is missing (no
    judge ran on this task, or it errored — can't compute agreement
    for it, same "no data point, not a violation" convention as every
    other `None`-returning function in this codebase)."""
    if task.judge_score_a is None or task.judge_score_b is None:
        return None
    diff = task.judge_score_a - task.judge_score_b
    if abs(diff) <= tie_margin:
        return "tie"
    return "a" if diff > 0 else "b"


def judge_human_agreement(tasks: list, ratings: list, tie_margin: float = 0.05) -> dict:
    """"Reports judge<->human agreement" (A4.3's own literal phrase).
    `tasks` is the full set of `HumanRatingTask`s (indexed by
    `task_id`); `ratings` is every collected `HumanRating` (one task
    may have several raters — each rating is its own comparison
    point, not averaged into one before comparing). Returns `{n_
    compared, n_agree, agreement_rate, n_no_judge_score,
    disagreements}` — `agreement_rate` is `None` when nothing was
    comparable (no judge scores recorded on any rated task yet)."""
    tasks_by_id = {t.task_id: t for t in tasks}
    compared = 0
    agree = 0
    no_judge_score = 0
    disagreements = []
    for rating in ratings:
        task = tasks_by_id.get(rating.task_id)
        if task is None:
            continue
        implied = judge_implied_choice(task, tie_margin=tie_margin)
        if implied is None:
            no_judge_score += 1
            continue
        compared += 1
        if implied == rating.choice:
            agree += 1
        else:
            disagreements.append({"task_id": task.task_id, "judge_choice": implied, "human_choice": rating.choice,
                                   "rater_id": rating.rater_id})
    return {
        "n_compared": compared, "n_agree": agree,
        "agreement_rate": (agree / compared) if compared else None,
        "n_no_judge_score": no_judge_score, "disagreements": disagreements,
    }
