#!/usr/bin/env python3
"""Verifies Phase 8 residual polish, B6 "Reflection as meta-scientist"
(docs/ROADMAP-2026-07-REMAINING.md): `SimulationEngine._reevaluate_
advisory_outcomes` closes the one real, confirmed-still-open gap this
item named — `_review_advisory` was the ONLY place an `advisory_
proposals` entry's `status` ever changed, and nothing ever checked
whether an ACCEPTED piece of advice actually helped afterward.

No unittest, same standalone `@check`-decorator convention as every
sibling `verify_*.py` in this repo. Run:

    python3 scripts/verify_b6_advisory_outcomes.py
"""
from __future__ import annotations

import asyncio
import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.world.state import World

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


class FakeAdapter:
    """The minimal real `LLMAdapter` shape `CognitionRunner._run_gated`
    actually calls -- same technique every other LLM-job verify script
    in this codebase uses (see verify_phase35_w1_naming_workspace.py)."""

    timeout_seconds = 5.0

    def generate_json(
        self, prompt, system=None, capture=None, json_schema=None,
        num_predict_override=None, temperature_override=None,
        reasoning=False, timeout_override=None,
    ) -> dict:
        if capture is not None:
            capture["raw"] = '{"advice": "watch the granaries closely next winter."}'
        return {"advice": "watch the granaries closely next winter."}

    @classmethod
    def build_from_config(cls, config):
        return cls()


def _make_engine(tag: str, seed: int = 5) -> SimulationEngine:
    d = tempfile.mkdtemp()
    db_path = f"{d}/{tag}.sqlite3"
    cfg = Config(db_path=db_path, width=16, height=16, seed=seed, llm_enabled=False, initial_population=4)
    conn = connect(db_path)
    world = World.create_new(cfg)
    return SimulationEngine(conn, cfg, world)


async def _drain_background(eng: SimulationEngine) -> None:
    for _ in range(50):
        if not eng._background_tasks:
            return
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------
# End-to-end: a real advisory produced through the real _schedule_advisory
# pipeline, accepted, then evaluated through the real new method.


async def main_async() -> int:
    eng = _make_engine("e2e")
    eng._cognition_runner.client = FakeAdapter()

    check("check 0: engine starts with an empty advisory_proposals list",
          eng.world.advisory_proposals == [])

    eng._schedule_advisory({"id": 1, "subject": "granary emptiness", "content": "granaries keep running dry."})
    await _drain_background(eng)

    check("check 1: a real advisory was created through the real production apply()",
          len(eng.world.advisory_proposals) == 1)
    advisory = eng.world.advisory_proposals[0]
    check("check 2: the new tracking fields are present and start unevaluated",
          advisory.get("status") == "pending" and advisory.get("outcome") is None
          and advisory.get("outcome_tick") is None and advisory.get("world_model_entry_id") is not None)
    check("check 3: the real advice text landed (not the fallback)",
          advisory["advice"] == "watch the granaries closely next winter.")
    check("check 4: exactly one reflection_pillar.world_model entry was mirrored",
          len(eng.world.reflection_pillar.world_model) == 1)

    # Pending -- never touched by outcome evaluation.
    eng._reevaluate_advisory_outcomes(None)
    check("check 5: a still-pending advisory is untouched by outcome evaluation",
          advisory.get("outcome") is None)

    # Accept it (the real, only, status-changing call site).
    eng._review_advisory(advisory["id"], "accepted")
    check("check 6: _review_advisory really flips status to accepted",
          advisory["status"] == "accepted")

    emergence_before = len(eng.world.emergence_log)
    world_model_before = len(eng.world.reflection_pillar.world_model)
    eng._reevaluate_advisory_outcomes(None)  # no pattern fired this cycle
    check("check 7: an accepted advisory whose pattern did NOT recur gets a real outcome",
          advisory.get("outcome") == "pattern_did_not_recur" and advisory.get("outcome_tick") is not None)
    entry = next(e for e in eng.world.reflection_pillar.world_model if e["id"] == advisory["world_model_entry_id"])
    check("check 8: the SAME pillar world_model entry was revised in place, not duplicated",
          len(eng.world.reflection_pillar.world_model) == world_model_before)
    check("check 9: the revised entry reads observation/confidence 0.7, honestly hedged wording",
          entry["status"] == "observation" and abs(entry["confidence"] - 0.7) < 1e-9
          and "plausible" in entry["belief"] and "not proven" in entry["belief"])
    check("check 10: a real Emergence API observation was appended for the outcome",
          len(eng.world.emergence_log) == emergence_before + 1)

    outcome_tick_first = advisory["outcome_tick"]
    entry_confidence_first = entry["confidence"]
    eng.world.clock.tick_count += 500  # same "advance the clock directly" technique other verify scripts use
    eng._reevaluate_advisory_outcomes(None)
    check("check 11: an already-evaluated advisory is never re-evaluated (idempotent)",
          advisory["outcome_tick"] == outcome_tick_first and entry["confidence"] == entry_confidence_first)

    return 0 if not FAILURES else 1


