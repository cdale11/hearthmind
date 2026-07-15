# Codebase audit & refactoring roadmap (v0.69.0, July 2026)

Scope: a full read-through audit for performance, maintainability, and
ease of adding features, with a **behavior-preserving** bias — the
brief was explicitly "without breaking any existing functionality," and
this project has no automated test suite (verification is compile
checks, ad-hoc equivalence scripts, live smoke runs, and the user's
real-hardware diagnostics). Refactors that can't be proven equivalence-
safe in one run are documented here as sequenced future work rather
than attempted blind.

## Headline findings

The codebase is in good shape. It is **not** a tangle: within each file
the code is clearly sectioned, constants carry rationale docstrings,
and the objective/subjective split and single-writer tick loop are
respected throughout. Concretely:

- **Dead code: almost none.** An AST scan for unused imports and
  unreferenced functions across all 50 modules found exactly one real
  unused import (`random` inside `llm/caravan.fallback_caravan`) and
  zero dead functions (the `intervene_*` "unreferenced" hits are
  FastAPI route handlers bound by decorator). Fixed.
- **Performance: not CPU-bound, as the standing docs already say.**
  Fresh profile (cProfile, 60 agents / 64×64, 3000 ticks after a 500-
  tick warm-up): ~4.2 ms/tick, and every top entry is proportional to
  genuine simulated activity — `Population.tick` orchestration,
  `resources.tick`/`roads.tick` (bounded by node / worn-tile count, not
  the whole grid), `Settlement.at` (already O(1) position-indexed),
  `_update_relationships` (proportional to real colocation). There is
  **no wasteful hotspot left to fix** after the v0.67.0 `_nearest_
  resource` bounded-box change. The tick budget is 1000 ms; we use ~4.
  A numpy/native pass would buy <1% of a budget we aren't spending —
  see "Deferred" below for why it stays deferred.
- **Maintainability: three oversized modules** are the only real
  structural debt — `agents/population.py` (~3930 lines),
  `settlement/buildings.py` (~2140), `simulation/engine.py` (~2090).
  These are the friction when adding a feature. Splitting them is the
  high-value refactor, but also the highest-risk one without tests, so
  it is planned in detail below rather than rushed here.

## Done this pass (all proven behavior-preserving)

Verified by: full compile; a fresh-world run of 7000 ticks (llm-
disabled, deterministic fallback) producing a byte-identical SHA-256
hash of the entire event stream **before vs. after** the changes
(construction, settlement naming, temperament, and player-standing all
exercised); plus a server-CLI boot smoke test.

1. **New `hearthmind/util.py`** — the bottom of the dependency graph
   (stdlib-only, importable everywhere without cycle risk). Holds three
   genuinely universal helpers:
   - `clamp(value, low, high)` — replaces the `max(lo, min(hi, x))`
     idiom (30+ occurrences codebase-wide; migrated the 5 in
     `buildings.py`'s Phase-G / market math this pass, the rest are a
     safe mechanical follow-up, see below).
   - `namespaced_rng` / `namespaced_roll` — **were copy-pasted verbatim
     into three modules** (`population.py`, `world/state.py`,
     `simulation/engine.py`). Now a single source of truth; each module
     keeps its historical private `_namespaced_rng` name via a one-line
     alias so **no call site changed**.
2. **Import hygiene**: removed the now-dead `import random` (caravan)
   and the `hashlib`/`random` imports left unused in `state.py` and
   `engine.py` once the RNG helpers moved; hoisted two function-local
   `from collections import deque` in `population.py` to a module-level
   import.

Net: −~35 lines of duplication, one clear home for cross-cutting
helpers, zero behavior change.

## Deferred — sequenced plans (documented, not done)

Each is deferred for a stated reason; none is blocked on anything but
careful, test-free verification effort.

### R1. Split `population.py` into a package (mixin-based) — highest value

**Why deferred:** it touches the single largest, hottest file with no
test net; doing it safely means one cohesive method-group at a time,
each followed by the event-hash equivalence check used above. That is
several careful iterations, not one edit.

**Why mixins (not free functions):** the ~60 methods on `Population`
are overwhelmingly `@staticmethod`/`@classmethod`, but they call each
other as `cls._x`/`self._x` and read module-level constants. Extracting
them as free functions would rewrite every call site (high risk).
**Mixins preserve `self`/`cls`/MRO exactly**, so call sites are
untouched — the class simply becomes
`class Population(MovementMixin, ReproductionMixin, …):`. This is the
same "compose, don't rewrite" spirit as the proven v-series `Settlement`
domain-object split.

