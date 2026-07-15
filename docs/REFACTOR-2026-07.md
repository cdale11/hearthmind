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

### R4. Grid-pass vectorization (`resources`/`roads`/terrain) — do **not** do without a measured need

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

## One-line summary for CLAUDE.md / CHANGELOG

Audit found the codebase clean (near-zero dead code, no wasteful
hotspots); shipped a safe dedup pass (shared `util.py`: `clamp` +
`namespaced_rng`/`namespaced_roll`, import hygiene), proven byte-
identical over a 7000-tick run; documented the three-big-file split
(R1 mixins), scheduler-registry (R2), and the declined numpy pass (R4)
as sequenced future work.
