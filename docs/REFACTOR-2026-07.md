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

**Module 5 shipped (v0.72.4 follow-up): `WildlifeGrid.nearest_grazer_herd`.**
`GrazerHerdIndex` (`cpp/src/wildlife_index.cpp`) — same live-patch shape
as `ResourceIndex`: herd positions only change in `WildlifeGrid.tick()`
(always before `Population.tick()`, see world/state.py's ordering), but
`hunt()` can zero a herd's count mid-`Population.tick()`, so the index
is rebuilt once at the end of `WildlifeGrid.tick()` and live-patched via
`hunt()`. **A real bug was caught during verification, not just
confirmed absent**: the first implementation stored herds in an
`unordered_map`, whose iteration order doesn't match Python dict
insertion order — invisible for a unique-nearest query, but a
tied-Manhattan-distance query could silently resolve to a *different*
(still valid, but not identical) herd than the Python path. Caught by a
20,000-query randomized check (238/20000 mismatches, all tied-distance
cases), fixed by switching to an insertion-order `vector` + an
id→index map for `update()`. Re-verified at 0/20000 mismatches
afterward, plus 0/5000 on a separate live-patch-ordering check, plus the
standard cumulative-event-hash soak. Recorded because the earlier
ported indexes (`ResourceIndex`, `TerrainMaterialIndex`) don't have this
failure mode — they're keyed by *position* and iterate a fixed spatial
loop, so container iteration order never leaks into tie-break behavior;
`GrazerHerdIndex`/`AgentPositionIndex` iterate object identity directly,
so it does. **Any future index port must ask this question explicitly.**

## R6: full engine-core rewrite (started v0.72.4, explicit user directive)

Distinct from R5's incremental hot-loop track above. Explicit user
instruction, after the R5 module-5 batch: port the *orchestration*
layer itself into C++, not just self-contained lookups — "port all
remaining code to C++... then do a full engine rewrite as well." This
directly contradicts the R5-era framing immediately below (still true
on its own narrow terms, kept for the historical record) that
`population.py`/`engine.py`/`buildings.py` are not good mechanical-
translation candidates. Flagged to the user before starting (per this
project's standing "conflict flagged, not silently resolved" rule) —
the user chose to proceed, explicitly scoping it: **SQLite persistence,
asyncio LLM job scheduling, and the FastAPI web layer stay Python**;
only the deterministic tick-time simulation logic moves.

*Historical framing being superseded, kept for context:* "porting
`population.py`/`engine.py`/`buildings.py` meaningfully means
redesigning around C++ ownership semantics for what's currently
Python's reference/GC model, which is a redesign, not a port." Still
true — R6 is explicitly that redesign, undertaken deliberately rather
than avoided. The mitigation isn't "it's not a redesign," it's the same
discipline every native module here has used since v0.72.0: byte-
identical fallback + hash-soak proof per increment, so a redesign
proceeds without the project's missing test suite meaning "no way to
tell if it broke something."

**Scoping principle:** port pure, deterministic, no-I/O computation —
math and branching over already-resolved primitive/boolean inputs —
leaving every place that touches a Python object graph (`Agent`,
`Settlement`, `Building` dataclasses), SQLite, asyncio tasks, or the
LLM client in Python. This mirrors module 6 below exactly: object-shaped
resolution (which building an agent stands on, whether it's a standing
hospital) stays Python; only the arithmetic that follows crosses into
C++. A function belongs in R6 only if it can be expressed as "given
these scalars, compute these scalars" with no side effects on shared
state beyond its own return value.

**Module 6 shipped (v0.72.4): `Population._update_needs`.** The first
R6 module — unlike every R5 module (goal-gated: only fires for an agent
pursuing a specific goal), this runs unconditionally for *every* agent,
*every* tick, so it's the real per-tick cost floor, not just a
worst-case bound. `update_needs` (`cpp/src/needs.cpp`) takes the
already-resolved shelter/hospital/elder booleans plus the agent's
current hunger/energy/resting state and every tunable constant (via a
`NeedsConstants` struct, one instance built once per `Population.tick()`
— constants don't change mid-tick) and returns the updated hunger/
energy/resting triple; Python writes the result back onto the `Agent`
dataclass. Constants are passed as parameters rather than duplicated as
C++ literals — they're currently spread across `agents/agent.py`,
`agents/population.py`, and `settlement/buildings.py` with no single
home, and a second hardcoded copy risks silent drift on a future retune
that only updates the Python side. Verified via 50,000 randomized
input combinations against a reference Python port of the exact same
branching (0 mismatches to 1e-9) plus the cumulative-event-hash soak
across three seeds.

**Module 7 shipped (v0.72.6): `Population._maybe_predator_attack`'s
kill-chance math.** `predator_kill_chance` (`cpp/src/predator_kill_
chance.cpp`) — pure arithmetic only, no RNG: the function's two
`rng.random()` rolls (does-an-attack-happen, then does-it-land-lethal)
stay in Python in their original order, since a native module must
never introduce a second, uncoordinated randomness source alongside the
project's namespaced-RNG discipline. `has_hospital`/`temperament`/
`resilience` are resolved in Python exactly as before and passed in as
plain scalars. Verified via 50,000 randomized input combinations (0
mismatches to 1e-12) plus the cumulative-event-hash soak across four
seeds, all seven native modules on vs. off, byte-identical.

**Queued next for R6**, roughly in order of how self-contained they
are: `FarmGrid`/`FarmPlot` growth-tick math (`economy/farms.py`, not
yet inspected in detail — likely close to module 6's shape); building
decay/repair progress math (`settlement/buildings.py`) once the "which
building, which stage" resolution is separated from the "how much did
its condition change" arithmetic. As of v0.72.6 these are also R7
candidates (below) — see R7 for the reframing of this whole queue.

## R7: cellular-automata physical substrate — new domain code is C++ from the start (added v0.72.6)

Explicit user directive, building on R6: reframe the deterministic
physical-reality layer this project already commits to (CLAUDE.md's
design priorities — "the deterministic engine should only model
objective physical reality: time, weather, seasons, physics, movement,
pathfinding, resources, ecology, construction, decay") as an explicitly
**cellular-automata-style substrate**, and — new addition — **write any
new code in that domain directly in C++ from the outset**, not
Python-first-then-ported-later. This is a scoping/workflow change, not
a mechanics change: agriculture, ecology/wildlife, weather, environment
effects, disasters, and terrain evolution are already grid/tile-based
systems with local per-cell state updated by per-tick rules (a
`ResourceNode`'s regen, a `Tile`'s biome/moisture, an `AnimalHerd`'s
position/count, a farm plot's growth stage) — genuinely CA-shaped
already, even before this directive; what changes is where new code in
this domain gets written first.

**In scope (the CA/physical-substrate domain):** `world/resources.py`
(foraging/mining/fishing nodes — modules 1-2 partially ported),
`world/wildlife.py` (grazer/predator herds — module 5 partially
ported), `world/weather.py` (not yet ported — flagged not-yet-a-
measured-hotspot in the v0.72.2 correction, revisit under the new
"write new code in C++" rule for anything *added* to it from here),
`world/terrain_evolution.py` (weekly/monthly terrain change — same
status as weather.py), `world/disasters.py`, `world/hydrology.py`,
`economy/farms.py` (agriculture), `settlement/buildings.py`'s pure
decay/repair math (not the ownership/construction orchestration around
it). **Out of scope, unchanged:** everything CLAUDE.md already assigns
to the LLM — town-brain/chronicle/dialogue/culture/beliefs/dispute/
founding/omens/temperament-as-Phase-G, i.e. "town consciousness,"
supernatural ambiguity, and every other judgment/interpretation/
psychology/social-behavior decision point. R7 does not touch that
split; it only sharpens how the *other* half (physical reality) is
built going forward.

**The new rule, precisely:** a brand-new mechanic or extension inside
the CA/physical-substrate domain (a new disaster type, a new terrain
evolution rule, a new agriculture mechanic, a new weather effect) is
implemented as a C++ function/module from the first line, following the
same pattern every R5/R6 module already established — pybind11 binding,
a pure-Python fallback so a failed/skipped build never breaks the sim,
and a randomized-equivalence + cumulative-hash verification pass before
it's considered done. The fallback isn't optional busywork here: it's
what keeps "new code is C++-first" from becoming "new code has no
verifiable pure-Python behavior to check it against." **Existing Python
code in this domain is not being rewritten wholesale on this directive
alone** — it continues to move over incrementally under R6's existing
module-by-module queue (farms, weather, terrain evolution, disasters,
hydrology, building decay math), each still needing its own
provably-equivalent module and verification pass, same as always. R7
is additive to that queue, not a replacement for it: it governs new
code from here forward; the backlog of not-yet-ported existing code
is unchanged in shape, just now understood as "the CA engine's
remaining Python surface" rather than an ungrouped list of modules.

**Module 8 shipped (v0.72.7): `FarmGrid.tick`.** First module ported
under the R7 banner, and the cleanest fit for the "cellular automata"
framing so far — a plain per-plot local rule (GROWING accumulates
growth and flips to READY at 1.0; READY accumulates `ready_ticks` and
rots past `FARM_ROT_TICKS`), same shape as `resource_grid_tick` (module
1), just a second grid. `farm_grid_tick` (`cpp/src/farm_grid.cpp`)
takes an already-resolved `irrigated` boolean per plot (the
`is_adjacent_to_water` terrain lookup stays in Python, same "object-
graph resolution stays Python" principle as every module since 6) and
returns updated per-plot state plus the list of positions that rotted
this tick, so the caller's `del self.plots[pos]` loop is unchanged in
shape. Verified three ways: 20,000 randomized input combinations
against a reference Python port (0 mismatches), 500 direct `FarmGrid.
tick()` A/B runs (5 ticks each, native vs. Python paths on cloned
grids, comparing final plot state — 0 mismatches), and the cumulative-
event-hash engine soak across four seeds, all eight native modules on
vs. off, byte-identical.

**Modules 9-10 shipped (v0.72.8): building and vehicle decay.**
`building_decay_tick`/`vehicle_decay_tick` (`cpp/src/settlement_decay.
cpp`) — `Settlement.tick`'s two remaining per-cell decay passes, same
shape as module 8. Split into two functions since the pure-Python
original already treats `self.buildings`/`self.vehicles` as separate
collections with different lifecycles (buildings: STANDING→decay→
RUINED→rot→removed; vehicles: READY→decay→BROKEN, no removal — a
non-READY vehicle is untouched, so only READY ones are even passed to
the native call). x/y/kind stay in Python (event text only); the native
functions return small per-cell result flags (`just_ruined`/`removed`/
`just_broke`) so Python's existing event-logging reads a flag instead
of re-deriving it from a condition comparison. Verified via 20,000
(buildings) and 10,000 (vehicles) randomized input combinations against
reference Python ports (0 mismatches each) plus a 5000-tick,
four-seed cumulative-event-hash soak — deliberately longer than prior
soaks to give the comparatively rare ruin/reclaim/breakdown events more
chances to actually fire — all ten native modules on vs. off,
byte-identical.

**Module 11 shipped (v0.72.9): `compute_weather`'s blend/threshold
math.** First module whose Python original draws from a seeded
`random.Random` (`_tick_rng`) rather than either having no randomness
or receiving a caller-owned `rng.Random` (modules 6-7's pattern).
Decided NOT to reproduce CPython's Mersenne Twister in C++ — this
project's native-port discipline only requires native-vs-Python parity
for the *same* code path, not cross-implementation RNG parity, and
CLAUDE.md's standing rule is explicit that cross-run determinism isn't
a goal here at all. So the three `rng.uniform(...)` jitter draws stay
in Python; `compute_weather_blend` (`cpp/src/weather.cpp`) takes the
already-drawn jitter values and does the baseline+jitter/clamp/EMA-
blend/snow-threshold arithmetic. Verified via 30,000 randomized input
combinations (0 mismatches), a direct 20,000-tick `compute_weather()`
A/B sequence across all twelve months (0 mismatches — this check
specifically stresses the EMA blend's tick-to-tick dependency, where a
single-call equivalence check alone wouldn't catch compounding drift),
and the cumulative-event-hash engine soak across four seeds, all eleven
native modules on vs. off, byte-identical.

**Module 12 shipped (v0.72.10): shared `bounded_random_walk_step`.**
While scoping `tick_climate` (world/terrain_evolution.py) and the
lake-level nudge inside `tick_lakes` (world/hydrology.py), noticed both
share the exact `value = clamp(value*mean_reversion + jitter [+ extra],
-1, 1)` shape already used by three R6-era functions in `settlement/
buildings.py` (`tick_temperament`/`tick_player_standing`/
`tick_relation`). Ported once (`cpp/src/bounded_random_walk.cpp`),
wired into all five call sites instead of writing near-duplicate
functions — same dedup instinct as `util.py`'s `clamp`/`namespaced_rng`
(v0.69.0), just crossing into C++. `tick_temperament`/`tick_player_
standing`/`tick_relation` are Phase G/institution mechanics, not
physical substrate, so strictly R6 rather than R7 — noted for scope
accuracy, not re-litigated; the function itself is domain-agnostic.
Every call site keeps its own RNG draw in Python. Verified via 30,000
randomized inputs against the pure function, direct multi-call
sequences at each of the five call sites, and the cumulative-event-hash
soak across four seeds at 6000 ticks (long enough to span several
months so the monthly-cadence call sites actually fire), all twelve
native modules on vs. off, byte-identical.

**Module 13 shipped (v0.72.11): `_wilt_farms` (world/disasters.py).**
Resolves the RNG-in-loop question flagged after module 12 by finding a
function that actually fits the "pre-draw the rolls in Python" pattern
rather than forcing one that doesn't: `_wilt_farms` (shared by
`tick_heatwave`/`tick_frost`) rolls exactly one `rng.random()` per farm
plot, unconditionally, so the draw count is fixed and known before the
loop runs — unlike `apply_local_activity`/`maybe_reclaim`, where the
number of rolls depends on which tiles clear a heat threshold or
neighbor-count check first. `wilt_farms_tick`
(`cpp/src/wilt_farms.cpp`) takes the per-plot state plus one pre-drawn
roll per plot (same order `farms.plots.items()` iterates) and returns
updated state + a hit/removed flag per plot, same shape as
`farm_grid_tick` (module 8). Verified via 20,000 randomized input
combinations (0 mismatches), 500 direct `_wilt_farms()` A/B calls on
cloned `FarmGrid` instances sharing a seeded RNG (0 mismatches), and
the cumulative-event-hash engine soak across four seeds, all thirteen
native modules on vs. off, byte-identical.

**Module 14 shipped (v0.72.12): `tick_storm`'s flat-damage sweep.**
Checked `tick_flood`/`tick_wildfire`/`tick_storm` for module 13's "fixed
RNG draw count" shape. `tick_flood`/`tick_wildfire` don't qualify —
both roll a data-dependent number of draws (flood candidate-tile count,
wildfire spread count per burning tile) that changes as the loop runs,
same problem as terrain_evolution.py's functions. `tick_storm` does
qualify, more simply than `_wilt_farms`: at most one RNG draw total,
gated by a condition (`weather.wind >= threshold`) the caller already
knows before any loop — not a per-iteration draw. `flat_damage_tick`
(`cpp/src/flat_damage.cpp`) is the remainder once that single draw is
resolved: unconditional `max(0, condition - damage)` across every
building/vehicle, no RNG left. Deliberately does not add a RUINED/
BROKEN transition at zero condition (unlike modules 9-10) — the
pure-Python original doesn't either, and mirroring the source exactly
matters more than internal consistency with a different function.
Verified via 10,000 randomized inputs plus the cumulative-event-hash
soak across four seeds, all fourteen native modules on vs. off,
byte-identical.

**Remaining queue is now the genuinely-hard tier**: `world/
terrain_evolution.py`'s `apply_local_activity`/`maybe_reclaim`,
`world/disasters.py`'s `tick_flood`/`tick_wildfire`, and the rest of
`world/hydrology.py` all share the data-dependent-RNG-draw-count
problem — porting them safely needs a "call back into Python's
`rng.random()` from C++ at the exact point a draw is needed" design
(viable via pybind11, but real per-draw crossing overhead and its own
risk surface), not the "pre-draw everything in Python, hand off the
batch" pattern that carried modules 11-14. Deliberately not attempted
without a measured performance need — these functions run at weekly/
monthly cadence over small candidate sets, nowhere near the tick loop's
actual (already-established-nonexistent) CPU bottleneck. Escalate only
if that changes.

## One-line summary for CLAUDE.md / CHANGELOG

Audit found the codebase clean (near-zero dead code, no wasteful
hotspots); shipped a safe dedup pass (shared `util.py`: `clamp` +
`namespaced_rng`/`namespaced_roll`, import hygiene), proven byte-
identical over a 7000-tick run; documented the three-big-file split
(R1 mixins), scheduler-registry (R2), and the declined numpy pass (R4)
as sequenced future work.
