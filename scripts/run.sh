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
#   LLAMA_CTX_SIZE       Default: 2560 (matches Config.llm_num_ctx —
#                        synced in v0.78.5 so the two never drift; was
#                        1280 as a separate "CPU-only-safe floor"
#                        default while Config already defaulted to
#                        3072/2560, a real footgun if you launched via
#                        run.sh without also overriding this. For
#                        genuinely CPU-only/8GB hardware, explicitly set
#                        LLAMA_CTX_SIZE=1280 LLAMA_N_GPU_LAYERS=0 — see
#                        README's 8GB section).
#   LLAMA_BATCH_SIZE     Default: 512 (v0.78.5, down from llama.cpp's own
#                        2048 — tuned for a single-lane, `--parallel 1`
#                        workload, not a multi-user server; a long
#                        sequential prompt just chunks into a couple of
#                        passes instead of one, negligible on this
#                        project's short strict-JSON prompts). --batch-
#                        size (the logical prompt-processing batch) sizes
#                        part of the compute-buffer allocation alongside
#                        the KV cache. Must stay >= LLAMA_UBATCH_SIZE
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
#                        or if you'd rather rely on periodic restarts).
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
#   LLAMA_FIT_TARGET     Default: 2560 (v0.78.5, was empty/llama.cpp's own
#                        1024 MiB default) — MiB margin per device --fit
#                        leaves free rather than offloading. Raised for
#                        the shared-memory-iGPU case documented in
#                        README's "Running stably for years" section:
#                        "VRAM" there is drawn from the same system-RAM
#                        pool --ctx-size/hearthmind itself also need, so
#                        a bigger deliberate margin trades a little
#                        offload for real system-RAM headroom on a long-
#                        running box. Set empty (LLAMA_FIT_TARGET=) to
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
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-2560}"
LLAMA_THREADS="${LLAMA_THREADS:-$(nproc 2>/dev/null || echo 4)}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-auto}"
LLAMA_FIT="${LLAMA_FIT-on}"
LLAMA_FIT_TARGET="${LLAMA_FIT_TARGET-2560}"
LLAMA_CACHE_TYPE_K="${LLAMA_CACHE_TYPE_K:-q8_0}"
LLAMA_CACHE_TYPE_V="${LLAMA_CACHE_TYPE_V:-q8_0}"
LLAMA_FLASH_ATTN="${LLAMA_FLASH_ATTN-on}"
LLAMA_REASONING="${LLAMA_REASONING-off}"
LLAMA_BATCH_SIZE="${LLAMA_BATCH_SIZE-512}"
LLAMA_UBATCH_SIZE="${LLAMA_UBATCH_SIZE-128}"
LLAMA_DEFRAG_THOLD="${LLAMA_DEFRAG_THOLD-0.1}"
LLAMA_MLOCK="${LLAMA_MLOCK-}"
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

# Registered once, up front, so it correctly cleans up whichever
# process(es) are alive regardless of where in the script a signal or
# early exit happens — both pid variables are read at call time, not
# trap-registration time, so this stays correct as they get populated.
cleanup() {
  if [[ -n "$hearthmind_pid" ]] && kill -0 "$hearthmind_pid" 2>/dev/null; then
    kill -TERM "$hearthmind_pid" 2>/dev/null || true
    wait "$hearthmind_pid" 2>/dev/null || true
  fi
  if [[ -n "$llama_pid" ]] && kill -0 "$llama_pid" 2>/dev/null; then
    echo "run.sh: stopping llama-server (pid $llama_pid)..." >&2
    kill -TERM "$llama_pid" 2>/dev/null || true
    wait "$llama_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

if [[ "$llm_disabled" == false ]]; then
  if [[ -z "${MODEL_PATH:-}" ]]; then
    echo "run.sh: MODEL_PATH is required (path to a GGUF model file)." >&2
    echo "        Pass --llm-disabled to skip the LLM entirely instead." >&2
    exit 1
  fi

  llama_port="${LLAMA_HOST##*:}"
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
  echo "run.sh: starting llama-server on $LLAMA_HOST (ctx=$LLAMA_CTX_SIZE, threads=$LLAMA_THREADS, gpu-layers=$LLAMA_N_GPU_LAYERS, fit=${LLAMA_FIT:-off}/target=${LLAMA_FIT_TARGET:-default}, flash-attn=${LLAMA_FLASH_ATTN:-off}, reasoning=${LLAMA_REASONING:-model default}, kv=$LLAMA_CACHE_TYPE_K/$LLAMA_CACHE_TYPE_V, batch=${LLAMA_BATCH_SIZE:-default}/${LLAMA_UBATCH_SIZE:-default}, defrag=${LLAMA_DEFRAG_THOLD:-off}, mlock=${LLAMA_MLOCK:-off})..." >&2
  # shellcheck disable=SC2086  # $fit_str/$fa_str/$reasoning_str/$batch_str/$ubatch_str/$mlock_str/$defrag_str/$LLAMA_EXTRA_ARGS are intentionally word-split
  "$LLAMA_SERVER_BIN" \
    --model "$MODEL_PATH" \
    --ctx-size "$LLAMA_CTX_SIZE" \
    --parallel 1 \
    --cache-type-k "$LLAMA_CACHE_TYPE_K" \
    --cache-type-v "$LLAMA_CACHE_TYPE_V" \
    $fa_str \
    $reasoning_str \
    $batch_str \
    $ubatch_str \
    $defrag_str \
    $mlock_str \
    --no-mmproj \
    --port "$llama_port" \
    --n-gpu-layers "$LLAMA_N_GPU_LAYERS" \
    $fit_str \
    --threads "$LLAMA_THREADS" \
    $LLAMA_EXTRA_ARGS &
  llama_pid=$!

  echo "run.sh: waiting for llama-server to become ready..." >&2
  ready=false
  for _ in $(seq 1 60); do
    if curl -fsS "$LLAMA_HOST/health" >/dev/null 2>&1; then
      echo "run.sh: llama-server is up." >&2
      ready=true
      break
    fi
    if ! kill -0 "$llama_pid" 2>/dev/null; then
      echo "run.sh: llama-server exited before becoming ready — check the model path and build." >&2
      exit 1
    fi
    sleep 1
  done
  if [[ "$ready" == false ]]; then
    echo "run.sh: llama-server did not become ready within 60s — check its output above." >&2
    exit 1
  fi
fi

echo "run.sh: starting hearthmind.server..." >&2
cd "$REPO_ROOT"
if [[ "$llm_disabled" == false ]]; then
  python -m hearthmind.server --llm-backend llamacpp --llm-llamacpp-host "$LLAMA_HOST" "$@" &
else
  python -m hearthmind.server "$@" &
fi
hearthmind_pid=$!
wait "$hearthmind_pid"
hearthmind_status=$?
hearthmind_pid=""  # already exited — nothing left for cleanup() to do on this one
exit "$hearthmind_status"
