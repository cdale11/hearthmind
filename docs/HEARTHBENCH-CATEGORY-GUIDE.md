# HearthBench — adding a new benchmark category (A5.10)

A category is a Python module in `hearthbench/tests/` — three parts,
none optional, none needing you to touch a runner (A11 doesn't exist
yet; nothing here does either). Copy `hearthbench/tests/_template.py`
and follow along.

## 1. Declare the `Category`

```python
from hearthbench.tests.category import Category

MY_CATEGORY = Category(
    id="my_category",             # stable, lowercase, matches A10.1's naming if it maps to one of its named slots
    name="My Category",           # human-readable, for reports
    weight=10.0,                  # see A10.1's default table below
    scorer_ids=("schema_validity",),  # string ids only — never import a Scorer object here
    description="One sentence: what does this category measure?",
)
```

A10.1's own stated default composite weights, for reference (a new
category not in this list simply isn't folded into the composite
until A10 is built and this list is extended there too — nothing
breaks by adding a category outside it):

| Category | Weight |
|---|---|
| Grounding | 20 |
| Dialogue | 15 |
| Beliefs | 12 |
| Memory | 12 |
| Village cognition | 10 |
| Personality | 10 |
| Planning | 8 |
| Reliability / structured output | 8 |
| Performance | 5 |

## 2. Reuse an existing scorer, or add one

Check `hearthbench.scoring.DEFAULT_REGISTRY.ids()` first — most
categories need nothing new (`structured_outputs.py` adds zero new
scorers, reusing three of A4.1's nine). Only write a new `Scorer` when
the category needs a judgment nothing existing makes:

```python
from hearthbench.scoring.types import CaseResult, ScoreDetail, Scorer

def _score_my_thing(case, result: CaseResult, context: dict) -> ScoreDetail:
    # value: normalized [0.0, 1.0] "how good", or None if this is a
    # pure measurement / not applicable to this case (see ScoreDetail's
    # own docstring — None is a real, meaningful answer, never a
    # silent zero).
    return ScoreDetail(scorer_id="", scorer_version="", value=1.0, passed=True, detail={})

MY_SCORER = Scorer(id="my_scorer", version="1", fn=_score_my_thing, tier=1, category="my_category")
```

Never raise inside `fn` — `Scorer.score()` already catches everything
and degrades to an error `ScoreDetail`, but writing genuinely defensive
`fn`s (return `None`/a real detail on an unexpected input, same as
every scorer in `deterministic.py`) keeps error messages meaningful
instead of generic.

Tier matters: `1` = deterministic/free/always-on (A4.1's own bar — no
model call inside `fn`, ever). `2` = needs a judge model (see
`hearthbench.scoring.judge.JudgeScorer`, construct one per adapter, use
`.as_scorer()`). `3` = human-rating-derived (see `hearthbench.
scoring.human`) — a category almost never scores Tier 3 directly; it
feeds `judge_human_agreement`'s calibration report instead.

## 3. Build real `TestCase` objects

Two real sources exist today:

**(a) From a fixture** (a real recorded example, or a synthesized one)
— the right choice when organic archive data already carries what the
category needs:

```python
from hearthbench.prompts.schema import test_case_from_fixture

def build_my_category_cases(fixtures) -> list:
    return [test_case_from_fixture(fx, category="my_category", scorers=list(MY_CATEGORY.scorer_ids)) for fx in fixtures]
```

**(b) Hand-authored** — the right choice for a designed/adversarial
prompt with no natural archive source (see `grounding.py`'s bait
cases):

```python
from hearthbench.prompts.schema import TestCase, Turn

def build_my_category_cases() -> list:
    return [
        TestCase(
            id="my_category:some_case", category="my_category",
            system_prompt="...", scorers=list(MY_CATEGORY.scorer_ids),
            turns=[Turn(index=0, content="the bait question or prompt")],
            expected_invariants=["a fact this case's own context does/doesn't support"],
        ),
    ]
```

## 4. Register it

Add the `Category` and any `build_*_cases`/new `Scorer` to
`hearthbench/tests/__init__.py`'s imports and `CATEGORY_REGISTRY` —
the one place a future A9 (reports)/A10 (composite score)/A11 (runner)
looks up "every category this benchmark knows about." A new Tier 1
scorer should also be registered into `hearthbench.scoring.DEFAULT_
REGISTRY` (via `hearthbench.scoring.registry.ScorerRegistry.register`)
so `DEFAULT_REGISTRY.resolve([...])` can find it by id.

## 5. Verify it the same way every shipped category was

No unittest in this project (see `CLAUDE.md`'s standing workflow
rule) — write a standalone `scripts/verify_*.py` following `verify_a4_
scoring.py`'s own shape: real inputs (a real archive via
`TrainingRecorder`, or real hand-built `CaseResult`s), a `check(name,
condition)` helper, exit non-zero on any failure. Cover: the category's
own scorer(s) against a case that SHOULD pass and one that SHOULD fail;
`build_*_cases()` producing real, well-formed `TestCase`s; and — if you
added a scorer — its degrade-to-`None`/error paths, not just the happy
path.