# ---------------------------------------------------------------------------
# Direct checks against the pure logic, isolated from the LLM-scheduling
# pipeline above (a hand-seeded advisory is just as real an input to the
# method under test -- these check branches the end-to-end path above
# doesn't reach).


def check_recurred_branch() -> bool:
    eng = _make_engine("recurred")
    entry = eng.world.reflection_pillar.upsert_world_model(
        eng.world.clock.tick_count, "wildfire frequency", "seed hypothesis text", 0.5,
        status="hypothesis", source="self_tuning_advisory",
    )
    eng.world.advisory_proposals.append({
        "id": 1, "tick": eng.world.clock.tick_count, "hypothesis_id": 1, "subject": "wildfire frequency",
        "advice": "clear brush near the tree line.", "status": "accepted",
        "world_model_entry_id": entry["id"], "outcome": None, "outcome_tick": None,
    })
    eng._reevaluate_advisory_outcomes({"subject": "wildfire frequency", "description": "still firing far off rate."})
    advisory = eng.world.advisory_proposals[0]
    revised = next(e for e in eng.world.reflection_pillar.world_model if e["id"] == entry["id"])
    return (
        advisory["outcome"] == "recurred_despite_advice"
        and len(eng.world.reflection_pillar.world_model) == 1
        and revised["status"] == "hypothesis" and abs(revised["confidence"] - 0.2) < 1e-9
        and "may not have helped" in revised["belief"]
    )


def check_non_matching_subject_treated_as_did_not_recur() -> bool:
    eng = _make_engine("nonmatch")
    entry = eng.world.reflection_pillar.upsert_world_model(
        eng.world.clock.tick_count, "ontology coherence", "seed text", 0.5, source="self_tuning_advisory",
    )
    eng.world.advisory_proposals.append({
        "id": 1, "tick": eng.world.clock.tick_count, "hypothesis_id": 1, "subject": "ontology coherence",
        "advice": "slow the pace of invention.", "status": "accepted",
        "world_model_entry_id": entry["id"], "outcome": None, "outcome_tick": None,
    })
    # A DIFFERENT pattern fired this cycle -- this advisory's own subject
    # did not recur, so it should read as "pattern_did_not_recur", the
    # same as pattern=None.
    eng._reevaluate_advisory_outcomes({"subject": "wildfire frequency", "description": "unrelated."})
    return eng.world.advisory_proposals[0]["outcome"] == "pattern_did_not_recur"


def check_pending_and_rejected_never_touched() -> bool:
    eng = _make_engine("skip")
    eng.world.advisory_proposals.append({
        "id": 1, "tick": 0, "hypothesis_id": 1, "subject": "food shortage",
        "advice": "build another granary.", "status": "pending",
        "world_model_entry_id": None, "outcome": None, "outcome_tick": None,
    })
    eng.world.advisory_proposals.append({
        "id": 2, "tick": 0, "hypothesis_id": 2, "subject": "food shortage",
        "advice": "different advice.", "status": "rejected",
        "world_model_entry_id": None, "outcome": None, "outcome_tick": None,
    })
    eng._reevaluate_advisory_outcomes({"subject": "food shortage", "description": "recurred."})
    return all(a.get("outcome") is None for a in eng.world.advisory_proposals)


