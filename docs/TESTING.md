# Release testing checklist

Run this before every release (every merge to the development branch that
adds a feature slice, not just tagged versions). Passing `unittest` is
necessary but not sufficient — it catches logic regressions, not "does the
actual server behave correctly," which has burned us before (see
`docs/DECISIONS.md`, M1-4a: the `sim_minutes_per_tick` bug was found by
running the server and inspecting saved state, not by reasoning about it).

None of this requires anything beyond the Python standard library today.
Once Milestone 3 (Ollama) lands, add an "LLM path" section; once Milestone
4 (browser) lands, add a "browser" section. Keep this file growing with the
project rather than starting a new one per phase.

## 1. Unit tests

```bash
python3 -m unittest discover -s tests -v
```

All tests must pass. If a test needed loosening or deleting to make this
true, that's a regression in disguise — fix the code or justify the test
change in the commit message, don't just delete the assertion.

## 2. Fresh-world smoke test

Start a brand-new world on a throwaway database, let it run for real
(don't just call internal methods — invoke the actual CLI entrypoint), and
confirm it ticks, logs events, and snapshots without crashing:

```bash
rm -f /tmp/hm_test.sqlite3
timeout 6 python3 -m hearthmind.server --db /tmp/hm_test.sqlite3 \
    --seed 5 --width 16 --height 16 --tick-seconds 0.2 --snapshot-every 5 -v
```

Check the log for: a `genesis` event, periodic `Snapshot saved` lines, and
a clean `Engine stopping — saving final snapshot` on the timeout-triggered
SIGTERM. No tracebacks.

```bash
python3 -m hearthmind.inspect_world --db /tmp/hm_test.sqlite3
```

Sanity-check the printed summary against what changed in this release —
e.g. after Phase A, population/resource numbers should look plausible
(no negative amounts, hunger/energy in `[0, 1]`, population within the
configured cap).

## 3. Resume test

Run the server again against the *same* database and confirm it resumes
instead of regenerating:

```bash
timeout 4 python3 -m hearthmind.server --db /tmp/hm_test.sqlite3 --tick-seconds 0.2 -v
```

The log should say `Resumed world at tick N` (not "creating a new world"),
`N` should match where the previous run left off, and any `--seed`/
`--width`/`--height`/etc. flags that differ from creation should produce
the expected "ignored (creation-only field)" warnings, not silent
corruption or a crash.

## 4. Backward-compatibility / migration test

Whenever a release changes the snapshot format (adds a new subsystem,
renames a field, etc.), simulate loading an *old* save and confirm it
migrates cleanly through the real CLI, not just a unit test mock:

```bash
python3 - <<'EOF'
import json, sqlite3
conn = sqlite3.connect("/tmp/hm_test.sqlite3")
row = conn.execute("SELECT world_json FROM snapshots ORDER BY id DESC LIMIT 1").fetchone()
data = json.loads(row[0])
# Remove whatever key(s) this release added, to simulate a pre-release save.
# e.g. del data["resources"]
conn.execute(
    "INSERT INTO snapshots (tick, saved_at, world_json) VALUES (?, 0, ?)",
    (data["clock"]["tick_count"], json.dumps(data)),
)
conn.commit()
conn.close()
EOF

timeout 4 python3 -m hearthmind.server --db /tmp/hm_test.sqlite3 --tick-seconds 0.2 -v
```

Confirm the log shows the expected migration message and a
`*_migration` event appears in `inspect_world`'s recent events — and that
the *next* load of the same database does **not** re-trigger the
migration (it should only happen once per save).

## 5. Longer soak (spot-check, not every release)

For releases that touch per-tick logic that compounds over time (needs
decay, population growth, resource depletion), let a world run for a few
thousand ticks and eyeball the trend, not just a single snapshot:

```bash
timeout 30 python3 -m hearthmind.server --db /tmp/hm_soak.sqlite3 \
    --seed 1 --tick-seconds 0.01 --snapshot-every 200 -v
python3 -m hearthmind.inspect_world --db /tmp/hm_soak.sqlite3 --json
```

Look for runaway values (population exploding past its cap, hunger stuck
at exactly 1.0 for the whole population with no deaths ever triggering,
resource nodes all permanently at zero) — the kind of bug that a
20-tick unit test won't surface but a 3000-tick run will.

## 6. Clean up

```bash
rm -f /tmp/hm_test.sqlite3* /tmp/hm_soak.sqlite3*
```

Scratch databases are not committed and shouldn't linger in `/tmp` between
sessions.
