"""A7 (docs/MASTERCHECKLIST-2026-07-22.md, roadmap step 27), first
slice, dialect-drift domain. Explicit user decision (via
`AskUserQuestion`): accept the doc's own default split — "layout/
architecture/dialect deterministic; myth/custom/law stay LLM (they
need meaning, not just structure)" — and implement all three
deterministic domains in one batch rather than picking just one.

This module: a deterministic rewrite-rule grammar over an EXISTING
coined term (`Settlement.lexicon`, still LLM-coined — see `llm/
narrative_direction.py`), producing a phonetically plausible variant
spelling with zero LLM cost. "The LLM seeds and names; the grammar
expands and varies deterministically and cheaply" (the doc's own
framing). Real production consumer: `SimulationEngine._maybe_schedule_
fission`'s `apply()` — a daughter settlement inherits a few of its
origin's terms, each independently drift-mutated, so two related
villages measurably start saying things slightly differently. Rule
selection is a stable hash of the term text, not `random` — this stays
a pure function of its input, no RNG stream, no native-soak-parity
risk."""

from __future__ import annotations

import hashlib

from hearthmind.util import clamp

VOWELS = "aeiou"

_VOWEL_SHIFT: dict[str, str] = {"a": "e", "e": "i", "i": "o", "o": "u", "u": "a"}
"""A closed rotation, not a random substitution — the same vowel
always shifts to the same neighbor, so repeated drift of the same term
is stable/reproducible, not noise."""

_CONSONANT_SOFTEN: dict[str, str] = {"k": "g", "t": "d", "p": "b", "s": "z"}

DRIFT_RULES: tuple[str, ...] = ("vowel_shift", "apocope", "epenthesis", "consonant_soften")
"""The closed set of production rules `drift_term` may apply — one per
call, chosen deterministically (see `_stable_choice`)."""


def _stable_choice(seed_text: str, options: tuple[str, ...]) -> str:
    """Deterministic, not `random.choice` — the same `seed_text` always
    picks the same option, so a term's drift is reproducible and this
    module never needs its own RNG stream."""
    digest = hashlib.sha256(seed_text.encode()).digest()
    return options[digest[0] % len(options)]


def _apply_rule(rule: str, term: str) -> str | None:
    """Returns the drifted term, or `None` if this rule has nothing to
    act on for this particular term (e.g. `apocope` on a term with no
    trailing vowel)."""
    if rule == "vowel_shift":
        for i in range(len(term) - 1, -1, -1):
            if term[i] in _VOWEL_SHIFT:
                return term[:i] + _VOWEL_SHIFT[term[i]] + term[i + 1:]
        return None
    if rule == "apocope":
        if len(term) > 3 and term[-1] in VOWELS:
            return term[:-1]
        return None
    if rule == "epenthesis":
        for i in range(len(term) - 1):
            if term[i] in VOWELS and term[i + 1] in VOWELS:
                return term[:i + 1] + "n" + term[i + 1:]
        return None
    if rule == "consonant_soften":
        for i, ch in enumerate(term):
            if ch in _CONSONANT_SOFTEN:
                return term[:i] + _CONSONANT_SOFTEN[ch] + term[i + 1:]
        return None
    return None


MAX_DRIFT_STEPS = 4
"""Cap on `drift_term`'s `steps` param (A7 follow-up, Tier 3 item 18):
compounding drift genuinely diminishes in per-step legibility — by the
fifth or sixth round a term has usually cycled through every rule at
least once with nothing left to visibly change, so there's no real
payoff in letting `Settlement.lineage_depth` drive the round count
unbounded. A grandchild many fissions removed still reads as "the same
family of word, further along," not gibberish."""


def _drift_once(term: str) -> str:
    """One rule application — the original single-step behavior,
    factored out so `drift_term` can chain it. Applies the first rule
    (starting from a deterministically-chosen one, then trying the rest
    of `DRIFT_RULES` in order) that actually changes `term`. Only falls
    back to the term unchanged if NONE of the four rules have anything
    to act on (e.g. a term with no vowels and no soften-able
    consonant) — rare, and still a real, deterministic, never-raising
    function."""
    start = DRIFT_RULES.index(_stable_choice(term, DRIFT_RULES))
    for offset in range(len(DRIFT_RULES)):
        rule = DRIFT_RULES[(start + offset) % len(DRIFT_RULES)]
        drifted = _apply_rule(rule, term)
        if drifted is not None:
            return drifted
    return term


def drift_term(term: str, steps: int = 1) -> str:
    """A7 follow-up (roadmap Tier 3 item 18, docs/ROADMAP-2026-07-
    REMAINING.md): what was a single rule application is now a genuine
    RECURSIVE rewrite system — each of `steps` rounds re-seeds the next
    round's rule choice off the STRING PRODUCED BY THE PREVIOUS ROUND
    (`_stable_choice` reads the current term, not the original), so
    compounding drift is a real chain of productions, not the same rule
    applied N times. `steps=1` (the default) reproduces the original
    single-application behavior exactly — every pre-existing call site
    is unaffected. `steps` is clamped to `[1, MAX_DRIFT_STEPS]`, and a
    round that can't change the current string (every rule exhausted)
    simply stops early rather than looping uselessly."""
    term = term.strip().lower()
    if not term:
        return term
    steps = clamp(steps, 1, MAX_DRIFT_STEPS)
    for _ in range(steps):
        drifted = _drift_once(term)
        if drifted == term:
            break
        term = drifted
    return term
