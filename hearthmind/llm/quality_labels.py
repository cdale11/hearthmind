"""FT.2 (docs/AUDIT-2026-07-20.md's fine-tuning roadmap): "Build the
quality-label pass (automatic curation)." Every label below already
existed as logic somewhere in this project for a different purpose —
`llm/json_schemas.py` (FT.0), `dialogue._is_sane_line`'s leak/garble
gate, `llm/review_diagnostics.py`'s context-reflection heuristic, the
P0.2/P1.1 leak fixes recorded in CLAUDE.md. This module is the first
place they run PER EXAMPLE over the archive and combine into one
queryable label set, so "the SFT set is a filter query over the
archive" (the audit's own phrase) is something `scripts/recorder_
tools.py label`/`export-sft` can actually do instead of a human
eyeballing which examples are safe to train on.

Deliberately read-only: nothing here mutates the archive (it stays
append-only, same discipline every other event log in this project
keeps) or the live `TrainingRecorder`. `label_example` takes one
already-loaded archive dict (the `to_dict()` shape `TrainingExample`
writes, i.e. what `review_pack.iter_examples` yields) and returns a
plain dict of labels — every one of them a real judgment already
computed from data the example already carries, never a fresh network
call.

**Do not confuse `sft_eligible=True` with "good enough to actually
train on."** Per FT's own warning (docs/AUDIT-2026-07-20.md, the "Do
not SFT on the raw archive as-is" callout): today's archive is the
current UN-TUNED model's own outputs, recorded mid-flaw. `sft_eligible`
only means "structurally sound and free of the specific failure
patterns this project has already identified" — it is a necessary
filter, not a sufficient one. FT.3's teacher-distillation/rejection-
sampling step is still what actually produces trainable targets.
"""
from __future__ import annotations

import re
from typing import Any

from hearthmind.llm.json_schemas import schema_for_task
from hearthmind.llm.review_diagnostics import context_reflects_any

_COORD_RE = re.compile(r"\(\s*-?\d{1,4}\s*,\s*-?\d{1,4}\s*\)|\b(?:x\s*=\s*-?\d+|y\s*=\s*-?\d+)\b", re.IGNORECASE)
"""Raw tile coordinates leaking into narrated text — the P1.1 finding
(CLAUDE.md v1.3.7: "raw tile coordinates recited in speech"). Matches
`(12, 34)`-style pairs and bare `x=12`/`y=34` fragments; deliberately
loose (a false positive here just costs an example its `no_coord_leak`
label, never a crash or a silent drop) rather than tuned to any one
prompt's exact past phrasing."""

_MEMORY_FADE_PREFIX_RE = re.compile(r"i only vaguely recall", re.IGNORECASE)
"""The other P1.1 finding: `faded_memory_text`'s narrator-facing
"I only vaguely recall:" prefix quoted/laundered as literal spoken
dialogue instead of being stripped before reaching the character's own
voice."""

_VOICE_LEADING_PRONOUN_RE = re.compile(r"^(they|he|she|it)\s+", re.IGNORECASE)
"""Mirrors `agents.agent._VOICE_LEADING_PRONOUN_RE` — the P0.4 "broken
voice grammar" bug (CLAUDE.md v1.3.6): a `mind` task's `voice` field
is meant to be a bare continuation predicate ("speaks in short, plain
sentences"), not a full sentence with its own redundant subject
pronoun or a sentence-initial capital. `normalize_voice_phrase` fixes
this at write/read time in production; this label exists to flag any
ARCHIVED example recorded before that fix (or from a raw completion
that predates its own parse-time correction) as unsuitable to imitate
verbatim."""

_META_LEAKAGE_MARKERS = (
    "json", "system prompt", "you are writing", "respond with",
    "as an ai", "language model", "i cannot", "i'm an ai",
    "here is", "here's a", "output:", "```",
)
"""A trimmed, task-agnostic subset of `dialogue._LEAKAGE_MARKERS` —
instruction/meta-commentary leakage isn't a dialogue-only failure
mode, so this checks every text field on every task, not just
line_a/line_b. Narrower than dialogue's own list (drops dialogue-
schema-specific markers like `"line_a"`/`"sentiment"` that would
false-positive on other tasks whose real field names happen to
overlap)."""