def check_missing_world_model_entry_id_degrades_safely() -> bool:
    eng = _make_engine("missing_entry")
    eng.world.advisory_proposals.append({
        "id": 1, "tick": 0, "hypothesis_id": 1, "subject": "currency shortage",
        "advice": "raise taxes gently.", "status": "accepted",
        "world_model_entry_id": None, "outcome": None, "outcome_tick": None,
    })
    world_model_before = len(eng.world.reflection_pillar.world_model)
    eng._reevaluate_advisory_outcomes(None)
    advisory = eng.world.advisory_proposals[0]
    return (
        advisory["outcome"] == "pattern_did_not_recur"
        and len(eng.world.reflection_pillar.world_model) == world_model_before  # no crash, no phantom entry
    )


def check_legacy_shaped_advisory_dict_is_backfilled_safely() -> bool:
    """A pre-B6 advisory has none of `world_model_entry_id`/`outcome`/
    `outcome_tick` at all -- confirms `.get()` reads degrade correctly
    rather than raising `KeyError`, and that it still gets evaluated
    (a genuinely never-yet-tracked outcome, not a permanent skip)."""
    eng = _make_engine("legacy")
    eng.world.advisory_proposals.append({
        "id": 1, "tick": 0, "hypothesis_id": 1, "subject": "council gridlock",
        "advice": "hold a joint council session.", "status": "accepted",
    })
    eng._reevaluate_advisory_outcomes(None)
    return eng.world.advisory_proposals[0]["outcome"] == "pattern_did_not_recur"


def check_round_trip_preserves_new_fields() -> bool:
    eng = _make_engine("roundtrip")
    entry = eng.world.reflection_pillar.upsert_world_model(
        eng.world.clock.tick_count, "guild decline", "seed text", 0.5, source="self_tuning_advisory",
    )
    eng.world.advisory_proposals.append({
        "id": 1, "tick": eng.world.clock.tick_count, "hypothesis_id": 1, "subject": "guild decline",
        "advice": "recruit a new apprentice.", "status": "accepted",
        "world_model_entry_id": entry["id"], "outcome": None, "outcome_tick": None,
    })
    eng._reevaluate_advisory_outcomes(None)
    restored = World.from_dict(eng.world.to_dict(), eng.config)
    restored_advisory = restored.advisory_proposals[0]
    return (
        restored_advisory["outcome"] == "pattern_did_not_recur"
        and restored_advisory["outcome_tick"] is not None
        and restored_advisory["world_model_entry_id"] == entry["id"]
    )


def main() -> int:
    exit_code = asyncio.run(main_async())

    direct_checks = [
        ("recurred branch: advisory revised in place, hypothesis-status, lowered confidence, honest wording",
         check_recurred_branch),
        ("a different pattern firing this cycle reads the same as no pattern (did not recur)",
         check_non_matching_subject_treated_as_did_not_recur),
        ("pending/rejected advisories are never evaluated",
         check_pending_and_rejected_never_touched),
        ("a missing world_model_entry_id degrades safely (outcome still set, no phantom entry)",
         check_missing_world_model_entry_id_degrades_safely),
        ("a legacy-shaped advisory dict (no new keys at all) is backfilled and evaluated, not crashed on",
         check_legacy_shaped_advisory_dict_is_backfilled_safely),
        ("World.to_dict()/from_dict() round-trips every new field",
         check_round_trip_preserves_new_fields),
    ]
    for label, fn in direct_checks:
        try:
            check(label, fn())
        except Exception as exc:  # noqa: BLE001 -- report as a failed check, not a crash
            check(f"{label} (raised {exc!r})", False)

    if FAILURES:
        exit_code = 1
    print()
    print(f"{len(FAILURES)} failure(s)." if FAILURES else "All checks passed.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
