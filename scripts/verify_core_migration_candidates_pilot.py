#!/usr/bin/env python3
"""Tier 5 B10.2 pilot conversion — direct equivalence check.

`Population.core_migration_candidates` used to scan every living agent
in `self.agents` (in list order) filtering to the small `core_agent_
ids` subset. It now iterates `sorted(self.core_agent_ids)` directly and
resolves each via the now-O(1) `Population.get()` (backed by a new
`_agent_by_id` index, see `population.py`'s `__post_init__`/`_adopt`/
the two death/district removal sites).

This script proves the new implementation produces byte-identical
output (same candidate tuples, same relative order) to a direct
reimplementation of the OLD algorithm, across scenarios the 4000-tick
whole-engine soak (`scripts/verify_replay_hash.py`-style before/after
hash comparison, run manually for this pilot) did not exercise on its
own — real fission never happened in that run, so `core_migration_
candidates` never got past its `len(named) < 2` early return there.
Standalone, no unittest — same convention as every other `verify_*.py`
in this repo.
"""
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.agents.agent import Agent
from hearthmind.agents.population import Population
from hearthmind.settlement.buildings import Settlement

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def old_core_migration_candidates(pop: Population, settlements):
    """Direct reimplementation of the pre-conversion algorithm: scan
    `pop.agents` in list order, filter to `core_agent_ids` membership,
    then apply the exact same body as the new version."""
    named = [s for s in settlements if s.name]
    if len(named) < 2:
        return []
    by_id = {s.id: s for s in named}
    candidates = []
    for agent in pop.agents:
        if agent.id not in pop.core_agent_ids:
            continue
        home = by_id.get(agent.settlement_id)
        if home is None or agent.travel_target is not None:
            continue
        found = pop.migration_push_target(agent, home, by_id)
        if found is not None:
            candidates.append((agent, found[0], found[1]))
    return candidates


def make_settlements():
    return [
        Settlement(id=0, name="Alpha"),
        Settlement(id=1, name="Beta"),
    ]


def make_agent(agent_id, settlement_id, bonded_to=None, travel_target=None):
    a = Agent(id=agent_id, name=f"agent{agent_id}", x=0, y=0)
    a.settlement_id = settlement_id
    if bonded_to is not None:
        a.relationships[bonded_to] = 0.9  # above MIGRATION_BOND_THRESHOLD
    if travel_target is not None:
        a.travel_target = travel_target
    return a


def main() -> int:
    settlements = make_settlements()

    # Scenario 1: a real bonded-partner candidate, a non-core agent
    # (must be excluded), a core agent with no push signal (excluded),
    # and a core agent already mid-journey (excluded via travel_target).
    a_bonded = make_agent(1, settlement_id=0)
    a_partner = make_agent(2, settlement_id=1)  # lives in Beta
    a_bonded.relationships[a_partner.id] = 0.9
    a_no_signal = make_agent(3, settlement_id=0)
    a_traveling = make_agent(4, settlement_id=0, bonded_to=a_partner.id, travel_target=(5, 5))

    pop = Population(agents=[a_bonded, a_partner, a_no_signal, a_traveling])
    pop.core_agent_ids = {1, 2, 3, 4}

    old = old_core_migration_candidates(pop, settlements)
    new = pop.core_migration_candidates(settlements)
    check("scenario1: identical candidate lists", old == new)
    check("scenario1: exactly one real candidate (the bonded agent)", len(new) == 1 and new[0][0].id == 1)

    # Scenario 2: a stale core_agent_ids entry (an id that no longer
    # exists in pop.agents at all — the monthly prune hasn't run yet).
    pop2 = Population(agents=[a_bonded, a_partner, a_no_signal])
    pop2.core_agent_ids = {1, 2, 3, 9999}  # 9999 never existed
    old2 = old_core_migration_candidates(pop2, settlements)
    new2 = pop2.core_migration_candidates(settlements)
    check("scenario2: stale id handled identically (no crash, same result)", old2 == new2)

    # Scenario 3: several bonded candidates at once, order must match
    # (relies on self.agents always being id-ascending, and both old
    # and new algorithms iterating in that same relative order —
    # old scans self.agents directly, new scans sorted(core_agent_ids)
    # which for a set of ids present in id-ascending self.agents order
    # produces the identical relative sequence).
    b1 = make_agent(10, settlement_id=0)
    b2 = make_agent(11, settlement_id=1)
    b3 = make_agent(12, settlement_id=0)
    b1.relationships[b2.id] = 0.95
    b3.relationships[b2.id] = 0.95
    pop3 = Population(agents=[b1, b2, b3])
    pop3.core_agent_ids = {10, 11, 12}
    old3 = old_core_migration_candidates(pop3, settlements)
    new3 = pop3.core_migration_candidates(settlements)
    check("scenario3: multi-candidate order matches", old3 == new3)
    check("scenario3: two real candidates in ascending-id order", [c[0].id for c in new3] == [10, 12])

    # Scenario 4: fewer than 2 named settlements -> both algorithms
    # short-circuit to [].
    lone = [Settlement(id=0, name="Alpha")]
    pop4 = Population(agents=[a_bonded, a_partner])
    pop4.core_agent_ids = {1, 2}
    check("scenario4: single-settlement early return", pop4.core_migration_candidates(lone) == [])

    # Scenario 5: empty core_agent_ids -> [].
    pop5 = Population(agents=[a_bonded, a_partner])
    pop5.core_agent_ids = set()
    check("scenario5: empty core cast -> no candidates", pop5.core_migration_candidates(settlements) == [])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
