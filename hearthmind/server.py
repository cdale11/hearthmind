"""Entrypoint: `python3 -m hearthmind.server [--db world.sqlite3] [...]`

Runs the simulation forever until interrupted (Ctrl+C / SIGTERM), at which
point it saves a final snapshot and exits cleanly. Running this again with
the same --db resumes the same world at the same tick.
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import random
import signal

from hearthmind.config import Config
from hearthmind.llm import world_genesis
from hearthmind.llm.client import build_llm_client
from hearthmind.persistence.database import is_fresh, open_db, write_world_meta
from hearthmind.simulation.engine import SimulationEngine

logger = logging.getLogger("hearthmind.server")

_CREATION_ONLY_FIELDS = ("seed", "width", "height", "sim_minutes_per_tick", "initial_population")


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Run a Hearthmind world.")
    parser.add_argument("--db", default="world.sqlite3", help="Path to the SQLite world database.")
    parser.add_argument(
        "--seed", type=int, default=None,
        help="World seed, used only when creating a new world. Omit it and a brand-new world runs a "
             "one-time 'genesis' LLM call to pick an evocative founding scenario whose text becomes the "
             "seed (falls back to a wall-clock-derived seed if the LLM is disabled/unreachable).",
    )
    # Every default below references the Config class attribute directly —
    # a hardcoded copy here silently drifts when Config's tuned value
    # changes (audit finding: --llm-max-concurrent sat at a hardcoded 4
    # for several releases after Config was deliberately tuned down to 2
    # for 8GB-memory headroom, so every plain `hearthmind-server` launch
    # ran twice the intended Ollama concurrency).
    parser.add_argument("--width", type=int, default=Config.width, help="Used only when creating a new world.")
    parser.add_argument("--height", type=int, default=Config.height, help="Used only when creating a new world.")
    parser.add_argument("--tick-seconds", type=float, default=Config.tick_seconds, help="Real seconds between ticks.")
    parser.add_argument("--sim-minutes-per-tick", type=int, default=Config.sim_minutes_per_tick,
                         help="Sim-minutes advanced per tick.")
    parser.add_argument("--snapshot-every", type=int, default=Config.snapshot_every_ticks,
                         help="Ticks between snapshots.")
    parser.add_argument("--initial-population", type=int, default=Config.initial_population,
                         help="Used only when creating a new world.")
    parser.add_argument("--llm-disabled", action="store_true",
                         help="Disable the Ollama cognition/dialogue/culture layer (on by default as of "
                              "E2; every LLM call still falls back to deterministic behavior if Ollama "
                              "isn't reachable, so this is only needed for a fully offline run).")
    parser.add_argument("--llm-backend", choices=["llamacpp", "ollama"], default=Config.llm_backend,
                         help="Which local LLM server to talk to (v0.72.0). 'llamacpp' (default) talks to a "
                              "llama-server process (see README, 'Running the LLM (llama.cpp)'); 'ollama' keeps "
                              "the original Ollama HTTP client for anyone with an existing Ollama setup.")
    parser.add_argument("--llm-host", default=Config.llm_host, help="Ollama server URL (only used with --llm-backend=ollama).")
    parser.add_argument("--llm-llamacpp-host", default=Config.llm_llamacpp_host,
                         help="llama-server URL (only used with --llm-backend=llamacpp, the default).")
    parser.add_argument("--llm-model", default=Config.llm_model,
                         help="Model name/tag. For --llm-backend=ollama this must already be `ollama pull`ed; "
                              "for llamacpp it's informational only (llama-server loads one GGUF file at "
                              "startup via --model, see README) but still sent in the request body.")
    parser.add_argument("--llm-timeout", type=float, default=Config.llm_timeout_seconds,
                         help="Seconds before an LLM call falls back.")
    parser.add_argument("--llm-num-ctx", type=int, default=Config.llm_num_ctx,
                         help="Context-window cap (KV-cache size, see Config.llm_num_ctx's docstring for the "
                              "GPU-offload-vs-CPU-only rationale). Sent per-request for the Ollama backend; for "
                              "llama.cpp this is documentation only — the real cap is llama-server's own "
                              "--ctx-size launch flag (see README/scripts/run.sh), which must be raised/lowered "
                              "in step with this value.")
    parser.add_argument("--llm-num-predict", type=int, default=Config.llm_num_predict,
                         help="Cap on generated tokens per call, counted against --llm-num-ctx's budget.")
    parser.add_argument("--llm-temperature", type=float, default=Config.llm_temperature,
                         help="Sampling temperature for every LLM call (both backends). Lower "
                              "(0.5-0.6) curbs the rambling/garbled/off-topic output small models "
                              "produce under the JSON constraint; higher (0.9) adds variety on a "
                              "stronger model.")
    parser.add_argument("--llm-max-concurrent", type=int, default=Config.llm_max_concurrent,
                         help="Max simultaneous in-flight LLM requests.")
    parser.add_argument("--llm-num-thread", type=int, default=os.cpu_count() or 4,
                         help="CPU threads Ollama devotes to a single inference call. Defaults to every "
                              "core on this machine — finishes each call faster without adding memory, "
                              "unlike raising --llm-max-concurrent (Config.llm_num_thread's own default "
                              "is None, i.e. defer to Ollama; this CLI entry point picks a smarter "
                              "runtime default since os.cpu_count() can't be a dataclass default). Pass "
                              "0 to leave Ollama's own heuristic in charge instead.")
    parser.add_argument("--event-log-retention", type=int, default=Config.event_log_retention,
                         help="Most-recent rows kept in the events table (older pruned on the snapshot "
                              "cadence). The events table is the one unbounded-growth table on a perpetual "
                              "run. 0 disables event pruning (unbounded).")
    parser.add_argument("--metrics-log-retention", type=int, default=Config.metrics_log_retention,
                         help="Most-recent rows kept in the metrics table (older pruned on the snapshot "
                              "cadence, same shape as --event-log-retention). 0 disables metrics pruning "
                              "(unbounded).")
    parser.add_argument("--llm-core-cast-size", type=int, default=Config.llm_core_cast_size,
                         help="How many NPCs are the LLM-driven 'core cast' — only these get LLM cognition, "
                              "and only a pair of them gets LLM dialogue; everyone else uses the deterministic "
                              "fallback. Decouples Ollama call volume from population (the swap fix). 0 disables "
                              "LLM cognition/dialogue entirely.")
    parser.add_argument("--llm-max-calls-per-day", type=int, default=Config.llm_max_calls_per_day,
                         help="Hard ceiling on total Ollama calls per sim-day (belt-and-braces above the core "
                              "cast); once hit, LLM decisions fall back deterministically until the next day.")
    parser.add_argument("--api-disabled", action="store_true",
                         help="Disable the browser interface (on by default; requires 'fastapi'/'uvicorn' — "
                              "run without them installed and this is disabled automatically with a warning).")
    parser.add_argument("--api-host", default=Config.api_host, help="Browser API bind host.")
    parser.add_argument("--api-port", type=int, default=Config.api_port, help="Browser API port.")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug-level logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    return Config(
        seed=args.seed,
        width=args.width,
        height=args.height,
        tick_seconds=args.tick_seconds,
        sim_minutes_per_tick=args.sim_minutes_per_tick,
        snapshot_every_ticks=args.snapshot_every,
        event_log_retention=args.event_log_retention,
        metrics_log_retention=args.metrics_log_retention,
        initial_population=args.initial_population,
        db_path=args.db,
        llm_enabled=not args.llm_disabled,
        llm_backend=args.llm_backend,
        llm_host=args.llm_host,
        llm_llamacpp_host=args.llm_llamacpp_host,
        llm_model=args.llm_model,
        llm_timeout_seconds=args.llm_timeout,
        llm_num_ctx=args.llm_num_ctx,
        llm_num_predict=args.llm_num_predict,
        llm_temperature=args.llm_temperature,
        llm_max_concurrent=args.llm_max_concurrent,
        llm_num_thread=args.llm_num_thread or None,
        llm_core_cast_size=args.llm_core_cast_size,
        llm_max_calls_per_day=args.llm_max_calls_per_day,
        api_enabled=not args.api_disabled,
        api_host=args.api_host,
        api_port=args.api_port,
    )


async def _resolve_genesis_seed(config: Config) -> tuple[int, str]:
    """Turn "no --seed given" into a concrete seed for a brand-new world:
    an LLM-authored founding scenario, hashed into a seed (see
    hearthmind.llm.world_genesis), or a wall-clock-derived fallback if
    the LLM is disabled/unreachable. Blocking-but-once: this only ever
    runs a single time, before the tick loop starts, so a multi-second
    LLM call here is an acceptable one-time startup cost, not a
    liveness risk like a per-tick call would be."""
    fallback_hint = random.SystemRandom().randrange(1, 2**31 - 1)
    if config.llm_enabled:
        try:
            client = build_llm_client(config)
            result = await asyncio.wait_for(
                asyncio.to_thread(client.generate_json, world_genesis.build_prompt(), world_genesis.SYSTEM_PROMPT),
                timeout=config.llm_timeout_seconds + 5.0,
            )
            scenario = world_genesis.parse_scenario(result, world_genesis.fallback_scenario(fallback_hint))
            return world_genesis.seed_from_scenario(scenario), scenario
        except Exception as exc:  # LLM failure must never block world creation
            logger.warning("World-genesis LLM call failed, using a deterministic fallback scenario: %s", exc)
    scenario = world_genesis.fallback_scenario(fallback_hint)["scenario"]
    return world_genesis.seed_from_scenario(scenario) ^ fallback_hint, scenario


async def _main_async(config: Config) -> None:
    with open_db(config.db_path) as conn:
        fresh = is_fresh(conn)

        seed_explicitly_requested = config.seed is not None
        founding_scenario = ""
        if config.seed is None:
            if fresh:
                seed, founding_scenario = await _resolve_genesis_seed(config)
            else:
                seed = 1337  # irrelevant on resume — the loaded snapshot's own seed is authoritative
            config = dataclasses.replace(config, seed=seed)

        broadcaster = None
        uvicorn_module = create_app = None
        if config.api_enabled:
            # Deferred import: only requires fastapi/uvicorn when the API
            # is actually enabled (on by default — see Config.api_enabled).
            # Checked upfront (before the engine is built, which needs to
            # know whether it has a broadcaster) and downgraded to a
            # warning rather than crashing on ImportError: the simulation
            # itself never depends on the browser interface, so a base
            # install (no `pip install -r requirements.txt`) should still
            # run. See docs/DECISIONS.md, UI-default pass.
            try:
                import uvicorn as uvicorn_module
                from hearthmind.interface.api import WorldBroadcaster
                from hearthmind.interface.app import create_app
                broadcaster = WorldBroadcaster()
            except ImportError:
                broadcaster = None
                logger.warning(
                    "Browser interface is enabled but 'fastapi'/'uvicorn' aren't installed — "
                    "running without it. Install with: pip install -r requirements.txt"
                )

        engine = SimulationEngine.load_or_create(
            conn, config, broadcaster=broadcaster, founding_scenario=founding_scenario,
        )
        if fresh:
            write_world_meta(conn, seed=engine.world.config.seed,
                              width=engine.world.config.width, height=engine.world.config.height)
            if founding_scenario:
                engine.log_founding_scenario(founding_scenario)
        else:
            for field_name in _CREATION_ONLY_FIELDS:
                if field_name == "seed" and not seed_explicitly_requested:
                    continue  # no --seed given — nothing to warn about a genesis seed being ignored
                requested = getattr(config, field_name)
                actual = getattr(engine.world.config, field_name)
                if requested != actual:
                    logger.warning(
                        "--%s=%s was requested but this world was created with %s=%s; "
                        "the flag is ignored on resume (creation-only field).",
                        field_name.replace("_", "-"), requested, field_name, actual,
                    )

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, engine.request_stop)
            except NotImplementedError:
                pass  # signal handlers aren't available on some platforms (e.g. Windows)

        if broadcaster is not None:
            app = create_app(broadcaster, conn, config)
            uvicorn_config = uvicorn_module.Config(app, host=config.api_host, port=config.api_port, log_level="warning")
            uvicorn_server = uvicorn_module.Server(uvicorn_config)

            async def _stop_uvicorn_on_signal() -> None:
                await engine.stop_event.wait()
                uvicorn_server.should_exit = True

            await asyncio.gather(
                engine.run_forever(),
                uvicorn_server.serve(),
                _stop_uvicorn_on_signal(),
            )
        else:
            await engine.run_forever()


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    asyncio.run(_main_async(config))


if __name__ == "__main__":
    main()
