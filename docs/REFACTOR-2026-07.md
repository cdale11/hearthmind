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

**Module 15 shipped (v0.72.13): `apply_local_activity`'s deforestation
roll — and a correction to the "remaining queue is genuinely hard"
framing above.** Re-traced `apply_local_activity` rather than taking
the earlier blanket "RNG-in-loop" characterization at face value: its
per-tile deforestation-roll eligibility depends only on state that
exists before the loop runs (current heat value, current biome), never
on another tile's outcome within the same pass. That's different from
`maybe_reclaim`, where an earlier iteration's conversion can change a
later iteration's forest-neighbor count — a genuine same-pass
dependency that blocks pre-drawing. The real disqualifying test isn't
"does this loop call `rng.random()` a variable number of times," it's
"does a later candidate's eligibility depend on an earlier candidate's
outcome within the same pass." `roll_passes_tick`
(`cpp/src/roll_batch.cpp`) is a small, deliberately generic "which
pre-drawn rolls beat their chance" utility — reusable by any future
per-candidate RNG-gated decision with this shape, not just this one
call site. Verified via 20,000 randomized inputs, 300 direct
`apply_local_activity()` A/B runs on synthetic terrain/heat state, and
the cumulative-event-hash soak across four seeds, all fifteen native
modules on vs. off, byte-identical.

**`tick_wildfire`'s spread step (v0.72.14): reuses module 15, no new
C++.** Traced it individually rather than assuming it shared
`maybe_reclaim`'s problem just because both involve terrain mutation.
It doesn't: own-tile conversion draws no RNG at all (an active FOREST
tile always burns), and each neighbor-spread roll's eligibility depends
only on the pre-loop `active_wildfire_tiles` snapshot + terrain biomes
— `active_wildfire_tiles` is read via membership test throughout but
never mutated mid-loop (only unioned with `frontier` at the very end),
and `frontier` itself is never consulted for eligibility. A neighbor
shared by two active tiles still gets rolled twice, exactly like the
original — `frontier` being a set only de-duplicates the *result*, not
the roll count. Directly reuses `roll_passes_tick` (module 15) — the
Python side splits the original's single combined loop into an
unconditional own-conversion pass (no RNG, order-irrelevant) and a
candidate-collection-then-roll-batch pass, which doesn't reorder the
RNG stream since the first pass draws nothing. Verified via 300 direct
`tick_wildfire()` A/B runs on synthetic fire/terrain state (0
mismatches) plus the cumulative-event-hash soak across five seeds at
6000 ticks each, byte-identical.

**Module 16 shipped (v0.73.0): `apply_climate_drift`'s biome-step
mutation — the first Biome enum crossing the native boundary, and a
second same-pass-dependency catch inside a function whose RNG-draw
count IS fixed.** `classify_with_bias`/`BIOME_ORDER`-index-stepping
(`world/terrain.py`) moved to `cpp/src/climate_drift.cpp`
(`classify_biome_index`, `climate_drift_batch`). Python enums can't
cross pybind11 directly, so both sides speak plain `int` biome codes
matching `BIOME_ORDER` position — Python converts `Biome -> int` via
`BIOME_ORDER.index(...)` before the call and `int -> Biome` via
`BIOME_ORDER[i]` after, the same "resolve enums/objects in Python,
hand C++ only plain data" strategy every prior module already used
(no precedent existed for the enum itself crossing, since e.g.
`apply_local_activity`'s `Biome.FOREST` filtering happens entirely in
Python before the native call). The sampling loop's RNG draws
(`rng.randrange(width)`/`(height)`, fixed count = `sample_size`,
known before the loop starts) and the `_is_developed`/
`_skip_climate_drift` tile-eligibility filtering stay in Python, same
split as every module.

