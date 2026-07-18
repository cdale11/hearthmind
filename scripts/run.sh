#!/usr/bin/env bash
# Builds hearthmind._native, then launches llama-server (tuned per
# README's "Running the LLM (llama.cpp)" section) and hearthmind.server
# together as one command — "start the game" is one script instead of
# manually coordinating build + two processes.
#
# Usage:
#   MODEL_PATH=/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf ./scripts/run.sh
#   MODEL_PATH=... ./scripts/run.sh --db world.sqlite3 --llm-core-cast-size 12
#
# Every argument after the script name is passed straight through to
# `python -m hearthmind.server` (e.g. --db, --seed, --llm-disabled).
# Ctrl+C (or a plain `kill`) stops both processes cleanly — hearthmind
# gets its normal SIGINT/SIGTERM shutdown (final snapshot, see
# server.py) before llama-server is stopped.
#
# This script does NOT build or install llama.cpp/llama-server — build
# it yourself (see README) and point LLAMA_SERVER_BIN at the resulting
# binary, or have it already on PATH. It only builds hearthmind._native
# (fast, local, pure-Python fallback if skipped/failed — SKIP_NATIVE_
# BUILD=1 to skip).
#
# Configurable via environment variables (all optional; the llama-server
# flag defaults below match the confirmed-working GPU-offload recipe —
# see README, "Running the LLM (llama.cpp)"):
#   MODEL_PATH          Path to a GGUF model file. Required unless
#                        --llm-disabled is passed through in "$@".
#   LLAMA_SERVER_BIN     Path to the llama-server binary.
#                        Default: llama-server (resolved via PATH)
#   LLAMA_HOST           Host:port llama-server binds to (also passed to
#                        hearthmind via --llm-llamacpp-host).
#                        Default: http://localhost:8080
#   LLAMA_PARALLEL       Default: 2 (v0.81.0, up from a hardcoded 1 —
#                        matches Config.llm_max_concurrent; see its
#                        docstring for the live-diagnostics rationale:
#                        the earlier swap crisis this hardcoded 1
#                        responded to is resolved, and the live symptom
#                        had shifted to a single-lane queue serializing
#                        every job behind whatever's already running).
#                        Keep this in sync with Config.llm_max_concurrent
#                        — llama-server can't usefully run more concurrent
#                        requests than the Python side will ever send.
#   LLAMA_CTX_SIZE       Default: 5120 (v0.81.0) = Config.llm_num_ctx
#                        (2560) * LLAMA_PARALLEL (2). llama-server's
#                        --ctx-size is a TOTAL, divided evenly across its
#                        --parallel slots — raising LLAMA_PARALLEL without
#                        raising this in step would silently HALVE the
#                        context each concurrent request actually gets,
#                        not add real throughput. Keep this synced to
#                        `llm_num_ctx * LLAMA_PARALLEL` any time either
#                        changes. For genuinely CPU-only/8GB hardware,
#                        explicitly set LLAMA_CTX_SIZE=1280
#                        LLAMA_PARALLEL=1 LLAMA_N_GPU_LAYERS=0 — see
#                        README's 8GB section.
#   LLAMA_BATCH_SIZE     Default: 512 (v0.78.5, down from llama.cpp's own
#                        2048 — tuned for this project's short strict-JSON
#                        prompts; a long sequential prompt just chunks
#                        into a couple of passes instead of one).
#                        --batch-size (the logical prompt-processing
#                        batch) sizes part of the compute-buffer
#                        allocation alongside the KV cache — that
#                        allocation already scales with LLAMA_PARALLEL on
#                        its own, so this is left unraised at parallel=2
#                        rather than compounding the increase; revisit if
#                        prompt-processing throughput measures short with
#                        2 lanes active. Must stay >= LLAMA_UBATCH_SIZE
#                        (llama.cpp's own requirement). Empty disables
#                        the flag, falling back to llama.cpp's default.
#   LLAMA_UBATCH_SIZE    Default: 128 (v0.78.5, down from llama.cpp's own
#                        512 — the physical/compute batch; this is the
#                        more direct compute-buffer-memory lever of the
#                        two). Empty disables the flag.
#   LLAMA_DEFRAG_THOLD   Default: 0.1 (v0.78.5) — passes --defrag-thold,
#                        triggering a KV-cache defragmentation pass once
#                        fragmentation crosses this fraction. Aimed
#                        squarely at "runs stably for years": a session
#                        this long will see many different prompt
#                        lengths reuse the same KV cache over time, and
#                        periodic defrag keeps that from slowly
#                        fragmenting worse than a fresh restart would be.
#                        Empty omits the flag (older builds without it,
#                        or if you'd rather rely on periodic restarts —
#                        see LLAMA_RESTART_HOURS below).
#   LLAMA_CACHE_RAM      Default: 0 (v0.87.5, 2026-07 prompt-density
#                        audit). Passes --cache-ram, llama-server's
#                        host-RAM prompt cache for reusing cross-call
#                        shared prefixes (default 8192 MiB / 8GB if
#                        this flag is never passed at all — a real
#                        reservation ceiling on hardware this project
#                        already treats as memory-scarce). Genuinely
#                        useful for a shared-system-prompt/many-similar-
#                        prompts workload; this project's prompts are
#                        the opposite (every cognition/dialogue/
#                        chronicle/... call is freshly built and largely
#                        unique per agent/settlement/tick — see README's
#                        "Prompt density" section), so the realistic
#                        cache-hit rate is low and the 8GB default buys
#                        little. Set to a positive MiB value (or -1 for
#                        no limit) to re-enable if a live `/diagnostics.
#                        llm_prompt_stats` reading ever shows this
#                        workload's shape has changed; empty omits the
#                        flag for an older llama-server build that
#                        predates it.
#   LLAMA_METRICS_ENDPOINT Default: 1 (enabled, v0.87.6). Passes --metrics,
#                        exposing llama-server's own Prometheus `/metrics`
#                        endpoint (KV-cache occupancy, queue depth,
#                        prompt/predicted-token throughput) — the "poll
#                        llama-server's own /slots|/metrics" step v0.87.5
#                        flagged as recommended-but-deferred.
#                        `SimulationEngine` polls it every 30s (real
#                        server-side numbers, not the char-based
#                        estimates `llm_prompt_stats` uses) and surfaces
#                        it at `/diagnostics.llama_server_metrics`.
#                        Deliberately does NOT pass --slots (that
#                        endpoint echoes live prompt content back for
#                        prompt-cache inspection — a real privacy
#                        exposure this project doesn't need to take on
#                        for aggregate numbers /metrics already
#                        provides). Set to 0/empty to omit the flag for
#                        an older llama-server build that predates it.
#   LLAMA_RESTART_HOURS  Default: 0 (disabled). v0.86.9 — --defrag-thold
#                        only addresses KV-cache fragmentation; general
#                        heap fragmentation in a llama-server process
#                        that's been alive for many days/weeks of varied
#                        allocation sizes (many different prompt/response
#                        lengths) is a separate, well-known long-running-
#                        C++-process failure mode, and shows up as the
#                        same symptom a live report flagged: overall
#                        memory usage slowly climbing and swap increasing
#                        specifically on very long runs, never on short
#                        ones. Set this to a positive integer (e.g. 12 or
#                        24) to have run.sh restart llama-server on that
#                        cadence — a clean process restart is the
#                        reliable way to reclaim heap fragmentation that
#                        --defrag-thold can't touch. hearthmind.server
#                        PAUSES ticking outright for the ~1-10s restart
#                        window (v0.87.3, via a sentinel file this
#                        script's restart supervisor touches/removes
#                        around the restart — see Config.llm_restart_
#                        sentinel_path) rather than leaving it to every
#                        individual LLM call to fall back on its own —
#                        the browser UI shows a "llama-server
#                        restarting" indicator while paused, and
#                        `/diagnostics.llama_server_restarts_total`
#                        counts how many restarts have happened this
#                        session. Model reload time (seconds) scales with
#                        model size and disk speed, not with how long the
#                        previous instance had been running.
#   LLAMA_MALLOC_ARENA_MAX / LLAMA_MALLOC_MMAP_THRESHOLD_KB /
#   LLAMA_MALLOC_TRIM_THRESHOLD_KB
#                        All default empty/unset (glibc's own defaults,
#                        unchanged behavior). v0.87.2 — a complement to
#                        LLAMA_RESTART_HOURS that reduces the RATE
#                        general heap fragmentation accumulates, instead
#                        of periodically reclaiming it via restart (the
#                        two are not mutually exclusive; try tuning
#                        first, keep restart as the reliable backstop).
#                        glibc's default allocator behavior for a
#                        multi-threaded, long-lived process handling many
#                        different allocation sizes (llama-server's own
#                        shape: KV-cache slots, compute buffers, and
#                        many different prompt/response string lengths
#                        across --parallel worker threads) is a
#                        well-documented fragmentation source, tunable
#                        via three glibc-recognized env vars (`man
#                        mallopt`), exported ONLY into the llama-server
#                        child process, never into hearthmind.server or
#                        this script itself:
#                        - LLAMA_MALLOC_ARENA_MAX -> MALLOC_ARENA_MAX:
#                          caps the number of per-thread malloc arenas.
#                          glibc's default (roughly 8x core count) lets
#                          each thread fragment its own arena
#                          independently; capping this (try matching
#                          LLAMA_PARALLEL, e.g. 2) trades a little lock
#                          contention for materially less fragmentation
#                          on a many-core box.
#                        - LLAMA_MALLOC_MMAP_THRESHOLD_KB ->
#                          MALLOC_MMAP_THRESHOLD_ (converted to bytes):
#                          allocations at or above this size go through
#                          mmap (returned to the OS immediately on free)
#                          instead of the sbrk'd heap (which glibc can
#                          hold onto indefinitely once fragmented). glibc
#                          normally raises this threshold dynamically
#                          over a process's lifetime, which is itself a
#                          known contributor to long-run heap bloat;
#                          pinning it (try 128, i.e. 128KB) disables that
#                          dynamic adjustment. Try a value a bit below
#                          your typical KV-cache-slot/compute-buffer
#                          allocation size so those consistently round-
#                          trip through mmap.
#                        - LLAMA_MALLOC_TRIM_THRESHOLD_KB ->
#                          MALLOC_TRIM_THRESHOLD_ (converted to bytes):
#                          how much contiguous free space at the top of
#                          the heap glibc keeps before returning it to
#                          the OS. Lowering this (try 4096, i.e. 4MB)
#                          makes glibc give memory back sooner after a
#                          burst of large short-lived allocations,
#                          trading a few more syscalls for a lower
#                          resident-but-unused floor.
#                        These are measured trade-offs, not free wins —
#                        size/verify via /diagnostics.system_memory over
#                        a real multi-day run before and after, same
#                        "size first" discipline as LLAMA_MLOCK below.
#   LLAMA_MLOCK          Default: unset (off). Set to 1 to pass --mlock,
#                        which pins llama-server's memory in RAM and
#                        refuses to let the OS swap it. This does NOT
#                        reduce memory usage — it converts "swap and get
#                        slow" into "fail to start / get OOM-killed if
#                        undersized." Only turn this on AFTER confirming
#                        via /diagnostics.system_memory that llama-server's
#                        RSS comfortably fits your real available RAM with
#                        margin (lower --ctx-size/--batch-size first if
#                        not) — for a service meant to run unattended for
#                        years, failing loudly at startup beats silently
#                        degrading into swap thrashing months in. See
#                        README's "eliminating swap" guidance (v0.78.2).
#   LLAMA_THREADS        Default: every CPU core ($(nproc))
#   LLAMA_N_GPU_LAYERS   Default: auto (let llama.cpp size the GPU-layer
#                        split to available VRAM — see LLAMA_FIT below;
#                        also accepts 'all', an exact number, or 0 to
#                        force CPU-only). NOTE: 'auto'/'all' need a recent
#                        llama.cpp build; on an older binary that only
#                        takes a number, set LLAMA_N_GPU_LAYERS=999.
#   LLAMA_FIT            Default: on. Passes llama-server's --fit flag,
#                        which auto-adjusts unset args (incl. the GPU
#                        layer count when -ngl is 'auto') to fit device
#                        memory — the dynamic-allocation path, replacing
#                        the old hardcoded 999. Set empty (LLAMA_FIT=) to
#                        omit the flag entirely on older builds that don't
#                        support it.
#   LLAMA_FIT_TARGET     Default: 2048 (v0.81.0, down from 2560 in
#                        v0.78.5) — MiB margin per device --fit leaves
#                        free rather than offloading. v0.78.5 raised this
#                        for the shared-memory-iGPU case ("VRAM" there is
#                        drawn from the same system-RAM pool --ctx-size/
#                        hearthmind itself also need); a live diagnostic
#                        since then (see Config.llm_max_concurrent's
#                        docstring) showed real headroom to spare
#                        (mem_available 3321MB of 7045MB, swap ~0) rather
#                        than pressure, so this pulls back toward a
#                        slightly larger offload — freeing a bit more
#                        general system RAM for LLAMA_PARALLEL's second
#                        KV-cache slot rather than reserving it unused.
#                        Raise back toward 2560+ if a fresh
#                        /diagnostics.system_memory reading shows
#                        pressure again. Set empty (LLAMA_FIT_TARGET=) to
#                        restore llama.cpp's own default, e.g. on a
#                        discrete GPU where VRAM genuinely is separate.
#   LLAMA_CACHE_TYPE_K   Default: q8_0
#   LLAMA_CACHE_TYPE_V   Default: q8_0
#   LLAMA_FLASH_ATTN     Default: on. Passes --flash-attn on|off|auto —
#                        lower memory + faster attention on supported
#                        backends. Set LLAMA_FLASH_ATTN=auto if a build/
#                        backend combination rejects "on" outright, or
#                        empty (LLAMA_FLASH_ATTN=) to omit the flag on an
#                        older llama-server that doesn't have it.
#   LLAMA_REASONING      Default: off. Every prompt here wants one short
#                        strict-JSON answer — hybrid-thinking models
#                        (Qwen3 and similar) burn real tokens/latency/
#                        memory on a <think> block nobody reads, so
#                        reasoning is off by default (--reasoning off
#                        --reasoning-budget 0, both confirmed working).
#                        Set LLAMA_REASONING=auto to restore the model's
#                        own default, or empty (LLAMA_REASONING=) to omit
#                        both flags on an older llama-server.
#   SKIP_NATIVE_BUILD    1 to skip building hearthmind._native. Default: 0.
#   LLAMA_EXTRA_ARGS     Extra raw flags appended to the llama-server
#                        command line.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-llama-server}"
LLAMA_HOST="${LLAMA_HOST:-http://localhost:8080}"
LLAMA_PARALLEL="${LLAMA_PARALLEL:-2}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-5120}"
LLAMA_THREADS="${LLAMA_THREADS:-$(nproc 2>/dev/null || echo 4)}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-auto}"
LLAMA_FIT="${LLAMA_FIT-on}"
LLAMA_FIT_TARGET="${LLAMA_FIT_TARGET-2048}"
LLAMA_CACHE_TYPE_K="${LLAMA_CACHE_TYPE_K:-q8_0}"
LLAMA_CACHE_TYPE_V="${LLAMA_CACHE_TYPE_V:-q8_0}"
LLAMA_FLASH_ATTN="${LLAMA_FLASH_ATTN-on}"
LLAMA_REASONING="${LLAMA_REASONING-off}"
LLAMA_BATCH_SIZE="${LLAMA_BATCH_SIZE-512}"
LLAMA_UBATCH_SIZE="${LLAMA_UBATCH_SIZE-128}"
LLAMA_DEFRAG_THOLD="${LLAMA_DEFRAG_THOLD-0.1}"
LLAMA_CACHE_RAM="${LLAMA_CACHE_RAM-0}"
LLAMA_METRICS_ENDPOINT="${LLAMA_METRICS_ENDPOINT-1}"
LLAMA_MLOCK="${LLAMA_MLOCK-}"
LLAMA_RESTART_HOURS="${LLAMA_RESTART_HOURS-0}"
LLAMA_MALLOC_ARENA_MAX="${LLAMA_MALLOC_ARENA_MAX-}"
LLAMA_MALLOC_MMAP_THRESHOLD_KB="${LLAMA_MALLOC_MMAP_THRESHOLD_KB-}"
LLAMA_MALLOC_TRIM_THRESHOLD_KB="${LLAMA_MALLOC_TRIM_THRESHOLD_KB-}"
SKIP_NATIVE_BUILD="${SKIP_NATIVE_BUILD:-0}"
LLAMA_EXTRA_ARGS="${LLAMA_EXTRA_ARGS:-}"

