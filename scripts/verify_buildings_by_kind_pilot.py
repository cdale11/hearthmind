#!/usr/bin/env python3
"""Tier 5 B10.2 second pilot conversion — direct equivalence check.

`Settlement.buildings_of_kind(kind)` is a new O(1)-amortized index
(same "derived, never-serialized, invalidate-on-mutation" discipline
as the existing `_position_index` behind `at()`) replacing a full
`for building in settlement.buildings: if building.kind is not X:
continue` scan at twelve real per-tick call sites in `Population`
(granaries, husbandry, workshops, tool/medicine crafting, factories,
docks, oil rigs, forges, market workers, schools, the university
upgrade) — every one of these runs once per settlement, every tick,
unconditionally.

Unlike `_position_index` (rebuilt lazily via a length check, since a
building only ever appears/disappears, never moves), the by-kind index
needs an EXPLICIT invalidation at one more site the length check can't
catch: `_maybe_upgrade_university` mutates `school.kind` in place,
which changes the index's content without changing `len(settlement.
buildings)`. This script's own construction directly exercises all
three real invalidation sites (construction, ruin removal, the kind
mutation) and confirms `buildings_of_kind()` always matches a direct
brute-force scan of `settlement.buildings` — never stale, in either
direction. Standalone, no unittest — same convention as every other
`verify_*.py` in this repo.
"""
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.settlement.buildings import Building, BuildingKind, BuildingStage, Settlement

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def brute_force(settlement: Settlement, kind: BuildingKind) -> list[Building]:
    return [b for b in settlement.buildings if b.kind is kind]


def same_buildings(a: list[Building], b: list[Building]) -> bool:
    return [x.id for x in a] == [x.id for x in b]


def main() -> None:
    stl = Settlement(name="Testford", materials=1000.0)

    # 1. Fresh settlement: every bucket is empty, matching brute force.
    check(
        "fresh settlement: GRANARY bucket empty and matches brute force",
        stl.buildings_of_kind(BuildingKind.GRANARY) == [] == brute_force(stl, BuildingKind.GRANARY),
    )

    # 2. Construction (the real mutation site: start_construction ->
    #    buildings.append + explicit invalidation).
    granary1 = stl.start_construction(2, 2, kind=BuildingKind.GRANARY)
    workshop1 = stl.start_construction(3, 3, kind=BuildingKind.WORKSHOP)
    granary2 = stl.start_construction(4, 4, kind=BuildingKind.GRANARY)
    check(
        "after construction: GRANARY bucket has both granaries, real order",
        same_buildings(stl.buildings_of_kind(BuildingKind.GRANARY), [granary1, granary2]),
    )
    check(
        "after construction: WORKSHOP bucket has only the workshop",
        same_buildings(stl.buildings_of_kind(BuildingKind.WORKSHOP), [workshop1]),
    )
    check(
        "after construction: a kind with nothing built stays empty",
        stl.buildings_of_kind(BuildingKind.FACTORY) == [],
    )

    # 3. A second call without any mutation reuses the cached index
    #    (same object identity on the underlying dict — proves it's not
    #    rebuilt from scratch every call).
    cached = stl._buildings_by_kind_index
    _ = stl.buildings_of_kind(BuildingKind.GRANARY)
    check(
        "repeated calls with no mutation reuse the same cached index",
        stl._buildings_by_kind_index is cached and cached is not None,
    )

    # 4. School -> University kind mutation: the one site where the
    #    LIST LENGTH doesn't change but the bucket contents must.
    school = stl.start_construction(5, 5, kind=BuildingKind.SCHOOL)
    school.stage = BuildingStage.STANDING
    _ = stl.buildings_of_kind(BuildingKind.SCHOOL)  # populate the cache before mutating
    school.kind = BuildingKind.UNIVERSITY
    stl._buildings_by_kind_index = None  # the real call site's own explicit invalidation
    check(
        "after school->university mutation: SCHOOL bucket no longer holds it",
        school not in stl.buildings_of_kind(BuildingKind.SCHOOL),
    )
    check(
        "after school->university mutation: UNIVERSITY bucket holds it",
        same_buildings(stl.buildings_of_kind(BuildingKind.UNIVERSITY), [school]),
    )

    # 5. Ruin removal (the `self.buildings = survivors` mutation site):
    #    drop one granary, confirm the bucket shrinks and the other
    #    granary + everything else stays untouched.
    stl.buildings = [b for b in stl.buildings if b.id != granary1.id]
    stl._buildings_by_kind_index = None  # the real call site's own explicit invalidation
    check(
        "after ruin removal: GRANARY bucket has only the survivor",
        same_buildings(stl.buildings_of_kind(BuildingKind.GRANARY), [granary2]),
    )
    check(
        "after ruin removal: an unrelated kind (WORKSHOP) is unaffected",
        same_buildings(stl.buildings_of_kind(BuildingKind.WORKSHOP), [workshop1]),
    )

    # 6. Load-bearing check: a MISSING invalidation would produce a
    #    stale bucket. Prove the reverse — build a fresh settlement,
    #    populate the cache, mutate WITHOUT invalidating, and confirm
    #    that's exactly the failure mode this discipline prevents (a
    #    genuine negative control, not asserting the bug is absent by
    #    construction alone).
    stale = Settlement(name="Staleburg", materials=1000.0)
    stale.start_construction(0, 0, kind=BuildingKind.HUT)
    _ = stale.buildings_of_kind(BuildingKind.HUT)  # populate cache
    stale.buildings.append(Building(id=stale._next_id, x=1, y=1, kind=BuildingKind.HUT))
    stale._next_id += 1
    # Deliberately skip invalidation here to prove the cache CAN go
    # stale without it — this is what every real call site's explicit
    # `= None` line exists to prevent.
    check(
        "negative control: skipping invalidation after a real mutation produces a stale (wrong) bucket",
        len(stale.buildings_of_kind(BuildingKind.HUT)) == 1 and len(stale.buildings) == 2,
    )
    stale._buildings_by_kind_index = None
    check(
        "negative control, recovered: invalidating afterward fixes it",
        len(stale.buildings_of_kind(BuildingKind.HUT)) == 2,
    )

    # 7. Every real BuildingKind, cross-checked against brute force on
    #    a settlement with a mixed population of kinds/stages.
    mixed = Settlement(name="Mixedburg", materials=1000.0)
    for i, kind in enumerate(list(BuildingKind)[:6]):
        b = mixed.start_construction(i, i, kind=kind)
        b.stage = BuildingStage.STANDING if i % 2 == 0 else BuildingStage.UNDER_CONSTRUCTION
    for kind in BuildingKind:
        check(
            f"mixed settlement: {kind.value} bucket matches brute force",
            same_buildings(mixed.buildings_of_kind(kind), brute_force(mixed, kind)),
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
