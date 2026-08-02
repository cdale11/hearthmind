#!/usr/bin/env python3
"""Tier 5 B10.2 fourth pilot conversion — direct equivalence check.

`Settlement.institutions_of_kind(kind)` is the institution-side sibling
of `buildings_of_kind()`/`vehicles_of_kind()` — a new O(1)-amortized
InstitutionKind -> [Institution] index replacing a full `for inst in
settlement.institutions: if inst.kind is not X: continue` scan at six
real call sites in `population.py` (`_maybe_refresh_council`'s COUNCIL
lookup, `_maybe_refresh_guild`'s GUILD loop, `faction_of`,
`council_faction_majority`'s COUNCIL lookup, `family_of`, and
`fission_party`'s FAMILY loop).

`Institution.kind` never mutates in place anywhere in this codebase
(confirmed by direct grep, same as `Vehicle.kind`) — but unlike
vehicles, institutions are appended at FIVE real call sites (family/
council/guild x2/faction founding) plus pruned at one (the
`INSTITUTION_LIST_MAX_STORED` filter-reassignment in `_prune_
institutions`), so this pilot's own real risk is different from the
prior two: getting all SIX invalidation sites right, not just one.

This script proves `institutions_of_kind()` matches a direct
brute-force scan of `settlement.institutions` across founding and
pruning scenarios, standalone, no unittest — same convention as every
other `verify_*.py` in this repo.
"""
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.settlement.buildings import Settlement
from hearthmind.settlement.institutions import Institution, InstitutionKind

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def brute_force(settlement: Settlement, kind: InstitutionKind) -> list[Institution]:
    return [i for i in settlement.institutions if i.kind is kind]


def same_institutions(a: list[Institution], b: list[Institution]) -> bool:
    return [x.id for x in a] == [x.id for x in b]


def found(settlement: Settlement, kind: InstitutionKind, member_ids: set, name: str = "") -> Institution:
    """Mirror the real founding shape (`settlement.institutions.append`
    + explicit invalidation) rather than calling private production
    helpers, so this script exercises the exact same mechanism the
    real call sites use without depending on their internals."""
    inst = Institution(
        id=settlement.next_institution_id, kind=kind, founding_tick=0,
        member_agent_ids=set(member_ids), name=name,
    )
    settlement.next_institution_id += 1
    settlement.institutions.append(inst)
    settlement._institutions_by_kind_index = None  # the real invalidation line
    return inst


def main() -> None:
    stl = Settlement(name="Instituteford", materials=1000.0)

    # 1. Fresh settlement: every bucket empty, matching brute force.
    check(
        "fresh settlement: FAMILY bucket empty and matches brute force",
        stl.institutions_of_kind(InstitutionKind.FAMILY) == [] == brute_force(stl, InstitutionKind.FAMILY),
    )

    # 2. Founding at all five real shapes (family/council/guild x2/faction).
    family1 = found(stl, InstitutionKind.FAMILY, {1, 2})
    council1 = found(stl, InstitutionKind.COUNCIL, {3, 4})
    guild1 = found(stl, InstitutionKind.GUILD, {5}, name="farming")
    family2 = found(stl, InstitutionKind.FAMILY, {6, 7})
    faction1 = found(stl, InstitutionKind.FACTION, {8, 9}, name="the Ridge")
    guild2 = found(stl, InstitutionKind.GUILD, {10}, name="construction")
    check(
        "after founding: FAMILY bucket has both families, real order",
        same_institutions(stl.institutions_of_kind(InstitutionKind.FAMILY), [family1, family2]),
    )
    check(
        "after founding: COUNCIL bucket has only the council",
        same_institutions(stl.institutions_of_kind(InstitutionKind.COUNCIL), [council1]),
    )
    check(
        "after founding: GUILD bucket has both guilds, real order",
        same_institutions(stl.institutions_of_kind(InstitutionKind.GUILD), [guild1, guild2]),
    )
    check(
        "after founding: FACTION bucket has only the faction",
        same_institutions(stl.institutions_of_kind(InstitutionKind.FACTION), [faction1]),
    )

    # 3. Repeated calls with no mutation reuse the cached index.
    cached = stl._institutions_by_kind_index
    _ = stl.institutions_of_kind(InstitutionKind.FAMILY)
    check(
        "repeated calls with no mutation reuse the same cached index",
        stl._institutions_by_kind_index is cached and cached is not None,
    )

    # 4. Pruning (the real `_prune_institutions`-shaped mutation site):
    #    drop one guild, confirm the bucket shrinks and other kinds are
    #    untouched.
    stl.institutions = [i for i in stl.institutions if i.id != guild1.id]
    stl._institutions_by_kind_index = None  # the real pruning site's own invalidation
    check(
        "after pruning: GUILD bucket has only the survivor",
        same_institutions(stl.institutions_of_kind(InstitutionKind.GUILD), [guild2]),
    )
    check(
        "after pruning: an unrelated kind (FAMILY) is unaffected",
        same_institutions(stl.institutions_of_kind(InstitutionKind.FAMILY), [family1, family2]),
    )

    # 5. Negative control: mutate WITHOUT the real invalidation line and
    #    confirm the cache genuinely can go stale — proving the six
    #    invalidation sites are load-bearing, not redundant.
    stale = Settlement(name="Staleburg", materials=1000.0)
    found(stale, InstitutionKind.FAMILY, {1})
    _ = stale.institutions_of_kind(InstitutionKind.FAMILY)  # populate cache
    stale.institutions.append(Institution(id=stale.next_institution_id, kind=InstitutionKind.FAMILY, founding_tick=0))
    stale.next_institution_id += 1
    check(
        "negative control: appending without the real invalidation produces a stale bucket",
        len(stale.institutions_of_kind(InstitutionKind.FAMILY)) == 1 and len(stale.institutions) == 2,
    )
    stale._institutions_by_kind_index = None
    check(
        "negative control, recovered: invalidating afterward fixes it",
        len(stale.institutions_of_kind(InstitutionKind.FAMILY)) == 2,
    )

    # 6. Every real InstitutionKind, cross-checked against brute force.
    for kind in InstitutionKind:
        check(
            f"mixed settlement: {kind.value} bucket matches brute force",
            same_institutions(stl.institutions_of_kind(kind), brute_force(stl, kind)),
        )

    # 7. Load-bearing real-consumer proof: `faction_of`-shaped lookup
    #    (kind filter + membership check) reads correctly through the
    #    new index, matching a brute-force scan of the whole list.
    def faction_of_via_index(agent_id: int) -> "Institution | None":
        for inst in stl.institutions_of_kind(InstitutionKind.FACTION):
            if agent_id in inst.member_agent_ids:
                return inst
        return None

    def faction_of_brute_force(agent_id: int) -> "Institution | None":
        for inst in stl.institutions:
            if inst.kind is InstitutionKind.FACTION and agent_id in inst.member_agent_ids:
                return inst
        return None

    check(
        "faction_of-shaped lookup: member found via index matches brute force",
        faction_of_via_index(8) is faction_of_brute_force(8) is faction1,
    )
    check(
        "faction_of-shaped lookup: non-member returns None via both paths",
        faction_of_via_index(999) is faction_of_brute_force(999) is None,
    )

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
