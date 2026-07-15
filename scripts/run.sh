#!/usr/bin/env bash
# Builds what needs building, then launches llama-server (tuned per
# README's "Running the LLM (llama.cpp)" section) and hearthmind.server
# together as one command — "start the game" is one script instead of
# three manually-coordinated steps (build native extension, build/run
# llama-server, run hearthmind).
#
# Usage:
#   MODEL_PATH=/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf ./scripts/run.sh
#   MODEL_PATH=... ./scripts/run.sh --db world.sqlite3 --llm-core-cast-size 16
#
# Every argument after the script name is passed straight through to
# `python3 -m hearthmind.server` (e.g. --db, --seed, --llm-disabled).
# Ctrl+C (or a plain `kill`) stops both processes cleanly — hearthmind
# gets its normal SIGINT/SIGTERM shutdown (final snapshot, see
# server.py) before llama-server is stopped.
#
# Build steps (both skippable, both safe no-ops if already built):
#   - hearthmind._native (the pybind11 C++ extension, cpp/src/): always
#     attempted via `python3 setup.py build_ext --inplace` unless
#     SKIP_NATIVE_BUILD=1. Failure here is non-fatal — every native
#     function has a pure-Python fallback (see README).
#   - llama-server itself: if LLAMA_SERVER_BIN doesn't exist and a
#     llama.cpp source checkout is found at LLAMA_CPP_DIR, it's built
#     automatically (CMake + GGML_VULKAN if USE_VULKAN=1). If no
#     checkout is found, this script prints the clone command and stops
#     rather than silently fetching code from the network — set
#     AUTO_CLONE_LLAMA_CPP=1 to let it run that clone for you instead.
#
# Configurable via environment variables (all optional; the llama-server
# flag defaults below match the confirmed-working GPU-offload recipe —
# see README, "Running the LLM (llama.cpp)"):
#   MODEL_PATH          Path to a GGUF model file. Required unless
#                        --llm-disabled is passed through in "$@".
#   LLAMA_SERVER_BIN     Path to the llama-server binary.
#                        Default: llama.cpp/build/bin/llama-server
#   LLAMA_CPP_DIR        Where to find/build a llama.cpp checkout.
#                        Default: <repo>/llama.cpp
#   LLAMA_HOST           Host:port llama-server binds to (also passed to
#                        hearthmind via --llm-llamacpp-host).
#                        Default: http://localhost:8080
#   LLAMA_CTX_SIZE       Default: 1280 (matches Config.llm_num_ctx)
#   LLAMA_THREADS        Default: every CPU core ($(nproc))
#   LLAMA_N_GPU_LAYERS   Default: 999 (offload every layer the backend
#                        can fit — confirmed working via GPU inference;
#                        set 0 to force CPU-only).
#   LLAMA_CACHE_TYPE_K   Default: q8_0
#   LLAMA_CACHE_TYPE_V   Default: q8_0
#   USE_VULKAN           1 to build llama.cpp with -DGGML_VULKAN=ON
#                        (AMD iGPU offload, see README). Default: 0.
#   AUTO_CLONE_LLAMA_CPP 1 to let this script `git clone` llama.cpp when
#                        no checkout is found. Default: 0.
#   LLAMA_EXTRA_ARGS     Extra raw flags appended to the llama-server
#                        command line.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LLAMA_CPP_DIR="${LLAMA_CPP_DIR:-$REPO_ROOT/llama.cpp}"
LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$LLAMA_CPP_DIR/build/bin/llama-server}"
LLAMA_HOST="${LLAMA_HOST:-http://localhost:8080}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-1280}"
LLAMA_THREADS="${LLAMA_THREADS:-$(nproc 2>/dev/null || echo 4)}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-999}"
LLAMA_CACHE_TYPE_K="${LLAMA_CACHE_TYPE_K:-q8_0}"
LLAMA_CACHE_TYPE_V="${LLAMA_CACHE_TYPE_V:-q8_0}"
USE_VULKAN="${USE_VULKAN:-0}"
AUTO_CLONE_LLAMA_CPP="${AUTO_CLONE_LLAMA_CPP:-0}"
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
  ( cd "$REPO_ROOT" && python3 setup.py build_ext --inplace ) || \
    echo "run.sh: native extension build failed — continuing on the pure-Python fallback path (see README)." >&2
fi

# --- build llama-server if missing ------------------------------------------

if [[ "$llm_disabled" == false && ! -x "$LLAMA_SERVER_BIN" ]]; then
  if [[ ! -d "$LLAMA_CPP_DIR/.git" && ! -d "$LLAMA_CPP_DIR" ]]; then
    if [[ "$AUTO_CLONE_LLAMA_CPP" == "1" ]]; then
      echo "run.sh: cloning llama.cpp into $LLAMA_CPP_DIR..." >&2
      git clone --depth 1 https://github.com/ggml-org/llama.cpp "$LLAMA_CPP_DIR"
    else
      echo "run.sh: no llama-server binary at $LLAMA_SERVER_BIN and no checkout at $LLAMA_CPP_DIR." >&2
      echo "        Clone it yourself:" >&2
      echo "          git clone https://github.com/ggml-org/llama.cpp \"$LLAMA_CPP_DIR\"" >&2
      echo "        ...or re-run with AUTO_CLONE_LLAMA_CPP=1 to let this script do it." >&2
      exit 1
    fi
  fi
  echo "run.sh: building llama-server (USE_VULKAN=$USE_VULKAN)..." >&2
  cmake_flags=(-B "$LLAMA_CPP_DIR/build" -S "$LLAMA_CPP_DIR")
  if [[ "$USE_VULKAN" == "1" ]]; then
    cmake_flags+=(-DGGML_VULKAN=ON)
  fi
  cmake "${cmake_flags[@]}"
  cmake --build "$LLAMA_CPP_DIR/build" --config Release -j"$(nproc 2>/dev/null || echo 4)" --target llama-server
  if [[ ! -x "$LLAMA_SERVER_BIN" ]]; then
    echo "run.sh: build finished but $LLAMA_SERVER_BIN still isn't there — check the cmake/build output above." >&2
    exit 1
  fi
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
  echo "run.sh: starting llama-server on $LLAMA_HOST (ctx=$LLAMA_CTX_SIZE, threads=$LLAMA_THREADS, gpu-layers=$LLAMA_N_GPU_LAYERS, kv=$LLAMA_CACHE_TYPE_K/$LLAMA_CACHE_TYPE_V)..." >&2
  # shellcheck disable=SC2086
  "$LLAMA_SERVER_BIN" \
    --model "$MODEL_PATH" \
    --ctx-size "$LLAMA_CTX_SIZE" \
    --parallel 1 \
    --cache-type-k "$LLAMA_CACHE_TYPE_K" \
    --cache-type-v "$LLAMA_CACHE_TYPE_V" \
    --no-mmproj \
    --port "$llama_port" \
    --n-gpu-layers "$LLAMA_N_GPU_LAYERS" \
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
  python3 -m hearthmind.server --llm-backend llamacpp --llm-llamacpp-host "$LLAMA_HOST" "$@" &
else
  python3 -m hearthmind.server "$@" &
fi
hearthmind_pid=$!
wait "$hearthmind_pid"
hearthmind_status=$?
hearthmind_pid=""  # already exited — nothing left for cleanup() to do on this one
exit "$hearthmind_status"
