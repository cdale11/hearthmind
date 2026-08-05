# Hearthmind docs — index

This project accumulated twenty-odd overlapping design documents. This
file is the map. **Read this first**; it tells you which documents are
still authoritative, which are finished history, and which one to open
for a given question.

Filed v1.34.64 as part of an explicit "clean up the docs, there are so
many and so confusing" pass. Nothing was deleted — finished documents
moved to `docs/archive/` (see the path-change note at the bottom).

---

## Start here

| If you want to… | Read |
|---|---|
| Know the standing rules and current state | `../CLAUDE.md` (project memory — the single most important file) |
| Know what the priorities are when they conflict | `CONSTITUTION.md` |
| Know what's left to build | `ROADMAP-2026-07-REMAINING.md` |
| Know why something was built the way it was | `DECISIONS.md` |
| Know what changed in a given version | `../CHANGELOG.md` |
| Run/verify a change | `TESTING.md` |

---

## Live documents (authoritative, still governing)

- **`CONSTITUTION.md`** — canonical priority/architecture guide.
  Supersedes prior audit reports where they conflict. Priority order:
  Emergence > Memory efficiency > Performance > Simplicity > Backward
  compatibility.

- **`COGNITIVE-ARCHITECTURE-2026-08-02.md`** — **the Hearthmind
  Cognitive Architecture (HCA)**, filed on explicit user direction
  reframing the project's primary goal as the study of emergent
  cognition (NPCs a consequence, not the goal). Authoritative for how
  minds are organised at *every* scale — six layers, the LLM as one
  subsystem among several, impasse-gated deliberation, a global
  workspace with broadcast, prediction-error salience. Also defines the
  **Cognitive Observatory** UI and the amended three-surface rule.
  `CONSTITUTION.md` still wins on priority ordering. Roadmap: Tier 7.
  Nothing implemented yet.

- **`ROADMAP-2026-07-REMAINING.md`** — **the** roadmap. A phase-ordered
  (Phase 1 → 9) list of every genuinely open item across the whole
  project; shipped history is summarized at its own bottom and lives in
  full in `CHANGELOG.md`/this file's own "Current state" log.

- **`DECISIONS.md`** — running design-decision log: root causes,
  rationale, verification data. Appended to by every behavioural
  change. Older entries live in `archive/DECISIONS-ARCHIVE.md`.

- **`MASTERCHECKLIST-2026-07-22.md`** — the source-of-truth spec behind
  the roadmap's Part A (25 deterministic "Body" items), Part B (5
  cognitive pillars) and Part C (the Body↔Mind "Seam"). The roadmap
  tracks status; this document holds the specs.

- **`HEARTHBENCH-RUNTIME-2026-07-23.md`** — the Tier 5 program
  (HearthBench model-selection benchmark + the Adaptive Runtime).
  Deliberately not started; sequenced after Tiers 0–4.

- **`ML-ARCHITECTURE-2026-08-01.md`** — **the AI/ML architecture to
  build.** Supersedes the audit's M0-M9 staging: every proposed model
  challenged, four removed or merged, two promoted, plus
  teacher→student distillation and outcome/reward learning folded in.
  4 layers / 8 models with three shared components. Read this for
  *what to implement*; read the audit below for *why*.

- **`ML-AUDIT-2026-08-01.md`** — the AI/ML-vs-LLM audit (**baseline
  evidence**, superseded on staging only): every current
  and planned LLM task classified (keep-LLM / split decision-from-
  narration / already-deterministic), plus the deterministic systems
  with high emergence potential that should instead learn (memory
  retrieval, attention, social graph, belief confidence, adaptive
  runtime). Carries the 9-stage M0–M9 plan the roadmap's **Tier 6**
  tracks, and the hard boundary on what must stay LLM-authored. Also
  records a correction to v1.34.168's over-broad "nothing should be
  replaced" finding.

