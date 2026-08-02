#!/usr/bin/env python3
"""Tier 5 B10.2 third pilot conversion — direct equivalence check.

`Settlement.vehicles_of_kind(kind)` is the vehicle-side sibling of the
buildings-side `buildings_of_kind()` (v1.34.190) — a new O(1)-amortized
VehicleKind -> [Vehicle] index replacing a full `for v in settlement.
vehicles: if v.kind is not X: continue` scan at real per-tick/per-
gather-event call sites (`_haul_factor`, `_raft_factor`, `_agent_mount`,
`_maybe_assign_mounts`, `_wear_carts`, `_wear_rafts`, and
`Settlement._vehicle_summary()`, itself called from `Settlement.
summary()` — the same method whose measured per-tick cost is recorded
directly in `simulation/engine.py`'s own comment on a nearby call site:
"summary() ... is expensive enough that calling it every tick for
every settlement measurably slowed the tick loop").

Genuinely SIMPLER than the buildings-side index: `Vehicle.kind` never
mutates in place anywhere in this codebase (confirmed by direct grep
before this pilot began) and `Settlement.vehicles` is append-only — no
removal path exists anywhere. So `start_vehicle`'s own explicit
invalidation is the ONLY real mutation site, unlike buildings' three
(construction, ruin removal, the school->university kind mutation).

This script proves `vehicles_of_kind()` matches a direct brute-force
scan of `settlement.vehicles` across construction and cache-reuse
scenarios, standalone, no unittest — same convention as every other
`verify_*.py` in this repo.
"""
import itertools
import sys

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.settlement.buildings import Settlement
from hearthmind.settlement.vehicles import PERSONAL_VEHICLE_KINDS, Vehicle, VehicleKind, VehicleStage

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def brute_force(settlement: Settlement, kind: VehicleKind) -> list[Vehicle]:
    return [v for v in settlement.vehicles if v.kind is kind]


def same_vehicles(a: list[Vehicle], b: list[Vehicle]) -> bool:
    return [x.id for x in a] == [x.id for x in b]


def main() -> None:
    stl = Settlement(name="Cartford", materials=1000.0)

    # 1. Fresh settlement: every bucket empty, matching brute force.
    check(
        "fresh settlement: CART bucket empty and matches brute force",
        stl.vehicles_of_kind(VehicleKind.CART) == [] == brute_force(stl, VehicleKind.CART),
    )

    # 2. Construction (the real, and only, mutation site).
    cart1 = stl.start_vehicle(2, 2, kind=VehicleKind.CART)
    mount1 = stl.start_vehicle(3, 3, kind=VehicleKind.MOUNT)
    cart2 = stl.start_vehicle(4, 4, kind=VehicleKind.CART)
    check(
        "after construction: CART bucket has both carts, real order",
        same_vehicles(stl.vehicles_of_kind(VehicleKind.CART), [cart1, cart2]),
    )
    check(
        "after construction: MOUNT bucket has only the mount",
        same_vehicles(stl.vehicles_of_kind(VehicleKind.MOUNT), [mount1]),
    )
    check(
        "after construction: a kind with nothing built stays empty",
        stl.vehicles_of_kind(VehicleKind.AUTOMOBILE) == [],
    )

    # 3. Repeated calls with no mutation reuse the cached index.
    cached = stl._vehicles_by_kind_index
    _ = stl.vehicles_of_kind(VehicleKind.CART)
    check(
        "repeated calls with no mutation reuse the same cached index",
        stl._vehicles_by_kind_index is cached and cached is not None,
    )

    # 4. A further construction invalidates and correctly extends
    #    the bucket, proving the real invalidation site works.
    cart3 = stl.start_vehicle(5, 5, kind=VehicleKind.CART)
    check(
        "after a second construction: CART bucket includes the new cart",
        same_vehicles(stl.vehicles_of_kind(VehicleKind.CART), [cart1, cart2, cart3]),
    )

    # 5. Negative control: mirrors the buildings pilot's own discipline
    #    — mutate WITHOUT going through start_vehicle (bypassing the
    #    real invalidation site) and confirm the cache genuinely can go
    #    stale, so the invalidation line is proven load-bearing rather
    #    than redundant.
    stale = Settlement(name="Staleburg", materials=1000.0)
    stale.start_vehicle(0, 0, kind=VehicleKind.RAFT)
    _ = stale.vehicles_of_kind(VehicleKind.RAFT)  # populate cache
    stale.vehicles.append(Vehicle(id=stale._next_vehicle_id, x=1, y=1, kind=VehicleKind.RAFT))
    stale._next_vehicle_id += 1
    check(
        "negative control: appending without start_vehicle's own invalidation produces a stale bucket",
        len(stale.vehicles_of_kind(VehicleKind.RAFT)) == 1 and len(stale.vehicles) == 2,
    )
    stale._vehicles_by_kind_index = None
    check(
        "negative control, recovered: invalidating afterward fixes it",
        len(stale.vehicles_of_kind(VehicleKind.RAFT)) == 2,
    )

    # 6. Every real VehicleKind, cross-checked against brute force on a
    #    settlement with a mixed population of kinds/stages.
    mixed = Settlement(name="Mixedburg", materials=1000.0)
    for i, kind in enumerate(list(VehicleKind)):
        v = mixed.start_vehicle(i, i, kind=kind)
        v.stage = VehicleStage.READY if i % 2 == 0 else VehicleStage.BUILDING
    for kind in VehicleKind:
        check(
            f"mixed settlement: {kind.value} bucket matches brute force",
            same_vehicles(mixed.vehicles_of_kind(kind), brute_force(mixed, kind)),
        )

    # 7. Load-bearing real-consumer proof: `_agent_mount`-shaped lookup
    #    (personal-vehicle kinds, READY + assigned) reads correctly
    #    through the new index composed via itertools.chain, matching
    #    a brute-force scan of the whole vehicle list.
    personal = Settlement(name="Personalburg", materials=1000.0)
    m = personal.start_vehicle(0, 0, kind=VehicleKind.MOUNT)
    m.stage = VehicleStage.READY
    m.assigned_agent_id = 7
    a = personal.start_vehicle(1, 1, kind=VehicleKind.AUTOMOBILE)
    a.stage = VehicleStage.READY
    a.assigned_agent_id = 8
    personal.start_vehicle(2, 2, kind=VehicleKind.CART)  # not personal, must be excluded
    via_index = list(
        itertools.chain.from_iterable(personal.vehicles_of_kind(k) for k in PERSONAL_VEHICLE_KINDS)
    )
    via_brute_force = [v for v in personal.vehicles if v.kind in PERSONAL_VEHICLE_KINDS]
    check(
        "PERSONAL_VEHICLE_KINDS chain matches brute-force filter, cart excluded",
        same_vehicles(via_index, via_brute_force) and all(v.kind is not VehicleKind.CART for v in via_index),
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
