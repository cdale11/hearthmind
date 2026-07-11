# Hearthmind — Project Memory

Persistent, always-running town simulation. Python stdlib-only, SQLite
persistence, optional local LLM via Ollama. Repo `cdale11/hearthmind`,
branch `claude/hearthmind-overview-5bekay`.

## Response format (chat)

- Minimum tokens. No restating goals/architecture/history already in this
  file or prior chat.
- Explain only non-obvious decisions.
- Progress reports: **Changes / Tests / Known Issues / Next Milestone**
  only — no preamble, no recap.
- Ask short, specific design questions when direction is ambiguous;
  don't guess on product decisions.

## Hardware target

8GB RAM + zram swap, CPU-only inference. Default model `qwen2.5:3b`
(~2GB weights). `llm_timeout_seconds=20`, `llm_max_concurrent=4`. LLM is
on by default (`Config.llm_enabled=True`) and treated as not
budget-constrained on the user's hardware — prefer giving the LLM more
genuine decision points over deterministic/RNG-driven ones where it
plausibly improves emergence, subject to the liveness rule below.

## Workflow rules

- Audit before continuing; fix regressions before new features.
- Preserve existing behavior unless explicitly changing it.
- Update README/CHANGELOG/docs/DECISIONS.md as part of the work, not after.
- Do not run the automated test suite or add new unit tests — deemed
  unreliable. Verification is the user's live diagnostic reports from
  their own machine (real Ollama, real hardware), plus manual/ad-hoc
  verification scripts run directly in this environment. Treat the
  user's own diagnostics as high-priority signal and the actual source
  of truth for "does this work."
- Still reason through logic/edge cases carefully before shipping — just
  don't claim "tested" or spend effort on `unittest`.
- External libraries are allowed (no longer stdlib-only-by-default).
  Track every one in `requirements.txt` and `pyproject.toml`
  dependencies. Still prefer stdlib when it's a close call — only reach
  outside it when it buys something real (see F1's `websockets`
  precedent in docs/DECISIONS.md).
- **Determinism/reproducibility is NOT a project requirement** (dropped
  per explicit user instruction). The namespaced-RNG pattern
  (`hashlib.sha256(f"{seed}:{namespace}:{tick}")`) is still fine to use
  where it's the natural tool (e.g. picking among several candidates),
  and existing uses don't need to be ripped out, but new work should not
  be constrained by "must stay reproducible for the same seed" — favor
  whatever produces the most interesting emergent behavior, including
  bare `random`, wall-clock-seeded randomness, or LLM-driven
  non-deterministic choices.
- Tick loop (`World.tick`) is fully synchronous; LLM calls are
  fire-and-forget async and must never block a tick. Every LLM call
  still needs *some* fallback behavior on timeout/error (liveness, not
  determinism) — the fallback no longer needs to be reproducible, just
  non-blocking.

## Current state (v0.24.0+)

Phases A-G roadmap items are in flight; Phases A-F have substantial
content shipped (deterministic substrate now optional-determinism,
LLM cognition/dialogue/culture, settlements with real material costs,
farming, wildlife/ecology, roads, vehicles, a weather particle overlay,
a live browser UI with a dev diagnostics console). See
`docs/DECISIONS.md` for the full decision log, `docs/ROADMAP.md` for
phase-by-phase plan and the original feature checklist, `CHANGELOG.md`
for version history.

## Known architectural gaps (not yet built)

- Terrain evolution — both local activity-driven change (overharvested
  forest thins to grassland, abandoned farmland reverts) and longer-term
  climate/biome drift (temperature/precipitation trends shifting biome
  boundaries map-wide) — requested, not yet built; see chat for scoping
  notes until a DECISIONS entry exists.
- Further browser visual richness beyond the weather particle overlay
  and vehicle/building/wildlife map markers already shipped (e.g.
  smooth inter-tick agent movement interpolation, lighting/gradients).
- Per-agent inventory/trade, multiple named settlements, generational/
  family-specific agent memory, intervention ("nudge") endpoints.
- Phase G (subtle supernatural layer) — not started, deliberately last.

## Conventions

- Constants live as module-level values near the dataclass they govern,
  with a one-line docstring explaining *why* the number, not what it is.
- New behavioral fixes/features get a named or lettered decision entry
  in `docs/DECISIONS.md` — root cause (for fixes), design rationale, and
  verification data (manual/ad-hoc, not `unittest`).