llm_disabled=false
for arg in "$@"; do
  if [[ "$arg" == "--llm-disabled" ]]; then
    llm_disabled=true
  fi
done

# --- build hearthmind._native (fast, local, always attempted) --------------

if [[ "$SKIP_NATIVE_BUILD" != "1" ]]; then
  echo "run.sh: building hearthmind._native (set SKIP_NATIVE_BUILD=1 to skip)..." >&2
  ( cd "$REPO_ROOT" && python setup.py build_ext --inplace ) || \
    echo "run.sh: native extension build failed — continuing on the pure-Python fallback path (see README)." >&2
fi

# --- llama-server must already exist ----------------------------------------

if [[ "$llm_disabled" == false ]] && ! command -v "$LLAMA_SERVER_BIN" >/dev/null 2>&1 && [[ ! -x "$LLAMA_SERVER_BIN" ]]; then
  echo "run.sh: no llama-server binary found at/on PATH as '$LLAMA_SERVER_BIN'." >&2
  echo "        Build or install llama.cpp yourself (see README, \"Running the LLM (llama.cpp)\")," >&2
  echo "        then set LLAMA_SERVER_BIN to the binary path, or pass --llm-disabled to skip the LLM." >&2
  exit 1
fi

llama_pid=""
hearthmind_pid=""
restart_supervisor_pid=""
# llama_pid is only ever read/written by THIS process when
# LLAMA_RESTART_HOURS is unset — the pidfile only starts mattering once
# the restart supervisor (a separate background subshell, see below) can
# replace the running llama-server on its own schedule; a subshell can't
# write back to this shell's `llama_pid` variable, so the pidfile is the
# one shared channel both sides read/write through instead.
llama_pidfile="$(mktemp)"
write_llama_pid() { echo "$1" > "$llama_pidfile"; }
read_llama_pid() { cat "$llama_pidfile" 2>/dev/null || true; }