The randomized-equivalence check on the raw `classify_biome_index`/
`climate_drift_batch` functions passed clean first try (50,000 inputs,
0 mismatches) — but the first direct A/B run of the actual wrapper
function (`apply_climate_drift`, 500 trials) found real mismatches,
consistently off by exactly one changed-tile count per trial. Root
cause: `rng.randrange` samples *with replacement* — the same `(x, y)`
can be drawn twice in one `apply_climate_drift` call (`sample_size` is
only ~3% of the map, but collisions are still expected via the
birthday-paradox math over ~48 draws against a few thousand tiles).
The pure-Python original mutates `terrain` in place as it goes, so a
duplicate's second occurrence reads the tile's *already-stepped*
biome from the first occurrence — a genuine same-pass dependency, the
same disqualifying shape as `maybe_reclaim`, just triggered by
duplicate sampling rather than neighbor-count drift. The fix: call the
native function once per sample (reading current `terrain` state each
iteration) instead of batching every sample into one call up front —
preserves read-your-own-writes order while still doing the per-tile
arithmetic in C++; RNG draws were never affected either way. Re-run of
the same 500-trial A/B suite after the fix: 0 mismatches. This is the
second time in this queue a same-pass dependency wasn't visible from
reading the code alone and only surfaced once the actual wrapper
function was A/B tested against synthetic state — reinforces that step
2 of the verification methodology (direct wrapper A/B, not just the
raw-function randomized check) is load-bearing, not redundant with
step 1. Verified via 50,000 randomized inputs against the raw
functions (0 mismatches), 500 direct `apply_climate_drift()` A/B runs
on synthetic terrain (0 mismatches after the fix), and the
cumulative-event-hash engine soak across four seeds at 6000 ticks
each, all sixteen native modules on vs. off, byte-identical.

**Remaining queue**: `maybe_reclaim` (confirmed genuine same-pass
dependency — a converted tile can be a later tile's forest-neighbor in
the same pass); `tick_flood` (single-event trigger + a single
candidate-index pick, not a batched sweep — too little batchable
content to be worth a native module regardless of RNG shape).

**R7 queue closed (v0.73.3).** `world/hydrology.py`'s remaining
functions traced: `generate_rivers`/`identify_lakes` are both called
only from `World.create_new` and `World.from_dict`'s legacy-migration
path — creation-time-only, never per-tick, so out of scope regardless
of RNG shape (same reasoning as `tick_flood`, just a different flavor
of "not worth it"). `tick_lakes` (the only per-tick function in that
file) was already ported in module 12. With module 17 (`maybe_reclaim`)
also shipped in v0.73.2, every function originally in the R7
opportunistic-port queue is now accounted for: ported (15, the
`tick_wildfire` reuse, 16, 17), confirmed genuinely hard and left
(none remain — `maybe_reclaim` was the one, now ported via the
callback design), or confirmed creation-time/too-small-to-matter
(`tick_flood`, `generate_rivers`, `identify_lakes`). **R7 is done** —
any further native-port work is R8.

## R8: full engine-core rewrite — scoping pass (v0.73.0)

Explicit user directive to pursue "a full engine rewrite... in C++,"
distinct from R6 (opportunistic pure-math ports) and R7 (new
cellular-automata code C++-first). This section scopes what that would
actually mean, deliberately BEFORE any code moves, per this project's
standing discipline of designing a change before executing an
open-ended one (same posture as the v0.72.0 flag-before-proceeding for
the original C++/llama.cpp pivot).

**What "full engine rewrite" could mean, three readings, from
narrowest to broadest:**

1. **Finish the R6 opportunistic-port queue to completion** — every
remaining pure-math/no-I/O function gets ported (the `maybe_reclaim`/
`tick_flood`/hydrology remainder above), including functions that
need a genuine same-pass-dependency-safe design (a callback-into-
Python-RNG pattern, or restructuring the algorithm itself to remove
the dependency). This is a continuation of exactly what's been
happening since v0.72.0 — no new architectural category, just closing
out what's left. Lowest risk, most consistent with "sixteen provably-
equivalent increments, not a rewrite."