**Proposed package layout** (`hearthmind/agents/population/`):
- `__init__.py` — re-exports `Population` (and the module-level helpers
  other modules import from `agents.population`, e.g. `_namespaced_rng`,
  `WALKABLE_BIOMES`) so **external import paths never change**.
- `_pathfinding.py` — `_is_walkable`, `_walkable_tiles`, `_step_toward`,
  `_bfs_step`, `_reachable_tiles`, `_maybe_move`, and the
  `_nearest_*` target helpers; the biome/offset constants. Cohesive,
  almost entirely pure — the safest group to move first.
- `_needs.py` — `_update_needs`, `_maybe_forage`, `_maybe_gather`,
  `_maybe_plant`, disease (`_maybe_outbreak`/`_tick_disease`), predator
  attack.
- `_social.py` — `_update_relationships`, `_maybe_teach_skills`,
  reproduction/family, councils/guilds, migrants.
- `_settlement_ops.py` — construction/repair/site-choice, vehicles,
  fission, carrying capacity.
- `core.py` — the `Population` dataclass, `tick()` orchestration, and
  the mixin composition.
Shared constants move to a `_constants.py` (or stay in `core` and are
imported by the mixins). **Verification per step:** move one mixin, run
the 7000-tick event-hash equivalence script; only proceed when the hash
is unchanged.

### R2. Declarative tick-job dispatch table — DONE (v0.71.x)

Shipped a safer, higher-confidence version than the "unify all 20 method
bodies" idea originally sketched below (which risked flattening real
per-job differences — record's backpressure-fallback path, dispute's
distinct backlog check, per-item loops). Instead, the *dispatch* is now
data-driven: `SimulationEngine._TICK_JOBS` is a table of
`(method_name, arg_kind)` that `_tick_once` iterates, replacing the
hand-maintained 20-line call sequence. Adding a per-tick job is now one
table entry next to its method; the load-bearing order lives in one
place. The job method bodies are **unchanged** — proven byte-identical
by a 6000-tick event-stream hash match. The deeper "each job as a
registry descriptor with build/parse/apply callbacks" idea is left as
optional future work; the dispatch table captures most of the
maintainability win at near-zero risk. Original sketch retained below.

### R2 (original sketch). Collapse `engine.py`'s scheduling boilerplate

`engine.py` has ~20 near-identical `_maybe_schedule_<job>(events)`
methods (chronicle, tradition, invention, festival, caravan, town-brain,
beliefs, omen, record, dispute, guild-founding, geography, …) that each:
gate on backpressure, build a prompt, define an `apply()` closure, and
call `_schedule_llm_job`. This is the boilerplate a new LLM job must
copy, and the copy is where bugs hide (the v0.63.0 audit found a stale
hardcoded default in exactly this kind of duplicated shape).

**Plan:** a small declarative registry — each job is a dataclass
(`name`, cadence/trigger predicate, `build_prompt`, `parse`/`apply`,
`job_target`) registered in a list the tick loop iterates. The
per-job methods shrink to data. **Why deferred:** the closures capture
subtly different state (some read `events`, some the round-robin
`_job_target`, some settlement-scoped vs. world-scoped), so the
abstraction must be designed to not flatten a real distinction — a
design pass, not a mechanical move. Lower risk than R1 but real.

### R3. Finish the `clamp` migration — low value, low risk

25+ remaining `max(lo, min(hi, x))` sites in `population.py`,
`agents/agent.py`, `llm/beliefs.py`, etc. Purely readability; each is a
one-line mechanical swap but each is also a chance to flip a bound, so
do it file-by-file behind the event-hash check. Left out of this pass
to keep the diff reviewable.

### R4. resources.tick working set — DONE as pure-Python (v0.71.x)

