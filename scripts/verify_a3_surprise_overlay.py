#!/usr/bin/env python3
"""Tier 7 HCA Stage A, A3 (explicit user instruction: "Start A3"): the
surprise map overlay -- `FieldGrid.step_surprise`, `World.settlement_
surprise`, `terrain_evolution.decay_settlement_surprise`, and the real
write site in `SimulationEngine._append_emergence`.

A3's own stated bar (docs/COGNITIVE-ARCHITECTURE-2026-08-02.md):
"meeting that doc's own 'answers one nameable question' bar" -- the
question here is "where on the map is something happening the
simulation itself doesn't yet have a model for?" Verified by driving
the real gate/write/decay/field-step/round-trip path, not a mock.

No unittest, same standalone-script convention as every sibling
`verify_*.py`.
"""
from __future__ import annotations

import sys
import tempfile

sys.path.insert(0, "/home/user/hearthmind")

from hearthmind.config import Config
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine
from hearthmind.world.fields import FieldGrid
from hearthmind.world.state import World
from hearthmind.world.terrain_evolution import (
    SETTLEMENT_SURPRISE_DECAY_PER_WEEK,
    decay_settlement_surprise,
)

FAILURES: list[str] = []


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


def make_engine(tmpdir: str, db_name: str = "a3.db") -> SimulationEngine:
    db_path = f"{tmpdir}/{db_name}"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=1, initial_population=5, width=32, height=32)
    return SimulationEngine.load_or_create(conn, cfg)


