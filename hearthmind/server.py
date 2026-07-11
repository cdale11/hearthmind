"""Entrypoint: `python3 -m hearthmind.server [--db world.sqlite3] [...]`

Runs the simulation forever until interrupted (Ctrl+C / SIGTERM), at which
point it saves a final snapshot and exits cleanly. Running this again with
the same --db resumes the same world at the same tick.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import signal

from hearthmind.config import Config
from hearthmind.persistence.database import is_fresh, open_db, write_world_meta
from hearthmind.simulation.engine import SimulationEngine

logger = logging.getLogger("hearthmind.server")

_CREATION_ONLY_FIELDS = ("seed", "width", "height", "sim_minutes_per_tick")


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(description="Run a Hearthmind world.")
    parser.add_argument("--db", default="world.sqlite3", help="Path to the SQLite world database.")
    parser.add_argument("--seed", type=int, default=1337, help="Used only when creating a new world.")
    parser.add_argument("--width", type=int, default=64, help="Used only when creating a new world.")
    parser.add_argument("--height", type=int, default=64, help="Used only when creating a new world.")
    parser.add_argument("--tick-seconds", type=float, default=1.0, help="Real seconds between ticks.")
    parser.add_argument("--sim-minutes-per-tick", type=int, default=15, help="Sim-minutes advanced per tick.")
    parser.add_argument("--snapshot-every", type=int, default=60, help="Ticks between snapshots.")
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
        db_path=args.db,
    )


async def _main_async(config: Config) -> None:
    with open_db(config.db_path) as conn:
        fresh = is_fresh(conn)
        engine = SimulationEngine.load_or_create(conn, config)
        if fresh:
            write_world_meta(conn, seed=engine.world.config.seed,
                              width=engine.world.config.width, height=engine.world.config.height)
        else:
            for field_name in _CREATION_ONLY_FIELDS:
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

        await engine.run_forever()


def main(argv: list[str] | None = None) -> None:
    config = parse_args(argv)
    asyncio.run(_main_async(config))


if __name__ == "__main__":
    main()