2. **Port the object graph itself** (`Agent`, `Settlement`, `Building`,
`Population`, terrain grid) into C++ classes that Python holds
handles to, with the orchestration logic (`population.py`/
`engine.py`/`buildings.py`) becoming thin Python wrappers calling into
compiled tick methods. This is what "engine rewrite" most naturally
means as English, and is a different kind of change from every module
shipped so far: modules 1-16 all took a *pure function* operating on
already-resolved primitives and ported the function in isolation,
verified against the *existing* Python object graph as ground truth.
Porting the object graph itself removes that ground truth — there's
no longer an "existing Python version" to A/B against for the ported
classes themselves, only for the tick-level behavior they produce.
This is the R5 scoping document's own explicit boundary ("`population.
py`/`engine.py`/`buildings.py` are explicitly NOT ported and are not
simple mechanical translations") — reading 2 crosses exactly that
boundary. Substantially higher risk given no automated test suite;
would need a much heavier verification harness (full snapshot-state
diffing across thousands of ticks, not just the event-hash soak) built
*before* the first class moves, not after.

3. **Rewrite everything except SQLite/asyncio/FastAPI** (the standing
"stays Python" carve-out from v0.72.5) — the most literal reading of
"full engine rewrite," effectively reading 2 plus the LLM-adjacent
orchestration (`_schedule_llm_job`, the tick-job dispatch table,
`CognitionRunner`) reimplemented in C++ with Python only as a thin
FastAPI/SQLite shell calling into a compiled engine core. This is a
different program from Hearthmind-as-it-exists — the "plain-Python
hackability the whole workflow depends on" (v0.63.0's stated reason
the original full-port was recommended against) would be gone for the
entire simulation core, leaving only the web/persistence edges
hackable in Python. Given "Determinism/reproducibility is NOT a
requirement" and the CLAUDE.md-stated LLM/deterministic split must
stay exactly as documented, this reading doesn't unlock anything the
simulation's design priorities (emergence, believable causality,
persistent identity) actually need — it's a pure engineering
undertaking with no design-priority payoff of its own.

**Module 17 shipped (v0.73.2): `maybe_reclaim`, closing the R7
opportunistic queue's last individually-portable item.** Used a new
design — callback into Python's `rng.random` per conditional roll,
instead of pre-drawing — since `maybe_reclaim` genuinely has the
same-pass dependency the pre-draw pattern can't handle (confirmed
since v0.72.11). See `cpp/src/reclaim.cpp`. `tick_flood`/the rest of
`world/hydrology.py` remain the only queued R7 items, both already
individually assessed as not worth a native module (too little
batchable content) or not yet traced.

**Module 18 shipped (v0.73.2): `SimClock.advance()`, first R8
slice.** See docs/DECISIONS.md for the full writeup. Chosen as the
first object-graph/engine-tick-loop target because it has zero
references to any other mutable object and is the single highest
call-frequency function in the codebase. Verified via a 200,000-tick
sequential lockstep A/B (the longest verification run in this
project's native-port history) — 0 mismatches. `cpp/src/sim_clock.cpp`.

**User confirmed (v0.73.2): pursue reading 1 AND reading 2 together.**
Reading 3 remains not recommended, unchanged from the original
assessment above. Reading 1 continues under R6/R7 exactly as before —
module 17 (below) closed its last individually-portable item this
version. Reading 2 has its first real slice shipped: `SimClock.
advance()` (module 18, below), chosen over `Tile`/the terrain grid as
the literal first move because it's *more* isolated still (zero
references to any other mutable object at all, vs. terrain's still-
fairly-clean but slightly larger surface of hundreds of `terrain[y][x]`
call sites across many modules) — a smaller, safer first proof of the
whole pattern (build, dispatch, fallback, verify, soak) before
tackling something with more call sites to keep behavior-identical.
**Verification harness shipped (v0.74.0)**: `scripts/verify_native_
soak.py` — the heavier full-state-diffing harness the original scoping
called for. Hashes the complete `World.to_dict()` snapshot every tick
(not just the event-hash soak's narrated-consequences view) across
every native module's toggle in one coordinated pass, sanity-checked
against two different seeds to confirm it actually detects divergence
before trusting a "match" result. All eighteen modules shipped through
v0.73.3 pass full per-tick state equality across a 6000-tick, 4-seed
run — see docs/DECISIONS.md's v0.74.0 entry. Committed to the repo
(prior soaks were one-off shell invocations never saved) so it's
reusable, not re-derived, in whichever future session actually starts
the terrain-grid slice.

**Next R8 slice, not yet started**: the terrain grid remains the
recommended second target (least entangled of the *remaining* pieces),
but swapping `World.terrain`'s actual type away from `list[list[Tile]]`
touches hundreds of call sites across `world/*.py`/`agents/population.
py`/`settlement/buildings.py` that all do `terrain[y][x].biome`-style
access — this needs its own dedicated design pass (a compatibility
shim preserving existing indexing syntax, or a more surgical opt-in
path) before any code moves, not a same-session follow-on to module 18
or the verification harness. The tooling half of "build the harness
before the port" is now done; the design-and-port half is still
queued.

## One-line summary for CLAUDE.md / CHANGELOG

Audit found the codebase clean (near-zero dead code, no wasteful
hotspots); shipped a safe dedup pass (shared `util.py`: `clamp` +
`namespaced_rng`/`namespaced_roll`, import hygiene), proven byte-
identical over a 7000-tick run; documented the three-big-file split
(R1 mixins), scheduler-registry (R2), and the declined numpy pass (R4)
as sequenced future work.
