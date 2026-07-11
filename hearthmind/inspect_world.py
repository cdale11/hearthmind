"""`python3 -m hearthmind.inspect_world --db world.sqlite3`

Prints a summary of the latest saved snapshot plus recent events. Safe to
run while the server is running (SQLite WAL mode allows concurrent reads);
note it only ever shows state as of the last snapshot, not the live in-memory
tick, since the browser interface (which will read live state via the
engine) doesn't exist yet.
"""
from __future__ import annotations

import argparse
import datetime
import json

from hearthmind.config import Config
from hearthmind.persistence.database import open_db
from hearthmind.persistence.snapshot import load_latest_snapshot, recent_events


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect a Hearthmind world's saved state.")
    parser.add_argument("--db", default="world.sqlite3", help="Path to the SQLite world database.")
    parser.add_argument("--events", type=int, default=10, help="Number of recent events to show.")
    parser.add_argument("--json", action="store_true", help="Print raw JSON summary instead of text.")
    args = parser.parse_args(argv)

    with open_db(args.db) as conn:
        world = load_latest_snapshot(conn, runtime_config=Config(db_path=args.db))
        if world is None:
            print(f"No snapshot found in {args.db} — has the server been run yet?")
            return

        summary = world.summary()
        events = recent_events(conn, limit=args.events)

    if args.json:
        print(json.dumps({"summary": summary, "recent_events": events}, indent=2))
        return

    print(f"=== Hearthmind world: {args.db} ===")
    print(f"Tick:        {summary['tick']}")
    print(f"Date:        {summary['date']}  ({summary['clock']})")
    print(f"Weather:     {summary['weather']}")
    print(f"World size:  {summary['world_size']}")
    print("Biome counts:")
    for biome, count in sorted(summary["biome_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {biome:15s} {count}")

    pop = summary["population"]
    print(
        f"\nPopulation:  {pop['total']} inhabitants "
        f"({pop['awake']} awake, {pop['resting']} resting)  "
        f"avg hunger {pop['avg_hunger']:.2f}, avg energy {pop['avg_energy']:.2f}, "
        f"avg age {pop['avg_age_ticks']:.0f} ticks"
    )

    res = summary["resources"]
    print(
        f"Resources:   {res['total_nodes']} foraging grounds "
        f"({res['depleted']} depleted)  avg fullness {res['avg_amount']:.2f}"
    )

    print(f"\nRecent events (latest {len(events)}):")
    for event in events:
        when = datetime.datetime.fromtimestamp(event["logged_at"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [tick {event['tick']:>6}] {when}  {event['category']:12s} {event['description']}")


if __name__ == "__main__":
    main()