- **`REFACTOR-2026-07.md`** — mostly shipped (R1–R5), but **R6/R7/R8
  are standing rules**, not history: R6 is the opportunistic C++-port
  queue, R7 mandates that new physical-substrate code is written in C++
  from the start, R8 is the remaining agent-tick port. Cited directly
  by CLAUDE.md.

- **`TESTING.md`** — the verification workflow. Note the standing rule:
  no automated unit-test suite is run; verification is live diagnostics
  plus ad-hoc scripts.

- **`TRAINING_RECORDER.md`** — subsystem doc for the LLM training
  recorder / dataset pipeline (`llm/recorder.py`).

### Vision documents — standing philosophy, mostly shipped

These are kept live because CLAUDE.md cites **standing rules** from
them, not because work remains. Their compact summaries are already in
CLAUDE.md; these hold the full original text.

- **`VISION-2026-07-21-SELFEVOLVING.md`** — Phases 0–5 all shipped. Kept
  for the **Body/Mind framing** correction (each pillar is one system
  with a deterministic Body half and an LLM Mind half), which is a
  standing rule.
- **`VISION-2026-07-22-LIVINGTERRARIUM.md`** — items 1.1–5.4 shipped.
  Kept for the self-modification-inside-guardrails framing.
- **`VISION-2026-07-24-LIVINGMAP.md`** — M1–M12 shipped (roadmap Tier
  1.5 closed). Kept because "the map must read as a living landscape,
  not procgen with agents on top" is a standing completeness bar on
  every future map-touching batch.

---

## Archived documents (`docs/archive/`) — finished, kept as record

Nothing here is open work. They are preserved because they explain
*why* large parts of the system look the way they do, and because
CHANGELOG entries reference them.

| Document | What it was | Status |
|---|---|---|
| `AUDIT-2026-07-20.md` | Live-run audit, P0–P3 + fine-tuning roadmap | Every P0/P1/P2/P3 item shipped |
| `IDEAS-2026-07-EMERGENCE.md` | External "what's still missing" review, §0–§9 | Fully resolved as of v0.87.31 |
| `DEFINITIVECHECKLIST-2026-07-21.md` | Full-codebase sweep, tiered rewrite plan | Tier 0/2.2 shipped; rest folded into the live roadmap |
| `REVIEW-2026-07.md` | Independent architecture review at v0.39.0 | Implemented across v0.40.0–v0.41.0 |
| `VISION-2026-07.md` | Long-term vision, Phases I–N | All six phases shipped (v0.76.1–v0.84.4) |
| `VISION-2026-07-LEARNING.md` | "The LLM learns like a human" | Fully shipped (v0.87.0–.4) |
| `ROADMAP.md` | The original Phase A–H roadmap | Fully shipped, item for item |
| `CHANGELOG-ARCHIVE.md` | Older CHANGELOG entries | Historical record |
| `DECISIONS-ARCHIVE.md` | Older DECISIONS entries | Historical record |

### Path change

These files used to live at `docs/<NAME>.md` and now live at
`docs/archive/<NAME>.md`. References in **live** documents (CLAUDE.md,
README.md, the roadmap) were updated. References inside `CHANGELOG.md`
and the archives themselves were **deliberately left as-is** — those
are historical statements about where a file was at the time, and
rewriting them would falsify the record.

---

## Conventions worth knowing

- **A "vision doc" is filed, not scheduled.** Work starts from one only
  on an explicit instruction naming a specific item. Filing a document
  never implies its contents are queued.
- **Status notes are load-bearing.** When an item ships, its entry is
  updated in place with the version and what was *not* done. Treat a
  "still open"/"not attempted" note as accurate — but re-verify against
  code before building on it, since a few have gone stale (two were
  caught and corrected in the v1.34.64 audit).
- **CLAUDE.md is the index of record for current state.** These
  documents hold depth; CLAUDE.md holds what is true right now.