Resolved after review: the numpy path was declined because the hot loops
(`resources.tick`, `roads.tick`) iterate **sparse dicts**, not dense
numeric grids, and terrain tiles are enum-based objects — numpy's fit is
narrow and would force a sparse→dense restructure for marginal gain
(user agreed: "skip numpy; do the pure-Python win"). Shipped instead the
algorithmic win the deferral note itself pointed at: `ResourceGrid` now
keeps a `_regenerating` working set of below-cap node positions and
`tick` iterates only those (nodes at cap are a no-op under
`min(cap, amount+regen)` anyway). Kept in sync by `mark_regenerating`,
called at the three depletion sites (forage/gather/grazing).
**Byte-identical** (event stream + every node amount matched over 6000
ticks); measured `resources.tick` self-time 0.777s → 0.372s (~2.1x) at
population 60. `roads.tick` was left alone — it already iterates only
worn tiles (its cost is proportional to real road activity, not waste).
Numpy remains available if a *measured* dense-grid bottleneck ever
appears; the original declined-rationale is retained below.

### R4 (numpy variant, declined). Grid-pass vectorization — do **not** do without a measured need

These full-collection passes are ~10% of tick time but proportional to
real state, and the tick loop has ~250× headroom. Per CLAUDE.md's
standing escalation order (spatial buckets → numpy → PyPy, "all before
any C/C++, and only with a measured tick-time problem"), converting
them to numpy would add a heavy dependency and cost the plain-Python
hackability for <1% of an unspent budget. **Recorded as explicitly
declined**, not forgotten. If population/map ever grows an order of
magnitude and a real per-tick problem is *measured*, `resources.tick`
is the first candidate (a "non-full nodes" working set avoids touching
capped nodes) — but not before.

### R5 (new, v0.72.0+). Native C++ port — IN PROGRESS, module-by-module

Explicit user directive (July 2026): "port as many python modules into
C++ as possible," overriding the earlier "C/C++ port: evaluated,
recommended against" finding above (still true on its own terms — the
tick loop is nowhere near CPU-bound — but a full port is now a directly
requested product decision, not a perf-chasing one, and it's also a
real, if modest, resident-memory reduction: fewer live Python objects
per agent/tile). Flagged to the user before starting: with no automated
test suite, a full-engine rewrite in one pass has no equivalence-proof
net at the scale of `population.py`/`engine.py`/`buildings.py`
(~8,400 lines combined) — the SHA-256 event-stream-hash harness used for
R2/R4 proves a *scoped* change equivalent, not an entire rewrite. The
path taken: **incremental, one provably-equivalent hot-path module at a
time**, via a `hearthmind._native` pybind11 extension
(`cpp/src/*.cpp`, `setup.py`) with a mandatory pure-Python fallback for
every ported function — never a hard dependency, so a failed/skipped
build only costs the CPU/memory the port would have saved, nothing
breaks.

**Shipped (v0.72.0):** `world/resources.py`'s `ResourceGrid.tick`
(regeneration of the below-cap working set from R4) — the first module,
chosen because it's self-contained (pure arithmetic over a small
key/value shape, no cross-module state) and already had the R4
working-set optimization to port faithfully. Verified via a 3000-tick
standalone equivalence script (mixed depletion + season changes) hashing
final node-amount state: native and pure-Python paths produce an
identical SHA-256. Also ran the existing 4000-tick engine soak
(`llm_enabled=False`) with the extension built and loaded — no crash,
confirms the wiring (import try/except, `_key` encoding round-trip)
doesn't disturb the rest of the tick loop.

