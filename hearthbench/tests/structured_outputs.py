"""HearthBench A5.8 — Structured outputs. "JSON validity, schema
compliance, retry/parse-failure/fallback rate, with and without
grammar constraints."

`build_structured_output_cases()` derives one real `TestCase` per
task actually registered in `hearthmind.llm.json_schemas.TASK_SCHEMAS`
— real reuse (no second schema catalogue), and automatically covers a
future task the moment it's added there, with zero edits needed here.
Each task gets TWO case variants, `tags=["grammar"]`/`tags=["no_
grammar"]` (same `schema_ref`, same scorer set) — the checklist's own
"with and without grammar constraints" comparison is a property of how
a future A11 runner DISPATCHES a case (does it pass `schema=...` to
the adapter's `generate()` or not), not of the case data itself; the
two tags are what lets a runner group results back into the two
populations `score_structured_output_delta` below compares.

`score_structured_output_delta` is this pass's real answer to A6.3's
identical "score both constrained and unconstrained modes... report
the delta" — A6 (the full structured-output validator) doesn't exist
yet, but the one comparison A5.8/A6.3 both actually ask for (does
constraining decoding measurably raise the schema-compliance pass
rate?) needs nothing from A6 that isn't already in `hearthbench.
tests.category.CategoryScoreSummary`.

Import isolation (A1.2): stdlib + `hearthmind.llm.json_schemas`
(schema catalogue only, no `hearthmind.simulation`/`.agents`/`.world`)
+ `hearthbench.prompts`/`hearthbench.tests.category`.
"""
from __future__ import annotations

from hearthmind.llm.json_schemas import TASK_SCHEMAS

from hearthbench.prompts.schema import TestCase
from hearthbench.tests.category import Category, CategoryScoreSummary

STRUCTURED_OUTPUTS_CATEGORY = Category(
    id="structured_outputs", name="Structured Outputs", weight=8.0,
    scorer_ids=("schema_validity", "length_compliance", "fallback_free"),
    description="JSON validity, schema compliance, and parse/retry/fallback rate, with and without grammar constraints.",
)


def build_structured_output_cases() -> list:
    """One `(grammar, no_grammar)` pair per real registered task
    schema — real reuse of `TASK_SCHEMAS`, sorted for a deterministic
    case order (matters for a future runner's own resume/ID stability,
    A11.4)."""
    cases = []
    for task in sorted(TASK_SCHEMAS):
        for variant in ("grammar", "no_grammar"):
            cases.append(TestCase(
                id=f"structured_outputs:{task}:{variant}", category="structured_outputs",
                schema_ref=task, scorers=list(STRUCTURED_OUTPUTS_CATEGORY.scorer_ids),
                tags=["structured_outputs", variant],
            ))
    return cases


def score_structured_output_delta(with_grammar: CategoryScoreSummary, without_grammar: CategoryScoreSummary) -> dict:
    """A6.3/A5.8's own "report the delta." Both inputs are real
    `CategoryScoreSummary`s (from `hearthbench.tests.category.
    summarize_scores`) computed separately over the `grammar`-tagged
    vs. `no_grammar`-tagged case results of a real run. `pass_rate_
    delta` is `None` when either side has no scored pass/fail data yet
    (nothing to compare) rather than a misleading `0.0`."""
    if with_grammar.pass_rate is None or without_grammar.pass_rate is None:
        return {
            "pass_rate_delta": None, "with_grammar_pass_rate": with_grammar.pass_rate,
            "without_grammar_pass_rate": without_grammar.pass_rate,
            "reason": "one or both sides have no scored pass/fail data",
        }
    return {
        "pass_rate_delta": with_grammar.pass_rate - without_grammar.pass_rate,
        "with_grammar_pass_rate": with_grammar.pass_rate,
        "without_grammar_pass_rate": without_grammar.pass_rate,
        "grammar_helps": with_grammar.pass_rate > without_grammar.pass_rate,
    }
