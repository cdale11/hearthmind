# Verification workflow

**Standing rule (see CLAUDE.md, "Workflow rules"): no automated unit
test suite is run and no unit tests are added — the old suite was
deemed unreliable and was deleted entirely in v0.64.0 (explicit user
decision).** Verification for every change is instead:

1. **Ad-hoc verification scripts**, written per batch and run directly
   (a real `SimulationEngine` via `open_db()` +
   `SimulationEngine.load_or_create()` + `engine._tick_once()` inside
   `asyncio.run(...)`, plus direct unit-level checks of the changed
   functions). Each batch's scripts and their results are summarized in
   the matching `docs/DECISIONS.md` entry.
2. **A multi-thousand-tick engine smoke run** confirming tick
   throughput hasn't regressed (recent batches measure 0.5–0.9 ms/tick
   with the LLM disabled) and that a full
   `World.to_dict()`/`from_dict()` serialization round-trip preserves
   the touched state.
3. **The user's live diagnostic reports** from their own machine (real
   Ollama, real 8GB hardware) — treated as the highest-priority signal
   and the actual source of truth for "does this work." Anything
   touching Ollama-side memory/latency can only be truly confirmed
   there.

## CLI smoke tests (still valid, run when touching server/persistence)

```bash
# Fresh world: ticks, logs events, snapshots, exits cleanly.
rm -f /tmp/hm_test.sqlite3*
timeout 6 python3 -m hearthmind.server --db /tmp/hm_test.sqlite3 \
    --seed 5 --width 16 --height 16 --tick-seconds 0.2 --snapshot-every 5 -v
python3 -m hearthmind.inspect_world --db /tmp/hm_test.sqlite3

# Resume: same DB, must log "Resumed world at tick N", not recreate.
timeout 4 python3 -m hearthmind.server --db /tmp/hm_test.sqlite3 --tick-seconds 0.2 -v

# Clean up.
rm -f /tmp/hm_test.sqlite3*
```

Watch for: a `genesis` event on first run, periodic `Snapshot saved`
lines, a clean `Engine stopping — saving final snapshot` on shutdown,
no tracebacks, and creation-only-flag warnings (not silent corruption)
when resume flags differ from creation.

## Real-Ollama check (user's machine)

```bash
python3 -m hearthmind.inspect_world --db world.sqlite3 --agents
```

Agents' `goal_reason` should read as genuine contextual text, not the
fallback's terse "hungry"/"tired"/"content"; `GET /diagnostics` (the
browser dev console's "Full diagnostic report" button) is the payload
to paste back for any live problem report — it answers "is the LLM
degraded," "is memory growing," and "is the DB growing" in one place.