**Gotcha worth recording:** pybind11's default STL type casters (`py::
arg` of `std::unordered_map<...> &`) **copy** a Python dict into a
temporary C++ object rather than binding it by reference — mutating that
temporary in C++ has zero effect on the caller's Python dict. The first
implementation attempt relied on "mutate `amounts` in place" and
silently no-op'd (caught by the equivalence script, not by the build —
it compiled and ran fine, just produced wrong results). Fixed by having
the C++ function *return* the updated mapping instead. Any future
ported function that looks like it needs an in-place-mutated container
argument should return the new value instead, not rely on reference
semantics working across the language boundary.

**Module 2 shipped (v0.72.2): `Population._nearest_resource`.** The
`world/weather.py`/`world/terrain_evolution.py` candidates named above
turned out, on closer look, not to be good ports after all:
`compute_weather` is O(1) per tick (one `WeatherState`, not a per-tile
pass — the "grid pass" framing above was simply wrong), and
`terrain_evolution.py`'s functions run on weekly/monthly cadence,
touch `Settlement`/`Farm` occupancy queries, and mutate `Tile` objects
— cross-module and infrequent, the opposite of a good native-port
target. `_nearest_resource` was the real candidate (the v0.67.0
profiling pass had already named it the top hotspot). Ported as a
compiled `ResourceIndex` (`cpp/src/resource_grid.cpp`) — a native
hash map of in-range FOOD/FISH nodes, rebuilt once per `ResourceGrid.
tick()` (before any agent forages that tick) and live-patched at each
depletion site via the same `mark_regenerating` call `_regenerating`
(R4) already hooks, so a second agent foraging later in the same tick
sees the first agent's depletion exactly like the pure-Python dict scan
always did — this incremental-patch requirement, not the query itself,
was the nontrivial part of getting this port byte-identical. Verified
via 20,000 randomized bounded-box queries interleaved with mid-run
depletions (0 mismatches against a reference Python scan) plus the
existing 4000-tick engine soak (identical event-stream hash to the
pre-port baseline).

**Module 3 shipped (v0.72.3): `Population._nearest_material_tile`.**
Explicit user directive ("keep moving more python code to C++")
overrode the earlier "deliberately left unported, no measured-hotspot
evidence" call — ported anyway, on direction rather than fresh
profiling data (flagged as such, not silently treated as newly
measured). Same bounded-box shape as `_nearest_resource`, but simpler:
MATERIAL_BIOMES (FOREST/HILLS) tiles never deplete — GATHER harvests
wood/stone abstractly without changing the tile's biome — so
`TerrainMaterialIndex` (`cpp/src/terrain_index.cpp`) needs no live-patch
the way `ResourceIndex` did for depletion; a plain rebuild once per
`Population.tick()` (mirroring the existing `farm_positions`/`granary_
positions` "compute once, share across every agent" pattern one line
above it) is already exactly equivalent to the pure-Python scan.
Verified via 20,000 randomized queries against a synthetic 70x70 terrain
(0 mismatches) plus the standard 6000-tick cumulative-event-hash engine
soak (byte-identical, all three native modules on vs. off).
`Population._nearest_other_agent` and `WildlifeGrid.nearest_grazer_herd`
are the next same-shape candidates if the directive to keep porting
continues — still no fresh profiling behind either, noted for honesty
rather than re-litigated each time.

**Module 4 shipped (v0.72.4): `Population._nearest_other_agent`.** Of
the four modules ported so far, this is the first with a *genuine*
algorithmic case for porting independent of the "keep porting" directive:
SOCIALIZE's search has no distance cap (D4), so it's an honest
O(population) scan per agent, O(population²) per tick — the only ported
function whose cost scales with town size rather than a fixed map-shaped
cost. `AgentPositionIndex` (`cpp/src/agent_position_index.cpp`) is
deliberately just a fast linear scan, not a spatial structure — nothing
to bucket by without a radius. Built once per `Population.tick()` from
the same `position_snapshot` list/order the Python path already builds,
preserving tie-break behavior exactly. Verified via 20,000 randomized
queries (0 mismatches) plus the cumulative-event-hash soak at two
population scales. `WildlifeGrid.nearest_grazer_herd` remains the next
same-shape (radius-bounded, so fixed-cost) candidate if porting
continues.

`population.py`/`engine.py`/`buildings.py` themselves (the
orchestration layer — cross-references dozens of other modules, mutates
shared `World`/`Settlement` state, drives the LLM job scheduling) are
NOT good near-term candidates for a mechanical translation the way a
self-contained numeric loop is; porting those meaningfully means
redesigning around C++ ownership semantics for what's currently
Python's reference/GC model, which is a redesign, not a port, and needs
its own dedicated-session scoping the way R1 (mixin split) does. Revisit
R1 alongside this — a mixin split first would actually make the
boundaries between "orchestration" and "hot numeric loop" clearer for
extraction. **Do not treat "R1/R2/R4 done" as license to consider this
item small** — it is explicitly the largest deferred item in this file.

## One-line summary for CLAUDE.md / CHANGELOG

Audit found the codebase clean (near-zero dead code, no wasteful
hotspots); shipped a safe dedup pass (shared `util.py`: `clamp` +
`namespaced_rng`/`namespaced_roll`, import hygiene), proven byte-
identical over a 7000-tick run; documented the three-big-file split
(R1 mixins), scheduler-registry (R2), and the declined numpy pass (R4)
as sequenced future work.
