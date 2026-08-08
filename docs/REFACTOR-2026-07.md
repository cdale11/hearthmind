# Codebase audit & refactoring roadmap

Started as a full read-through audit (v0.69.0, July 2026) for
performance, maintainability, and ease of adding features, with a
**behavior-preserving** bias — this project has no automated test
suite, so every change here is verified by compile checks, ad-hoc
equivalence scripts, and full-state soak runs (`scripts/verify_native_
soak.py`), never by a unit-test net. It grew into the incremental C++
native-porting program (R5-R8) tracked below.

**Consolidated (v1.34.251)** — this file used to carry a full
implementation/verification narrative per shipped module ("Module N
shipped (vX.Y.Z): ..."), duplicating `CHANGELOG.md`/`CLAUDE.md`'s own
history log. That narrative is gone; what a module does and which
`cpp/src/*.cpp` file backs it is kept below as reference, verification
detail lives only in `CHANGELOG.md`/`docs/DECISIONS.md`. **R6/R7/R8 are
standing rules**, not history — see `CLAUDE.md`'s "Preserve absolutely"
section and R7's own rule below. Remaining open items are tracked in
`docs/ROADMAP-2026-07-REMAINING.md`'s Phase 7 (native performance) and
Phase 8 (R1/R3), not here.

## Headline findings (still true)

The codebase is **not** a tangle: within each file the code is clearly
sectioned, constants carry rationale docstrings, and the objective/
subjective split and single-writer tick loop are respected throughout.
Near-zero dead code (one AST scan across all modules found and fixed a
single unused import). **Performance is not CPU-bound** — the tick
loop uses ~4-9ms of a 1000ms budget; Ollama/llama.cpp call latency
dominates, not Python. The native-porting program below was pursued as
an explicit product decision (memory reduction, architectural
completeness) on repeated direct user directive, not because a measured
tick-time problem demanded it — CLAUDE.md's standing escalation order
(spatial buckets → numpy → PyPy → only then C/C++, "only with a
measured need") still governs any *future* optimization request.

**Maintainability: three oversized modules remain the only real
structural debt** — `agents/population.py` (9,060 lines as of v1.34.296
— corrected from a long-stale "~3,930" estimate carried by this doc
across many intervening sessions; see R1 below), `settlement/
buildings.py` (~2,140), `simulation/engine.py` (~2,090). Splitting
`population.py` (R1, below) is the highest-value remaining item; its
first real slice shipped v1.34.296.

## Done (dedup pass, v0.69.0)

New `hearthmind/util.py`: `clamp(value, low, high)` and shared
`namespaced_rng`/`namespaced_roll` helpers, replacing three copy-pasted
copies across `population.py`/`world/state.py`/`simulation/engine.py`
(each keeps a one-line alias, so no call site changed) plus a handful
of `max(lo, min(hi, x))` sites. Proven byte-identical over a 7000-tick
run before vs. after.

## R1 — Split `population.py` into a mixin-based package [PARTIAL,
first slice v1.34.296]

Highest-value remaining refactor; deferred for a long time because it
touches the single largest, hottest file with no test net — must be
done one cohesive method-group at a time, each verified against a
full-state soak before the next. Tracked in the roadmap's Phase 8.

**Why mixins, not free functions:** `Population`'s ~60 methods call
each other as `cls._x`/`self._x` and read module-level constants;
extracting them as free functions would rewrite every call site.
Mixins preserve `self`/`cls`/MRO exactly, so `class Population
(MovementMixin, ReproductionMixin, …):` needs no call-site changes —
same "compose, don't rewrite" spirit as the `Settlement` domain-object
split.

**First slice shipped, v1.34.296 — pathfinding, with one deliberate
departure from the layout below.** New sibling module `hearthmind/
agents/_population_pathfinding.py`: `PathfindingMixin` holds
`_choose_explore_target`/`_step_toward`/`_bfs_step`/`_reachable_tiles`/
`_maybe_move` (all already-pure `@staticmethod`s, exactly this doc's
own "safest to move first, almost entirely pure" reasoning), plus the
free functions `_is_walkable`/`_bridge_tiles_from_settlements`/
`_walkable_tiles`/`_find_bridge_span` and their 6 constants.
`class Population(PathfindingMixin):` makes every call site resolve
unchanged via the MRO, exactly as this section predicted.

**Deliberately NOT the literal `hearthmind/agents/population/` package
proposed below, this slice** — `population.py` stays a single module
at its unchanged import path, with the extracted names re-imported
into its own namespace, rather than converting to a real package with
an `__init__.py` re-export layer. Reason: a real package conversion
needs to exhaustively re-export dozens of underscore-prefixed
module-level names to preserve every external access pattern —
confirmed via grep that `scripts/verify_native_soak.py` alone reaches
~16 `_native_*`/`_Native*` toggles via bare attribute access
(`_population.NAME`), on top of every underscore name `engine.py`'s
own multi-name `from hearthmind.agents.population import (...)` block
pulls in. Missing even one during a package conversion would silently
break something the same way a package's `__init__.py` always risks —
real regression surface for no real gain on a first slice, when the
sibling-module shape achieves the identical decomposition goal (a
genuinely separate, independently-readable module; `population.py`'s
own line count reduced) with zero re-export risk, since `from X import
Y` binds `Y` into the importing module's own namespace regardless.
A real package conversion, if ever warranted, can follow once several
such sibling-module slices exist to fold in at once.

**Proposed package layout** (`hearthmind/agents/population/`,
un-adopted this slice, kept here as the shape future slices can still
converge toward): `__init__.py` (re-exports, external import paths
unchanged), `_pathfinding.py` (shipped as a sibling module instead,
see above), `_needs.py` (needs/forage/gather/plant/disease/predator),
`_social.py` (relationships/teaching/reproduction/councils/guilds/
migrants), `_settlement_ops.py` (construction/repair/site-choice/
vehicles/fission/carrying-capacity), `core.py` (the dataclass,
`tick()`, mixin composition). Verify one mixin move at a time against
a full-state soak before proceeding to the next — same discipline the
pathfinding slice itself followed (pyflakes clean, every external
consumer's exact access pattern re-confirmed, a real 6000-tick
production soak, `scripts/verify_native_soak.py` MATCH across 3 seeds
x 3000 ticks).

## R2 — Declarative tick-job dispatch table [DONE, v0.71.x]

`SimulationEngine._TICK_JOBS` is a data table of `(method_name,
arg_kind)` `_tick_once` iterates — adding a per-tick job is now one
table entry, not a hand-maintained call sequence. Job method bodies
unchanged.

## R3 — Finish the `clamp()` migration [OPEN, low value/risk]

25+ remaining `max(lo, min(hi, x))` sites across `population.py`,
`agents/agent.py`, `llm/beliefs.py`, etc. Purely readability; one-line
mechanical swaps, file-by-file behind a soak check. Tracked in the
roadmap's Phase 8.

## R4 — `ResourceGrid.tick` working set [DONE, v0.71.x]; numpy [DECLINED]

A `_regenerating` working set now skips already-capped nodes (~2.1x
faster at that call site). The numpy/dense-grid-vectorization
alternative was evaluated and explicitly declined — the hot loops
iterate sparse dicts of enum-keyed objects, not dense numeric grids;
numpy's fit is narrow and would cost real dependency weight for <1% of
an unspent tick budget. Revisit only on a genuine measured need at an
order-of-magnitude-larger population/map.

## R5-R8 — Native C++ port program [24 modules shipped]

`hearthmind._native` (pybind11, `cpp/src/*.cpp`, `setup.py`) — every
module is optional, has a mandatory pure-Python fallback proven
equivalent, and is verified via randomized-equivalence tests plus
`scripts/verify_native_soak.py` (full `World.to_dict()` hash, native
vs. fallback, multi-seed). A failed/skipped native build only costs the
CPU/memory the port would have saved; nothing else changes.

**R6 (opportunistic pure-math ports)** and **R7 (new physical-substrate
code is C++-first)** are **standing rules**, not one-time passes — see
`CLAUDE.md`'s R7 section. R7's scoping: agriculture/ecology/weather/
disasters/terrain evolution are cellular-automata-shaped (per-tile
local state, per-tick local rules); pure, deterministic, no-I/O
arithmetic over already-resolved primitives belongs in C++, object-
graph resolution (which building, which tile, whether a hospital
stands) stays Python. R7's original opportunistic queue closed in full
at v0.73.3 (module 17). **R7 governs new code going forward** — it does
not force an immediate rewrite of any remaining un-ported Python in
this domain.

**Shipped modules** (chronological; file under `cpp/src/`):
`resource_grid.cpp` (foraging/mining regen + nearest-node index),
`terrain_index.cpp` (nearest material tile), `agent_position_index.cpp`
(nearest other agent), `wildlife_index.cpp` (nearest grazer herd),
`needs.cpp` (`_update_needs`, R6's first, runs every agent every tick),
`predator_kill_chance.cpp`, `farm_grid.cpp` (`FarmGrid.tick`, R7's
first), `settlement_decay.cpp` (building + vehicle decay), `weather.cpp`
(`compute_weather` blend/threshold math), `bounded_random_walk.cpp`
(shared drift primitive backing temperament/player-standing/relation/
climate/lake-level ticks), `wilt_farms.cpp`, `flat_damage.cpp` (storm
sweep), `roll_batch.cpp` (generic "which pre-drawn rolls beat their
chance" utility, also backs wildfire spread), `climate_drift.cpp`
(first `Biome` enum crossing), `reclaim.cpp` (`maybe_reclaim`, closing
R7's queue), `sim_clock.cpp` (`SimClock.advance()`, first R8 object-
graph slice), `terrain_grid.cpp` (`World.terrain` as a flat-array-
backed compatibility shim — ~60+ call sites needed zero edits),
`agent_table.cpp` + `agents/agent_store.py` (`AgentTable`, a structure-
of-arrays store wired live into `Population.agents` via an id-keyed
`AgentStore` + a property-shim `Agent` class — ~700 call sites needed
zero edits), `emotion_decay.cpp`, `road_wear.cpp`, `wildlife_step.cpp`
(grazer branch), `relationship_step.cpp`, `soil_fertility.cpp`,
`mining_scars.cpp`, `terrain_neighbor_count.cpp`, `ca_operators.cpp`
(`diffuse`/`reaction_diffuse`), `hydrology_tick.cpp` (moisture/
groundwater passes), `biology_ticks.cpp` (sleep-debt/immune-strength/
stress/injury-recovery/development, the first "agent tick logic"
method-group port beyond needs/emotions).

**Lessons that generalize, worth remembering for any future port:**

1. **pybind11's default STL casters copy, they don't bind by
   reference** — a `std::unordered_map &` argument is a *copy* of the
   caller's dict; mutating it in C++ has zero effect on the Python
   side. Return the updated value instead of relying on in-place
   mutation across the language boundary.
2. **Container iteration order can leak into tie-break behavior.** An
   index keyed by *position* (`ResourceIndex`, `TerrainMaterialIndex`)
   is immune — a fixed spatial loop order. An index keyed by *object
   identity* (`GrazerHerdIndex`, `AgentPositionIndex`) is not:
   `unordered_map` iteration order doesn't match Python dict insertion
   order, so a tied-distance query can silently resolve to a different
   (still valid) answer. Fixed by using an insertion-order `vector` +
   an id→index map. Ask this question explicitly for any future
   identity-keyed index.
3. **The real test for "can this loop's RNG draws be pre-drawn in
   Python" is not "is the draw count fixed"** — it's "does a later
   candidate's eligibility depend on an earlier candidate's outcome
   within the same pass." `maybe_reclaim` and `apply_climate_drift`
   (via `rng.randrange`'s sampling-with-replacement, letting the same
   tile be drawn twice in one call) both had this same-pass dependency
   despite looking safe from the code alone — only a direct wrapper-
   function A/B test (not just the raw-function randomized check)
   caught it both times. A same-pass dependency was solved for
   `maybe_reclaim` via a native callback into Python's `rng.random`
   per conditional roll, instead of pre-drawing.
4. **Python enums can't cross the pybind11 boundary directly** — both
   sides speak plain `int` codes matching a fixed order (e.g.
   `BIOME_ORDER`); Python converts at the call boundary.
5. **Verify every native-crossing wrapper two ways, not one**: a
   randomized-equivalence check on the raw ported function, AND a
   direct A/B sequence through the actual Python wrapper/call site
   (multi-call, not single-call, so tick-to-tick state dependencies get
   exercised) — module 16's bug shipped clean through the first check
   and only surfaced in the second.

**R8's remaining scope**, per the v0.74.2 design pass: `Agent`'s six
variable-size per-agent containers (`relationships`/`trust`/
`inventory`/`memories`/`skills`/`traits`) have no flat-array shape to
port to — they stay Python-side regardless. What's left is porting more
of `population.py`'s per-agent-per-tick *method groups* over the
already-native `AgentTable`/`AgentStore` (the same shape `needs.cpp`/
`biology_ticks.cpp` already established), one self-contained group at a
time. The great majority of `population.py`'s tick logic is still
Python. Tracked as the roadmap's Phase 7 (opportunistic, not gated on
anything — the tick loop remains nowhere near CPU-bound).
