"""A22 "The Emergence API" (docs/MASTERCHECKLIST-2026-07-22.md, Part A,
Stage I step 1): the deterministic Body's structured sense-stream.

The checklist's own framing: every deterministic subsystem should
expose a stream of *interesting* observations — anomalies, novel
combinations, bottlenecks, unexplained shifts, opportunities — tagged
by which future cognitive pillar would care, rather than raw state a
consumer would have to filter itself. This module is the shared
contract (`Observation` shape, the two closed vocabularies) every
producer writes through; `World.emergence_log` (see its own docstring
in `world/state.py`) is the bounded store, populated by
`SimulationEngine._append_emergence`.

Deliberately a plain-dict shape, not a dataclass — same convention
`World.highlights`/`reflection_notebook` already use for a persisted,
JSON-serialized list of small records, and it keeps `to_dict`/
`from_dict` trivial (no per-type (de)serialization to maintain).

No pillar reads this stream yet — that's Stage II of the roadmap (the
five-pillar refactor). Producing it first, ahead of any consumer, is
deliberate: same "build the sense organ, then the mind that uses it"
sequencing the roadmap itself calls for, and it means the stream's
shape gets exercised (and can be corrected) against real signals
before anything downstream depends on it."""
from __future__ import annotations

OBSERVATION_KINDS: tuple[str, ...] = (
    "anomaly", "novel_combination", "bottleneck", "unexplained_shift", "opportunity",
)
"""The closed set of "what kind of interesting thing is this" tags,
taken directly from det #22's own vocabulary. `anomaly`: a metric off
its rolling norm. `novel_combination`: something new formed from
existing pieces (an invented concept reaching real adoption, a
composite entity). `bottleneck`: a resource/capacity constraint
actually binding (materials too low to build, predation pressure
suppressing reproduction). `unexplained_shift`: a state change without
an obvious single cause (a feud crystallizing, a population swing).
`opportunity`: a threshold crossed that opens something new (an era
advance, a hypothesis becoming supported evidence)."""

PILLARS: tuple[str, ...] = ("humans", "village", "nature", "innovation", "reflection")
"""The closed set of future cognitive pillars (LLM_Pillars.md / Stage
II of the roadmap) an observation is tagged relevant to. An observation
may name more than one — e.g. a family feud is both `humans` (the
people involved) and `village` (the settlement's collective mood/
institutions). Reflection is included as a pillar in its own right (it
already observes the other four's Body state, per `_detect_reflection_
pattern`'s existing docstring) even though most observations won't
name it directly."""


def make_observation(
    observation_id: int, tick: int, kind: str, subsystem: str, summary: str,
    pillars: list[str] | tuple[str, ...], magnitude: float | None = None,
    settlement: str | None = None, data: dict | None = None,
) -> dict:
    """Builds one `emergence_log` entry. Validates `kind`/`pillars`
    against the closed vocabularies above (raises `ValueError`) — this
    is an internal producer-side contract, not user input, so a bad
    call site should fail loudly at the point that wrote it rather than
    silently persist an untagged, unfilterable observation. `magnitude`
    (optional, 0..1) is a rough severity/salience scalar for a future
    consumer to rank by; `None` when a producer has no natural scale
    for it (e.g. a one-off "this just happened" event) rather than a
    fabricated number. `data` is a small structured payload (never
    prose) for a future pillar to read directly — kept separate from
    `summary` (the human/LLM-readable sentence) so a consumer doesn't
    have to parse text to get at the underlying numbers."""
    if kind not in OBSERVATION_KINDS:
        raise ValueError(f"unknown observation kind {kind!r}, expected one of {OBSERVATION_KINDS}")
    bad_pillars = [p for p in pillars if p not in PILLARS]
    if bad_pillars:
        raise ValueError(f"unknown pillar(s) {bad_pillars!r}, expected a subset of {PILLARS}")
    if magnitude is not None:
        magnitude = max(0.0, min(1.0, magnitude))
    return {
        "id": observation_id,
        "tick": tick,
        "kind": kind,
        "subsystem": subsystem,
        "summary": summary,
        "pillars": list(pillars),
        "magnitude": magnitude,
        "settlement": settlement,
        "data": data or {},
    }
