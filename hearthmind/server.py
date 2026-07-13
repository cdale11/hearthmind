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
import random
import signal

from hearthmind.config import Config
from hearthmind.llm import world_genesis
from hearthmind.llm.client import OllamaClient
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
    parser.add_argument("--width", type=int, default=64, help="Used only when creating a new world.")
    parser.add_argument("--height", type=int, default=64, help="Used only when creating a new world.")
    parser.add_argument("--tick-seconds", type=float, default=1.0, help="Real seconds between ticks.")
    parser.add_argument("--sim-minutes-per-tick", type=int, default=15, help="Sim-minutes advanced per tick.")
    parser.add_argument("--snapshot-every", type=int, default=60, help="Ticks between snapshots.")
    parser.add_argument("--initial-population", type=int, default=12,
                         help="Used only when creating a new world.")
    parser.add_argument("--llm-disabled", action="store_true",
                         help="Disable the Ollama cognition/dialogue/culture layer (on by default as of "
                              "E2; every LLM call still falls back to deterministic behavior if Ollama "
                              "isn't reachable, so this is only needed for a fully offline run).")
    parser.add_argument("--llm-host", default="http://localhost:11434", help="Ollama server URL.")
    parser.add_argument("--llm-model", default=Config.llm_model, help="Ollama model name (must be pulled already).")
    parser.add_argument("--llm-timeout", type=float, default=Config.llm_timeout_seconds,
                         help="Seconds before an LLM call falls back.")
    parser.add_argument("--llm-max-concurrent", type=int, default=4,
                         help="Max simultaneous in-flight LLM requests.")
    parser.add_argument("--api-disabled", action="store_true",
                         help="Disable the browser interface (on by default; requires 'fastapi'/'uvicorn' — "
                              "run without them installed and this is disabled automatically with a warning).")
    parser.add_argument("--api-host", default="0.0.0.0", help="Browser API bind host.")
    parser.add_argument("--api-port", type=int, default=8765, help="Browser API port.")
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
        initial_population=args.initial_population,
        db_path=args.db,
        llm_enabled=not args.llm_disabled,
        llm_host=args.llm_host,
        llm_model=args.llm_model,
        llm_timeout_seconds=args.llm_timeout,
        llm_max_concurrent=args.llm_max_concurrent,
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
            client = OllamaClient(
                host=config.llm_host, model=config.llm_model, timeout_seconds=config.llm_timeout_seconds,
                num_ctx=config.llm_num_ctx, num_predict=config.llm_num_predict,
                keep_alive=config.llm_keep_alive, use_mmap=config.llm_use_mmap, num_gpu=config.llm_num_gpu,
            )
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