# Sentinel file for hearthmind.server (v0.87.3, see Config.llm_restart_
# sentinel_path's docstring): only created when LLAMA_RESTART_HOURS is
# actually enabled below, so the default path adds zero overhead (the
# Python side's check is skipped entirely when the sentinel path is
# never passed). Deliberately a `mktemp -u` (a fresh, not-yet-existing
# path) rather than `mktemp` itself, since the signal IS the file's
# existence — creating it up front would read as "already restarting"
# before the first restart ever happens.
llama_restart_sentinel="$(mktemp -u)"

# Registered once, up front, so it correctly cleans up whichever
# process(es) are alive regardless of where in the script a signal or
# early exit happens — pids are read at call time (llama's via the
# pidfile, so it sees a supervisor-issued restart too), not
# trap-registration time, so this stays correct as they get populated.
cleanup() {
  if [[ -n "$hearthmind_pid" ]] && kill -0 "$hearthmind_pid" 2>/dev/null; then
    kill -TERM "$hearthmind_pid" 2>/dev/null || true
    wait "$hearthmind_pid" 2>/dev/null || true
  fi
  if [[ -n "$restart_supervisor_pid" ]] && kill -0 "$restart_supervisor_pid" 2>/dev/null; then
    kill -TERM "$restart_supervisor_pid" 2>/dev/null || true
  fi
  local pid; pid="$(read_llama_pid)"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    echo "run.sh: stopping llama-server (pid $pid)..." >&2
    kill -TERM "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  fi
  rm -f "$llama_pidfile" "$llama_restart_sentinel" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Launches llama-server with the tuned flags above and records its pid
# to $llama_pidfile. Echoes the pid on stdout so both the initial launch
# and the periodic-restart supervisor (same flags, same function) can
# capture it. Safe to call more than once per process lifetime — every
# flag is re-read from the same env vars each call.
start_llama_server() {
  local llama_port fit_str fa_str reasoning_str batch_str ubatch_str mlock_str defrag_str pid
  local -a malloc_env
  llama_port="${LLAMA_HOST##*:}"
  # glibc malloc tuning (v0.87.2) — see LLAMA_MALLOC_ARENA_MAX/LLAMA_
  # MALLOC_MMAP_THRESHOLD_KB/LLAMA_MALLOC_TRIM_THRESHOLD_KB docstrings
  # above for the full rationale: a complement to LLAMA_RESTART_HOURS
  # that reduces the RATE of heap fragmentation instead of periodically
  # reclaiming it via restart. All three default empty/unset (glibc's
  # own defaults, unchanged behavior) — opt in only after a live
  # /diagnostics.system_memory reading shows llama-server RSS climbing
  # over a multi-day session. Built as an `env` prefix (not exported
  # into this script's own environment) so it applies only to the
  # llama-server child process, never to hearthmind.server or this
  # script itself.
  malloc_env=()
  [[ -n "$LLAMA_MALLOC_ARENA_MAX" ]] && malloc_env+=("MALLOC_ARENA_MAX=$LLAMA_MALLOC_ARENA_MAX")
  [[ -n "$LLAMA_MALLOC_MMAP_THRESHOLD_KB" ]] && \
    malloc_env+=("MALLOC_MMAP_THRESHOLD_=$((LLAMA_MALLOC_MMAP_THRESHOLD_KB * 1024))")
  [[ -n "$LLAMA_MALLOC_TRIM_THRESHOLD_KB" ]] && \
    malloc_env+=("MALLOC_TRIM_THRESHOLD_=$((LLAMA_MALLOC_TRIM_THRESHOLD_KB * 1024))")
  # Build the optional --fit args: only passed when LLAMA_FIT is non-empty,
  # so an older llama-server that predates the flag can omit it with
  # LLAMA_FIT=. --fit lets llama.cpp dynamically size the offload to
  # available VRAM (paired with -ngl auto), replacing the old hardcoded
  # -ngl 999.
  fit_str=""
  if [[ -n "$LLAMA_FIT" ]]; then
    fit_str="--fit $LLAMA_FIT"
    [[ -n "$LLAMA_FIT_TARGET" ]] && fit_str="$fit_str --fit-target $LLAMA_FIT_TARGET"
  fi
  # --flash-attn: lower memory + faster attention on supported backends.
  # --reasoning off --reasoning-budget 0: every prompt here wants one
  # short strict-JSON answer, never a <think> block — confirmed working,
  # skips the wasted tokens/latency/memory a hybrid-thinking model (Qwen3
  # and similar) otherwise spends on reasoning nobody reads. Both are
  # empty-string-omits-the-flag so an older llama-server still runs.
  fa_str=""
  [[ -n "$LLAMA_FLASH_ATTN" ]] && fa_str="--flash-attn $LLAMA_FLASH_ATTN"
  reasoning_str=""
  if [[ -n "$LLAMA_REASONING" ]]; then
    reasoning_str="--reasoning $LLAMA_REASONING"
    [[ "$LLAMA_REASONING" == "off" ]] && reasoning_str="$reasoning_str --reasoning-budget 0"
  fi
  # --batch-size/--ubatch-size: added optional (v0.78.1), given real
  # tuned defaults in v0.78.5 (512/128, down from llama.cpp's own
  # 2048/512) once the project moved to a single-lane (--parallel 1)
  # workload where large batching buys nothing but memory. Set either
  # to "" to fall back to llama.cpp's own default instead.
  batch_str=""
  [[ -n "$LLAMA_BATCH_SIZE" ]] && batch_str="--batch-size $LLAMA_BATCH_SIZE"
  ubatch_str=""
  [[ -n "$LLAMA_UBATCH_SIZE" ]] && ubatch_str="--ubatch-size $LLAMA_UBATCH_SIZE"
  mlock_str=""
  [[ "$LLAMA_MLOCK" == "1" ]] && mlock_str="--mlock"
  defrag_str=""
  [[ -n "$LLAMA_DEFRAG_THOLD" ]] && defrag_str="--defrag-thold $LLAMA_DEFRAG_THOLD"
  # --cache-ram (v0.87.5, 2026-07 prompt-density audit): llama-server's
  # host-RAM prompt cache for cross-call prefix reuse, DEFAULTS TO 8192
  # (8GB!) in stock llama-server if never passed — a huge reservation
  # ceiling on hardware this project already treats as memory-scarce.
  # Genuinely useful for a shared-system-prompt/many-similar-prompts
  # workload; this project's prompts are the opposite (every cognition/
  # dialogue/chronicle/... call is a freshly-built, largely-unique
  # string per agent/settlement/tick — see README's prompt-density
  # section) so the realistic cache-hit rate is low and the 8GB ceiling
  # buys little. Default 0 disables it outright; set LLAMA_CACHE_RAM to
  # a positive MiB value (or -1 for no limit) to re-enable if a live
  # `/diagnostics.llm_prompt_stats` reading ever shows this workload's
  # shape has changed. Empty string omits the flag for an older
  # llama-server build that predates it.
  cache_ram_str=""
  [[ -n "$LLAMA_CACHE_RAM" ]] && cache_ram_str="--cache-ram $LLAMA_CACHE_RAM"
  # --metrics (v0.87.6): exposes /metrics (Prometheus text, KV-cache
  # occupancy + queue depth + throughput counters, no prompt content) so
  # SimulationEngine can poll real server-side numbers instead of its own
  # char-based estimates — see the LLAMA_METRICS_ENDPOINT doc block above.
  metrics_str=""
  [[ "$LLAMA_METRICS_ENDPOINT" == "1" ]] && metrics_str="--metrics"
  echo "run.sh: starting llama-server on $LLAMA_HOST (ctx=$LLAMA_CTX_SIZE, parallel=$LLAMA_PARALLEL, threads=$LLAMA_THREADS, gpu-layers=$LLAMA_N_GPU_LAYERS, fit=${LLAMA_FIT:-off}/target=${LLAMA_FIT_TARGET:-default}, flash-attn=${LLAMA_FLASH_ATTN:-off}, reasoning=${LLAMA_REASONING:-model default}, kv=$LLAMA_CACHE_TYPE_K/$LLAMA_CACHE_TYPE_V, batch=${LLAMA_BATCH_SIZE:-default}/${LLAMA_UBATCH_SIZE:-default}, defrag=${LLAMA_DEFRAG_THOLD:-off}, cache-ram=${LLAMA_CACHE_RAM:-server default}, metrics=${LLAMA_METRICS_ENDPOINT:-off}, mlock=${LLAMA_MLOCK:-off}, malloc-tuning=${malloc_env[*]:-off})..." >&2
  # shellcheck disable=SC2086  # $fit_str/$fa_str/$reasoning_str/$batch_str/$ubatch_str/$mlock_str/$defrag_str/$cache_ram_str/$metrics_str/$LLAMA_EXTRA_ARGS are intentionally word-split
  env "${malloc_env[@]}" "$LLAMA_SERVER_BIN" \
    --model "$MODEL_PATH" \
    --ctx-size "$LLAMA_CTX_SIZE" \
    --parallel "$LLAMA_PARALLEL" \
    --cache-type-k "$LLAMA_CACHE_TYPE_K" \
    --cache-type-v "$LLAMA_CACHE_TYPE_V" \
    $fa_str \
    $reasoning_str \
    $batch_str \
    $ubatch_str \
    $defrag_str \
    $metrics_str \
    $cache_ram_str \
    $mlock_str \
    --no-mmproj \
    --port "$llama_port" \
    --n-gpu-layers "$LLAMA_N_GPU_LAYERS" \
    $fit_str \
    --threads "$LLAMA_THREADS" \
    $LLAMA_EXTRA_ARGS &
  pid=$!
  write_llama_pid "$pid"
}

# Polls /health until llama-server (pid $1) answers or dies. Shared by
# the initial launch and the periodic-restart supervisor.
wait_llama_ready() {
  local pid="$1" ready=false
  for _ in $(seq 1 60); do
    if curl -fsS "$LLAMA_HOST/health" >/dev/null 2>&1; then
      ready=true
      break
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      return 1
    fi
    sleep 1
  done
  [[ "$ready" == true ]]
}

if [[ "$llm_disabled" == false ]]; then
  if [[ -z "${MODEL_PATH:-}" ]]; then
    echo "run.sh: MODEL_PATH is required (path to a GGUF model file)." >&2
    echo "        Pass --llm-disabled to skip the LLM entirely instead." >&2
    exit 1
  fi

  start_llama_server
  llama_pid="$(read_llama_pid)"
  echo "run.sh: waiting for llama-server to become ready..." >&2
  if wait_llama_ready "$llama_pid"; then
    echo "run.sh: llama-server is up." >&2
  else
    if kill -0 "$llama_pid" 2>/dev/null; then
      echo "run.sh: llama-server did not become ready within 60s — check its output above." >&2
    else
      echo "run.sh: llama-server exited before becoming ready — check the model path and build." >&2
    fi
    exit 1
  fi

  # Periodic restart (v0.86.9, LLAMA_RESTART_HOURS — see its docstring
  # above): a clean process restart reclaims general heap fragmentation
  # that --defrag-thold's KV-cache-only defrag can't touch, which is the
  # documented cause of "memory usage climbs on very long runs but not
  # short ones" for long-lived C++ inference processes. Disabled by
  # default (LLAMA_RESTART_HOURS=0); this subshell can't write back to
  # this script's own $llama_pid, so it talks through $llama_pidfile the
  # same way the initial launch above does.
  if [[ "$LLAMA_RESTART_HOURS" =~ ^[0-9]+$ ]] && [[ "$LLAMA_RESTART_HOURS" -gt 0 ]]; then
    (
      while true; do
        sleep "$((LLAMA_RESTART_HOURS * 3600))"
        old_pid="$(read_llama_pid)"
        echo "run.sh: periodic llama-server restart (LLAMA_RESTART_HOURS=$LLAMA_RESTART_HOURS) — reclaiming any long-run heap fragmentation..." >&2
        # Sentinel file (Config.llm_restart_sentinel_path, v0.87.3):
        # hearthmind.server polls this path's existence and pauses
        # ticking outright while it's there, instead of relying on
        # every individual LLM call that happens to land during the
        # ~1-10s restart window to fall back/defer on its own. Created
        # BEFORE killing the old process (the town should pause for the
        # whole outage, not just the relaunch), removed only once the
        # replacement genuinely answers /health.
        touch "$llama_restart_sentinel"
        if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
          kill -TERM "$old_pid" 2>/dev/null || true
          wait "$old_pid" 2>/dev/null || true
        fi
        start_llama_server
        new_pid="$(read_llama_pid)"
        if wait_llama_ready "$new_pid"; then
          echo "run.sh: llama-server restarted (pid $new_pid)." >&2
        else
          echo "run.sh: llama-server failed to come back up after a periodic restart — giving up on further restarts." >&2
          rm -f "$llama_restart_sentinel"
          break
        fi
        rm -f "$llama_restart_sentinel"
      done
    ) &
    restart_supervisor_pid=$!
  fi
fi

echo "run.sh: starting hearthmind.server..." >&2
cd "$REPO_ROOT"
# Only passed when the restart supervisor above is actually active — a
# sentinel path with no supervisor touching it would just be a
# permanently-false check, so there's no reason to pay even that (tiny)
# per-loop os.path.exists() cost otherwise.
restart_sentinel_args=()
if [[ -n "$restart_supervisor_pid" ]]; then
  restart_sentinel_args=(--llm-restart-sentinel "$llama_restart_sentinel")
fi
if [[ "$llm_disabled" == false ]]; then
  python -m hearthmind.server --llm-backend llamacpp --llm-llamacpp-host "$LLAMA_HOST" "${restart_sentinel_args[@]}" "$@" &
else
  python -m hearthmind.server "${restart_sentinel_args[@]}" "$@" &
fi
hearthmind_pid=$!
wait "$hearthmind_pid"
hearthmind_status=$?
hearthmind_pid=""  # already exited — nothing left for cleanup() to do on this one
exit "$hearthmind_status"