def _text_fields(output: dict) -> list[str]:
    """Every string value in a parsed-output dict — the label checks
    below scan all of them rather than hardcoding per-task field names,
    so a new task/field is covered automatically without an update
    here."""
    return [v for v in output.values() if isinstance(v, str) and v.strip()]


def check_leaks(task: str, output: dict) -> list[str]:
    """Returns the names of every leak pattern found, `[]` if clean.
    Never raises on a malformed `output` (defends the same way every
    `parse_*` in this project does — a bad archive line degrades to
    "no labels available," not a crash)."""
    if not isinstance(output, dict):
        return []
    flags: list[str] = []
    texts = _text_fields(output)
    if any(_COORD_RE.search(t) for t in texts):
        flags.append("raw_coordinates")
    if any(_MEMORY_FADE_PREFIX_RE.search(t) for t in texts):
        flags.append("memory_fade_prefix")
    if any(any(marker in t.lower() for marker in _META_LEAKAGE_MARKERS) for t in texts):
        flags.append("meta_leakage")
    if task == "mind":
        voice = output.get("voice")
        if isinstance(voice, str) and voice.strip():
            stripped = voice.strip()
            if _VOICE_LEADING_PRONOUN_RE.match(stripped) or (stripped[0].isalpha() and stripped[0].isupper()):
                flags.append("voice_grammar_break")
    return flags


def _type_ok(prop_schema: dict, value: Any) -> bool:
    expected = prop_schema.get("type")
    types = expected if isinstance(expected, list) else [expected]
    for t in types:
        if t == "string" and isinstance(value, str):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "null" and value is None:
            return True
    return False


def schema_valid(task: str, output: dict) -> bool | None:
    """Validates `output` against the same per-task schema FT.0's
    grammar-constrained decoding enforces at generation time
    (`llm/json_schemas.py`) — a lightweight structural check (required
    keys present, types match, enums honored, string `maxLength`
    respected), not a full JSON Schema implementation, since this
    project's own schemas only ever use that subset. `None` (not
    applicable, not a violation) when the task has no schema entry —
    every call site treats `None` as "can't judge this one," same
    convention `context_reflects_any` already uses. A pre-FT.0
    archive example that happens to already satisfy the shape passes
    here too; this label isn't "was this call schema-constrained," it
    is "would this output have survived being schema-constrained.\""""
    schema = schema_for_task(task)
    if schema is None or not isinstance(output, dict):
        return None
    properties = schema.get("properties", {})
    for key in schema.get("required", ()):
        if key not in output or output[key] is None:
            return False
    for key, value in output.items():
        prop_schema = properties.get(key)
        if prop_schema is None:
            if not schema.get("additionalProperties", True):
                return False
            continue
        if value is None:
            if "null" not in (prop_schema.get("type") if isinstance(prop_schema.get("type"), list) else [prop_schema.get("type")]):
                if key in schema.get("required", ()):
                    return False
            continue
        if not _type_ok(prop_schema, value):
            return False
        if "enum" in prop_schema and value not in prop_schema["enum"]:
            return False
        if isinstance(value, str) and "maxLength" in prop_schema and len(value) > prop_schema["maxLength"] * 2:
            # 2x slack: schemas cap the *stored/truncated* field length
            # (see each `parse_*`'s own `[:N]` slice) — a raw pre-parse
            # completion can legitimately run a bit longer before
            # truncation without that being a real quality problem.
            return False
    return True


def length_in_bounds(task: str, output: dict) -> bool | None:
    """A softer, task-agnostic companion to `schema_valid`'s strict
    `maxLength` check: flags only the degenerate cases — an empty/
    whitespace-only text field where the schema requires one, or a
    field so long (5x its schema cap) it reads as the model ignoring
    the length instruction entirely rather than merely running a
    little over. `None` when the task has no schema to bound against."""
    schema = schema_for_task(task)
    if schema is None or not isinstance(output, dict):
        return None
    properties = schema.get("properties", {})
    required = set(schema.get("required", ()))
    for key, prop_schema in properties.items():
        if prop_schema.get("type") != "string":
            continue
        value = output.get(key)
        if key in required and (not isinstance(value, str) or not value.strip()):
            return False
        if isinstance(value, str) and "maxLength" in prop_schema and len(value) > prop_schema["maxLength"] * 5:
            return False
    return True


