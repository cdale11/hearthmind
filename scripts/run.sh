#!/usr/bin/env bash
# Launches llama-server (tuned per README's "Running the LLM (llama.cpp)"
# section) and hearthmind.server together as one command, so "start the
# game" is one script instead of two manually-coordinated terminals.
#
# Usage:
#   MODEL_PATH=/path/to/Qwen3-4B-Instruct-Q4_K_M.gguf ./scripts/run.sh
#   MODEL_PATH=... ./scripts/run.sh --db world.sqlite3 --llm-core-cast-size 8
#
# Every argument after the script name is passed straight through to
# `python3 -m hearthmind.server` (e.g. --db, --seed, --llm-disabled).
# Ctrl+C (or a plain `kill`) stops both processes cleanly — hearthmind
# gets its normal SIGINT/SIGTERM shutdown (final snapshot, see
# server.py) before llama-server is stopped.
#
# Configurable via environment variables (all optional, defaults match
# the README's tuned-for-8GB recipe):
#   MODEL_PATH        Path to a GGUF model file. Required unless
#                      --llm-disabled is passed through in "$@".
#   LLAMA_SERVER_BIN   Path to the llama-server binary.
#                      Default: llama.cpp/build/bin/llama-server
#   LLAMA_HOST         Host:port llama-server binds to (also passed to
#                      hearthmind via --llm-llamacpp-host).
#                      Default: http://localhost:8080
#   LLAMA_CTX_SIZE     Default: 1280 (matches Config.llm_num_ctx)
#   LLAMA_THREADS      Default: every CPU core ($(nproc))
#   LLAMA_N_GPU_LAYERS Default: 0 (CPU only). Set to 999 to offload every
#                      layer Vulkan/ROCm can fit (see README's AMD iGPU
#                      section) once you've confirmed a GPU-enabled
#                      llama-server build.
#   LLAMA_EXTRA_ARGS   Extra raw flags appended to the llama-server
#                      command line (e.g. "--cache-type-k q8_0
#                      --cache-type-v q8_0 --flash-attn" once your build
#                      supports them).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LLAMA_SERVER_BIN="${LLAMA_SERVER_BIN:-$REPO_ROOT/llama.cpp/build/bin/llama-server}"
LLAMA_HOST="${LLAMA_HOST:-http://localhost:8080}"
LLAMA_CTX_SIZE="${LLAMA_CTX_SIZE:-1280}"
LLAMA_THREADS="${LLAMA_THREADS:-$(nproc 2>/dev/null || echo 4)}"
LLAMA_N_GPU_LAYERS="${LLAMA_N_GPU_LAYERS:-0}"
LLAMA_EXTRA_ARGS="${LLAMA_EXTRA_ARGS:-}"

llm_disabled=false
for arg in "$@"; do
  if [[ "$arg" == "--llm-disabled" ]]; then
    llm_disabled=true
  fi
done

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
  if [[ ! -x "$LLAMA_SERVER_BIN" ]]; then
    echo "run.sh: llama-server binary not found or not executable at:" >&2
    echo "        $LLAMA_SERVER_BIN" >&2
    echo "        Build it (see README, 'Running the LLM (llama.cpp)') or set LLAMA_SERVER_BIN." >&2
    exit 1
  fi

  llama_port="${LLAMA_HOST##*:}"
  echo "run.sh: starting llama-server on $LLAMA_HOST (ctx=$LLAMA_CTX_SIZE, threads=$LLAMA_THREADS, gpu-layers=$LLAMA_N_GPU_LAYERS)..." >&2
  # shellcheck disable=SC2086
  "$LLAMA_SERVER_BIN" \
    --model "$MODEL_PATH" \
    --ctx-size "$LLAMA_CTX_SIZE" \
    --parallel 1 \
    --threads "$LLAMA_THREADS" \
    --n-gpu-layers "$LLAMA_N_GPU_LAYERS" \
    --no-mmproj \
    --port "$llama_port" \
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
