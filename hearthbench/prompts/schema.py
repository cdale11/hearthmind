"""HearthBench A3.2/A3.3 — the declarative test-definition schema.

"Adding a benchmark category = adding data + a scorer, never touching
the runner." `TestCase` is the literal shape the checklist specs:

    TestCase: id, category, fixture_ref, system_prompt, schema_ref,
              scorers[], weight, tags[], turns[] (multi-turn),
              expected_invariants[] (grounding facts that must hold),
              seed

A3.3's multi-turn/stateful cases are `turns: list[Turn]` — no separate
mechanism needed, a single-turn case is simply `turns` of length one
(or empty, using `system_prompt`/`fixture_ref` directly). `Turn`
itself carries `injected_fact`/`expects_recall_of` so a future A11
runner can actually inject state between turns (turn 1 establishes a
fact, turn 7 tests recall of it, turn 12 offers a contradiction — the
checklist's own worked example) without this schema knowing anything
about HOW a runner will execute that — purely declarative data.

Nothing here executes a test case (that's A11's job, not built yet) —
`render_turn_sequence` is the one piece of real logic this module
owns: a pure function turning a `TestCase`'s `turns` into the ordered
message sequence a runner would actually send, so the "what would this
case ask" question is answerable and testable today, independent of
whether a runner exists yet.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Turn:
    """One step of a multi-turn case. `content` is what gets sent to
    the model this turn (may reference a previously-injected fact in
    its own text — composing that reference is the test AUTHOR's job,
    this dataclass just carries the data). `injected_fact`/`expects_
    recall_of` are optional bookkeeping a scorer can read without
    having to parse `content` itself."""

    index: int
    content: str
    injected_fact: str | None = None
    """A fact this turn establishes (e.g. "the agent's name is Mira")
    — recorded here, not inferred from `content`, so a later turn's
    `expects_recall_of` can reference it by exact string."""
    expects_recall_of: str | None = None
    """Names an earlier turn's `injected_fact` this turn's response
    should correctly reference — the mechanism behind "turn 7 tests
    recall of turn 1's fact." `None` for a turn that establishes new
    state or offers a contradiction rather than testing recall."""
    offers_contradiction: bool = False
    """Marks a turn that deliberately states something inconsistent
    with an earlier `injected_fact` — a personality-stability/
    grounding scorer's own signal to check whether the model noticed,
    per the checklist's own worked example ("turn 12 offers a
    contradiction")."""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Turn":
        return cls(
            index=data["index"], content=data.get("content", ""),
            injected_fact=data.get("injected_fact"), expects_recall_of=data.get("expects_recall_of"),
            offers_contradiction=bool(data.get("offers_contradiction", False)),
        )


@dataclass
class TestCase:
    """The literal checklist shape. `fixture_ref` names a
    `FixtureExample.fixture_id` from a specific pack version (resolved
    by whatever loads the pack, not stored here — a `TestCase` stays a
    plain, portable data record with no live file-path dependency).
    `scorers`/`schema_ref` are string identifiers (a future A4 scorer
    registry / `hearthmind.llm.json_schemas` task key) — this module
    doesn't import either, keeping the schema itself free of any
    dependency on how scoring or validation actually work."""

    id: str
    category: str
    fixture_ref: str | None = None
    system_prompt: str | None = None
    schema_ref: str | None = None
    scorers: list = field(default_factory=list)
    weight: float = 1.0
    tags: list = field(default_factory=list)
    turns: list = field(default_factory=list)
    """`list[Turn]` — empty for an ordinary single-shot case (the
    common shape today; `fixture_ref`/`system_prompt` alone describe
    it)."""
    expected_invariants: list = field(default_factory=list)
    """Grounding facts that must hold across the whole case (e.g. "the
    settlement name must never change mid-conversation") — a list of
    plain-string assertions a future A4.1 grounding scorer checks
    against, not evaluated here."""
    seed: int | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["turns"] = [t.to_dict() if isinstance(t, Turn) else t for t in self.turns]
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "TestCase":
        turns = [Turn.from_dict(t) if not isinstance(t, Turn) else t for t in data.get("turns") or []]
        return cls(
            id=data["id"], category=data["category"], fixture_ref=data.get("fixture_ref"),
            system_prompt=data.get("system_prompt"), schema_ref=data.get("schema_ref"),
            scorers=list(data.get("scorers") or []), weight=float(data.get("weight", 1.0)),
            tags=list(data.get("tags") or []), turns=turns,
            expected_invariants=list(data.get("expected_invariants") or []), seed=data.get("seed"),
        )


def test_case_from_fixture(
    fixture, category: str, *, scorers=(), weight: float = 1.0, tags=(),
    schema_ref: str | None = None, case_id: str | None = None,
) -> TestCase:
    """A3.2's own "adding a benchmark category = adding data + a
    scorer" made real: given a `FixtureExample` (data, from A3.1) and
    a scorer id list (data, from A4's future registry), returns a
    complete, runnable `TestCase` — no runner code touched. `fixture`
    is duck-typed (any object with `.fixture_id`/`.task`/`.system_
    prompt`) rather than importing `fixtures.FixtureExample` directly,
    so this function has no hard dependency on that module's own
    shape evolving."""
    return TestCase(
        id=case_id or f"{category}:{fixture.fixture_id}",
        category=category, fixture_ref=fixture.fixture_id,
        system_prompt=fixture.system_prompt, schema_ref=schema_ref,
        scorers=list(scorers), weight=weight, tags=list(tags),
    )


def render_turn_sequence(test_case: TestCase) -> list[dict]:
    """A3.3's real piece of logic: walks `test_case.turns` in index
    order and returns the ordered `[{"index", "content", "context"},
    ...]` sequence a runner would actually send — `context` accumulates
    every `injected_fact` established SO FAR (not just this turn's own),
    since a later turn's recall/contradiction check needs the full
    running fact set, not only its own immediate predecessor. Pure and
    stateless — the same `test_case` always renders the same sequence,
    regardless of what any runner does with it. An empty/no-`turns`
    case renders to an empty list (a single-shot case has nothing to
    sequence — its `system_prompt`/`fixture_ref` already say
    everything)."""
    rendered: list[dict] = []
    facts_so_far: dict[str, str] = {}
    for turn in sorted(test_case.turns, key=lambda t: t.index):
        rendered.append({
            "index": turn.index,
            "content": turn.content,
            "context": dict(facts_so_far),
            "expects_recall_of": turn.expects_recall_of,
            "offers_contradiction": turn.offers_contradiction,
        })
        if turn.injected_fact is not None:
            facts_so_far[f"turn_{turn.index}"] = turn.injected_fact
    return rendered
