#!/usr/bin/env python3
"""Full-state-diffing native-module verification harness (R8 prereq).

Every native module since v0.72.0 has been verified via a cumulative-
event-hash soak (`World.last_life_events` accumulated across ticks,
hashed, compared native-vs-Python-fallback). That soak proves the
*narrated* consequences of a tick match, but a state field that never
produces a life event (e.g. a farm plot's raw `growth` float between
0.0 and readiness, an agent's `energy` between whole-number thresholds)
could theoretically drift without ever showing up in it.

This script instead hashes the FULL `World.to_dict()` snapshot every
tick — the same serialization `World.from_dict`/persistence already
trusts as complete — so nothing in scope for future object-graph work
(R8: porting `Agent`/`Settlement`/`Population`/the terrain grid itself)
can silently diverge without a save/load-equivalent state comparison
catching it. Deliberately a standalone script, not a pytest suite —
CLAUDE.md's standing rule is that the automated test suite is unused;
verification is live diagnostic reports plus ad-hoc scripts run in this
environment, and this is one of those scripts, just committed so it's
reusable rather than re-typed into a shell each session.

Usage: python3 scripts/verify_native_soak.py [--ticks N] [--seeds S,S,S]
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hearthmind.config import Config  # noqa: E402
from hearthmind.persistence.database import connect  # noqa: E402
from hearthmind.simulation.engine import SimulationEngine  # noqa: E402

import hearthmind.agents.agent as _agent  # noqa: E402
import hearthmind.agents.agent_store as _agent_store  # noqa: E402
import hearthmind.agents.population as _population  # noqa: E402
import hearthmind.economy.farms as _farms  # noqa: E402
import hearthmind.settlement.buildings as _buildings  # noqa: E402
import hearthmind.time_system as _time_system  # noqa: E402
import hearthmind.world.disasters as _disasters  # noqa: E402
import hearthmind.world.hydrology as _hydrology  # noqa: E402
import hearthmind.world.hydrology_field as _hydrology_field  # noqa: E402
import hearthmind.world.ca_operators as _ca_operators  # noqa: E402
import hearthmind.world.resources as _resources  # noqa: E402
import hearthmind.world.roads as _roads  # noqa: E402
import hearthmind.world.terrain as _terrain  # noqa: E402
import hearthmind.world.terrain_evolution as _terrain_evolution  # noqa: E402
import hearthmind.world.weather as _weather  # noqa: E402
import hearthmind.world.wildlife as _wildlife  # noqa: E402

# (module, attribute_name) for every native fast-path toggle in the
# codebase — kept as one list here so a new module only needs one new
# entry, not a bespoke soak script. See each module's own `try/except
# ImportError` import block for what each name binds when present.
_NATIVE_TOGGLES = [
    (_disasters, "_native_wilt_farms_tick"),
    (_disasters, "_native_flat_damage_tick"),
    (_disasters, "_native_roll_passes_tick"),
    (_hydrology, "_native_bounded_random_walk_step"),
    (_resources, "_NativeResourceIndex"),
    (_resources, "_native_tick"),
    (_terrain_evolution, "_native_climate_drift_batch"),
    (_terrain_evolution, "_native_maybe_reclaim_tick"),
    (_terrain_evolution, "_native_bounded_random_walk_step"),
    (_terrain_evolution, "_native_roll_passes_tick"),
    (_terrain, "_NativeTerrainGridImpl"),
    (_weather, "_native_compute_weather_blend"),
    (_wildlife, "_NativeGrazerHerdIndex"),
    (_population, "_NativeTerrainMaterialIndex"),
    (_population, "_NativeAgentPositionIndex"),
    (_population, "_NativeNeedsConstants"),
    (_population, "_native_update_needs"),
    (_population, "_native_predator_kill_chance"),
    (_buildings, "_native_building_decay_tick"),
    (_buildings, "_native_vehicle_decay_tick"),
    (_farms, "_native_farm_grid_tick"),
    (_time_system, "_native_sim_clock_advance"),
    # v0.75.0: nulling this makes Population build no AgentStore, so every
    # Agent keeps its 12 scalar fields in plain locals — the pre-v0.75.0
    # dataclass path. native=True routes them through cpp AgentTable.
    (_agent_store, "_NativeAgentTable"),
    # v0.76.2: Phase I's per-tick emotion decay (cpp/src/emotion_decay.cpp).
    (_agent, "_native_decay_emotions"),
    (_agent, "_NativeEmotionState"),
    # v0.85.6: relationship decay/colocation-gain scalar math
    # (cpp/src/relationship_step.cpp).
    (_population, "_native_relationship_decay_step"),
    (_population, "_native_relationship_gain_step"),
    # v0.86.1: road wear gain/decay scalar math (cpp/src/road_wear.cpp).
    (_roads, "_native_road_wear_gain_step"),
    (_roads, "_native_road_wear_decay_step"),
    # v0.86.4: grazer-branch scalar math (cpp/src/wildlife_step.cpp).
    (_wildlife, "_native_grazer_tick_step"),
    # v0.88.0 (v1 audit fix): soil fertility deplete/recover scalar math
    # (cpp/src/soil_fertility.cpp).
    (_farms, "_native_soil_fertility_deplete_step"),
    (_farms, "_native_soil_fertility_recover_step"),
    # v0.88.0 (v1 audit fix): mining scar gain/decay scalar math
    # (cpp/src/mining_scars.cpp).
    (_terrain_evolution, "_native_mining_scar_gain_step"),
    (_terrain_evolution, "_native_mining_scar_decay_step"),
    # v1.34.207: A14's five per-agent scalar-drift passes
    # (cpp/src/biology_ticks.cpp).
    (_population, "_NativeBiologyConstants"),
    (_population, "_native_tick_sleep_debt"),
    (_population, "_native_tick_immune_strength"),
    (_population, "_native_tick_stress"),
    (_population, "_native_tick_injury_recovery"),
    (_population, "_native_tick_development"),
    # C++ porting backlog parallel track: A11 hydrology's full-grid
    # moisture/groundwater scalar passes (cpp/src/hydrology_tick.cpp).
    (_hydrology_field, "_native_hydrology_moisture_tick"),
    (_hydrology_field, "_native_hydrology_groundwater_tick"),
    # C++ porting backlog parallel track: world/ca_operators.py's
    # diffuse/reaction_diffuse (cpp/src/ca_operators.cpp) -- exercised
    # via every FieldGrid field's per-tick diffuse() call plus
    # hydrology_field.py's tick_snowpack reaction_diffuse() call.
    (_ca_operators, "_native_ca_diffuse"),
    (_ca_operators, "_native_ca_reaction_diffuse"),
    # C++ porting backlog parallel track: _tick_fallow's own forest-
    # neighbor count (cpp/src/terrain_neighbor_count.cpp), exercised
    # via the weekly maybe_reclaim -> _tick_fallow call path.
    (_terrain_evolution, "_native_forest_neighbor_counts"),
    # R8 first slice: Population.decay_memory_salience's per-memory
    # decay step (cpp/src/memory_salience_decay.cpp) -- exercised via
    # the day_end-cadence decay_memory_salience call path.
    (_population, "_native_memory_salience_decay_step"),
    # R8, "big bang" batch (explicit user directive, reversing the
    # usual one-function-per-turn pacing once the pattern was proven):
    # _immune_modulation_factor's clamp formula (cpp/src/immune_
    # modulation.cpp), exercised via the per-tick _tick_disease call
    # path whenever a sick or colocated-healthy agent exists.
    (_population, "_native_immune_modulation_factor"),
]


def _snapshot_all_native() -> dict:
    return {(mod.__name__, attr): getattr(mod, attr, None) for mod, attr in _NATIVE_TOGGLES}


def _restore_all_native(saved: dict) -> None:
    for (mod_name, attr), value in saved.items():
        mod = sys.modules[mod_name]
        setattr(mod, attr, value)


def _disable_all_native() -> None:
    for mod, attr in _NATIVE_TOGGLES:
        setattr(mod, attr, None)


def _state_hash(world) -> str:
    # sort_keys so dict insertion order (which isn't semantically
    # meaningful for any of World.to_dict()'s contents) never causes a
    # false-positive divergence between two independently-run engines.
    payload = json.dumps(world.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


async def _run(seed: int, ticks: int, native: bool) -> list[str]:
    saved = _snapshot_all_native()
    if not native:
        _disable_all_native()
    hashes: list[str] = []
    try:
        with tempfile.TemporaryDirectory() as d:
            conn = connect(f"{d}/soak.db")
            cfg = Config(db_path=f"{d}/soak.db", llm_enabled=False, seed=seed, initial_population=10)
            eng = SimulationEngine.load_or_create(conn, cfg)
            for _ in range(ticks):
                eng._tick_once()
                await asyncio.sleep(0)
                hashes.append(_state_hash(eng.world))
    finally:
        _restore_all_native(saved)
    return hashes


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticks", type=int, default=3000)
    parser.add_argument("--seeds", type=str, default="1,55,999")
    args = parser.parse_args()
    seeds = [int(s) for s in args.seeds.split(",")]

    exit_code = 0
    for seed in seeds:
        native_hashes = await _run(seed, args.ticks, native=True)
        python_hashes = await _run(seed, args.ticks, native=False)
        if native_hashes == python_hashes:
            print(f"seed={seed} ticks={args.ticks}: MATCH (full World.to_dict() state, every tick)")
            continue
        exit_code = 1
        first_divergence = next(
            (i for i, (a, b) in enumerate(zip(native_hashes, python_hashes)) if a != b), None,
        )
        print(f"seed={seed}: MISMATCH — full state first diverges at tick {first_divergence}")
    return exit_code


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