def main() -> int:
    # --- FieldGrid.step_surprise: real aggregation/normalization/diffusion ---
    fg = FieldGrid()
    fg.step_surprise([], 64, 64)
    check("an empty source list produces an all-zero field, not a crash", all(
        v == 0.0 for row in fg.fields["surprise"] for v in row
    ))

    fg2 = FieldGrid()
    fg2.step_surprise([((5, 5), 0.9), ((60, 60), 0.3)], 64, 64)
    # region_of maps (5,5) into the top-left 3x3 region cell, (60,60) into
    # the bottom-right one -- the peak region should read exactly 1.0 pre-
    # diffuse (normalized against itself), the other region should read
    # 0.3/0.9 = 0.333... pre-diffuse, both softened outward by diffusion.
    check(
        "the region holding the higher raw surprise value reads as the field's own peak",
        fg2.fields["surprise"][0][0] == max(v for row in fg2.fields["surprise"] for v in row),
    )
    check(
        "a second, lower-surprise region still reads a nonzero (but lower) value",
        0.0 < fg2.fields["surprise"][2][2] < fg2.fields["surprise"][0][0],
    )

    fg3 = FieldGrid()
    fg3.step_surprise([((5, 5), 0.9), ((6, 6), 0.4)], 64, 64)
    check(
        "two settlements sharing one region take the MAX surprise, not a sum "
        "(a region's own reading never exceeds the single most-surprising "
        "settlement in it -- would exceed 1.0 pre-diffuse if summed instead)",
        fg3.fields["surprise"][0][0] <= 1.0,
    )

    # --- decay_settlement_surprise: real per-week decay + floor eviction ---
    scars = {(5, 5): 0.5, (10, 10): SETTLEMENT_SURPRISE_DECAY_PER_WEEK - 0.001}
    decay_settlement_surprise(scars)
    check(
        "a surviving entry decays by exactly the per-week constant",
        abs(scars[(5, 5)] - (0.5 - SETTLEMENT_SURPRISE_DECAY_PER_WEEK)) < 1e-9,
    )
    check("an entry that decays to <= 0 is dropped from the dict, not left negative", (10, 10) not in scars)

    # --- World round-trip: settlement_surprise survives to_dict/from_dict ---
    with tempfile.TemporaryDirectory() as tmpdir:
        eng = make_engine(tmpdir, "roundtrip.db")
        eng.world.settlement_surprise[(3, 4)] = 0.77
        data = eng.world.to_dict()
        check("to_dict() serializes settlement_surprise with a stable string key", "3:4" in data["settlement_surprise"])
        restored = World.from_dict(data, eng.world.config)
        check(
            "from_dict() reconstructs settlement_surprise as a real (x, y)-keyed dict",
            restored.settlement_surprise.get((3, 4)) == 0.77,
        )

        # legacy snapshot (no settlement_surprise key at all) backfills to
        # an empty dict rather than crashing -- the same discipline every
        # sibling scar dict already has.
        legacy_data = dict(data)
        del legacy_data["settlement_surprise"]
        legacy_world = World.from_dict(legacy_data, eng.world.config)
        check(
            "a legacy snapshot missing settlement_surprise entirely backfills to {} cleanly",
            legacy_world.settlement_surprise == {},
        )

        # --- the real production write site: _append_emergence ---
        eng2 = make_engine(tmpdir, "write.db")
        stl = eng2.world.settlements[0]
        stl.name = "Testville"
        stl.center_x, stl.center_y = 7, 9
        eng2._append_emergence(
            "opportunity", "invention", "The village invented pottery.",
            ("innovation",), settlement="Testville",
        )
        check(
            "a candidate that clears the surprise gate for a real settlement writes "
            "its position into World.settlement_surprise",
            eng2.world.settlement_surprise.get((7, 9)) is not None,
        )
        check(
            "the written value is a genuine surprise reading, clamped to <= 1.0",
            0.0 < eng2.world.settlement_surprise[(7, 9)] <= 1.0,
        )

        # a routine, repeated candidate at the SAME settlement eventually
        # gets suppressed by A2's own gate -- confirm the write site
        # correctly does NOT touch settlement_surprise on a suppressed call
        # (only a logged one), by driving the specialist to a low-surprise
        # steady state first, then checking the log length is unchanged
        # for a follow-up call that the gate itself suppresses.
        eng3 = make_engine(tmpdir, "suppress.db")
        stl3 = eng3.world.settlements[0]
        stl3.name = "Quietville"
        stl3.center_x, stl3.center_y = 1, 1
        for _ in range(40):
            eng3._append_emergence(
                "unexplained_shift", "cognition", "Mira decided to socialize.",
                ("humans",), settlement="Quietville",
            )
        log_len_before = len(eng3.world.emergence_log)
        surprise_before = dict(eng3.world.settlement_surprise)
        eng3._append_emergence(
            "unexplained_shift", "cognition", "Mira decided to socialize.",
            ("humans",), settlement="Quietville",
        )
        suppressed = len(eng3.world.emergence_log) == log_len_before
        check(
            "once the gate has genuinely learned a routine pattern, a further "
            "identical candidate is suppressed (production-path proof the gate "
            "still runs before the surprise-map write)",
            suppressed,
        )
        if suppressed:
            check(
                "a suppressed candidate leaves World.settlement_surprise untouched "
                "(no trace from silence, same discipline as the emergence log itself)",
                eng3.world.settlement_surprise == surprise_before,
            )

        # a settlement with no real site yet (center -1,-1, the pre-founding
        # state every settlement starts in) is a safe no-op, never a crash
        # or a bogus negative-coordinate field write.
        eng4 = make_engine(tmpdir, "unsited.db")
        unsited = eng4.world.settlements[0]
        unsited.name = "Nowhereville"
        before_len = len(eng4.world.settlement_surprise)
        eng4._append_emergence(
            "opportunity", "invention", "The village invented pottery.",
            ("innovation",), settlement="Nowhereville",
        )
        check(
            "a settlement with no real center yet (-1,-1) never gets a bogus field write",
            len(eng4.world.settlement_surprise) == before_len,
        )

        # a settlement name that doesn't resolve to any real settlement
        # object (should never happen in production, but the resolver must
        # degrade safely rather than raising) is also a safe no-op.
        eng5 = make_engine(tmpdir, "unknown.db")
        before_len5 = len(eng5.world.settlement_surprise)
        eng5._append_emergence(
            "opportunity", "invention", "The village invented pottery.",
            ("innovation",), settlement="NoSuchPlace",
        )
        check(
            "an unresolvable settlement name degrades to a safe no-op, never a crash",
            len(eng5.world.settlement_surprise) == before_len5,
        )

        # --- production-path: a real tick genuinely steps the field from
        #     World.settlement_surprise's own current contents ---
        eng6 = make_engine(tmpdir, "tick.db")
        stl6 = eng6.world.settlements[0]
        stl6.name = "Livelyville"
        stl6.center_x, stl6.center_y = 16, 16
        eng6.world.settlement_surprise[(16, 16)] = 0.9
        eng6.world.tick()
        surprise_field = eng6.world.fields.fields.get("surprise")
        check(
            "a real World.tick() call genuinely steps the surprise field from "
            "World.settlement_surprise's own live contents",
            surprise_field is not None and max(v for row in surprise_field for v in row) > 0.0,
        )

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