_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "in",
    "it", "that", "this", "i", "you", "we", "my", "your", "our", "on", "for",
})
_LEADING_CONNECTIVES = (
    "well", "aye", "no", "yes", "indeed", "true", "but", "and", "so", "ah",
    "true enough", "perhaps", "maybe", "still", "even so", "true, but",
)


def dialogue_responds(output: dict) -> bool | None:
    """"line_b-responds-to-line_a" (FT.2's own phrase: "token overlap /
    question-answered heuristic"). Three cheap signals, any one of
    which is enough to call it a real response rather than a
    non-sequitur: (1) line_a ends in a question and line_b isn't
    blank — an answer doesn't need to share vocabulary with its
    question; (2) line_b opens with a connective word a real
    conversational reply commonly opens with; (3) genuine token
    overlap (shared non-stopword words of length >= 3) between the two
    lines. `None` when either line is missing (not a dialogue example,
    or a malformed one)."""
    if not isinstance(output, dict):
        return None
    line_a, line_b = output.get("line_a"), output.get("line_b")
    if not isinstance(line_a, str) or not isinstance(line_b, str) or not line_a.strip() or not line_b.strip():
        return None
    if line_a.strip().endswith("?"):
        return True
    lowered_b = line_b.strip().lower()
    if any(lowered_b.startswith(c) for c in _LEADING_CONNECTIVES):
        return True
    tokens_a = {w for w in re.findall(r"[a-z']+", line_a.lower()) if len(w) >= 3 and w not in _STOPWORDS}
    tokens_b = {w for w in re.findall(r"[a-z']+", line_b.lower()) if len(w) >= 3 and w not in _STOPWORDS}
    return bool(tokens_a & tokens_b)


def topic_novel(structured_input: dict, output: dict) -> bool | None:
    """"topic-novelty vs. the settlement's dominant topic at that
    tick": the best per-tick baseline an already-archived example
    actually carries is `structured_input["settlement_topic"]`
    (`dialogue.build_prompt`'s own steering field, v0.87.31/.35) —
    literally what the prompt told the model the village had been
    talking about. `output["topic"]` differing from it is the direct
    signal the audit asked for; `None` when either side is missing
    (non-dialogue task, or a call where neither field fired)."""
    if not isinstance(structured_input, dict) or not isinstance(output, dict):
        return None
    dominant = structured_input.get("settlement_topic")
    topic = output.get("topic")
    if not isinstance(dominant, str) or not dominant.strip() or not isinstance(topic, str) or not topic.strip():
        return None
    return dominant.strip().lower() != topic.strip().lower()


def label_example(example: dict) -> dict:
    """Combines every label above into one dict for a single archive
    example (the `to_dict()` shape `review_pack.iter_examples`
    yields). Never raises — a malformed/legacy example just yields
    `None`/`False` labels rather than aborting a batch labeling run."""
    task = example.get("task")
    output = example.get("layer4_parsed_output") or {}
    structured_input = example.get("layer1_structured_input") or {}
    fallback_used = bool(example.get("fallback_used"))
    leaks = check_leaks(task, output) if not fallback_used else []
    output_text = " ".join(_text_fields(output)) if isinstance(output, dict) else ""
    labels = {
        "schema_valid": schema_valid(task, output),
        "length_in_bounds": length_in_bounds(task, output),
        "leak_flags": leaks,
        "context_reflected": context_reflects_any(structured_input, output_text),
        "fallback_used": fallback_used,
    }
    if task == "dialogue":
        labels["dialogue_responds"] = dialogue_responds(output)
        labels["topic_novel"] = topic_novel(structured_input, output)
    labels["sft_eligible"] = (
        not fallback_used
        and labels["schema_valid"] is not False
        and labels["length_in_bounds"] is not False
        and not leaks
        and (labels.get("dialogue_responds") is not False)
    )
    return labels
