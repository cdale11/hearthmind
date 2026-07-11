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
(~2GB weights). `llm_timeout_seconds=20`, `llm_max_concurrent=2`.

## Workflow rules

- Audit before continuing; fix regressions before new features.
- Preserve existing behavior unless explicitly changing it.
- Update README/CHANGELOG/docs/DECISIONS.md as part of the work, not after.
- Do not run the automated test suite or add new unit tests — deemed
  unreliable. Verification is the user's live diagnostic reports from
  their own machine (real Ollama, real hardware). Treat those as
  high-priority signal and the actual source of truth for "does this
  work," not anything run in this environment.
- Still reason through logic/edge cases carefully before shipping — just
  don't claim "tested" or spend effort on `unittest`.
- External libraries are allowed (no longer stdlib-only-by-default).
  Track every one in `requirements.txt` and `pyproject.toml`
  dependencies. Still prefer stdlib when it's a close call — only reach
  outside it when it buys something real (see F1's `websockets`
  precedent in docs/DECISIONS.md).
- Determinism: all randomness via `hashlib.sha256(f"{seed}:{namespace}:{tick}")`
  namespaced RNG, never bare `random`.
- Tick loop (`World.tick`) is fully synchronous; LLM calls are
  fire-and-forget async, never block a tick, always have a deterministic
  fallback (`hearthmind/llm/jobs.py`).

## Current state (v0.8.0+)

Phases A-D shipped (deterministic substrate, LLM cognition, settlements,
farming). D3/D5/D6: starvation-cascade bugs found via live-play diagnostics,
fixed. See `docs/DECISIONS.md` for the full decision log, `docs/ROADMAP.md`
for phase-by-phase plan, `CHANGELOG.md` for version history.

## Known architectural gaps (not yet built)

- Storage/granaries, production chains, trade/currency (Phase D remainder).
- Phase E (culture/history), F (browser UI), G (horror layer) — not started.
- Building placement is chance-based, not LLM/goal-driven (see DECISIONS C1).

## Conventions

- Constants live as module-level values near the dataclass they govern,
  with a one-line docstring explaining *why* the number, not what it is.
- New behavioral fixes get a lettered decision entry in `docs/DECISIONS.md`
  (D5, D6, ...) — root cause, fix, verification data.
- Regression tests for every live-play-discovered bug, named for the bug.
