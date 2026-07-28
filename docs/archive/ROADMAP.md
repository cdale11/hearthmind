# Roadmap

Trimmed 2026-07 per explicit user request ("trim all the docs and keep
recent few details only") — this file was a phase-by-phase checklist
(A-H) that is now **fully shipped, item for item**. The detailed
per-item rationale/verification for each now lives only in
`CHANGELOG.md` and `docs/DECISIONS.md`; this file keeps just the
status pointer and the cross-cutting practices that stay relevant
going forward.

**Status**: Phases A-H (original scope) and the long-term vision's
Phases I-N (`docs/VISION-2026-07.md`) are all shipped at least a v1.
See `CLAUDE.md`'s "Current state" section for the newest work and
`CHANGELOG.md` for the complete version-by-version history. No further
roadmap phase is currently green-lit — the next direction is whatever
the user asks for next.

**Emergence is the primary objective**, unchanged since project
inception: every system exists to produce behavior nobody scripted.
Systems are judged by what they let *emerge* from their interaction,
not by how complete they are in isolation. "Maximize emergence per LLM
call" (docs/VISION-2026-07.md) is the concrete standing test for any
new LLM-touching feature.

## Cross-cutting practices, ongoing at every phase

- **Docs/CHANGELOG discipline.** Every batch of work updates
  `README.md`, `CHANGELOG.md`, and `docs/DECISIONS.md` as part of the
  work, not after — see CLAUDE.md's "Workflow rules".
- **Release testing.** See `docs/TESTING.md` for the checklist run
  before every release.
- **Backward-compatible migrations.** Detect-missing-key, backfill,
  log, persist-once — the template for every save-format change since
  Phase A.
