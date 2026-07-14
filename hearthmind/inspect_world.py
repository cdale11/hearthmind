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

from hearthmind.agents.agent import MATURITY_TICKS
from hearthmind.config import Config
from hearthmind.persistence.database import open_db
from hearthmind.persistence.snapshot import load_latest_snapshot, recent_events


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Inspect a Hearthmind world's saved state.")
    parser.add_argument("--db", default="world.sqlite3", help="Path to the SQLite world database.")
    parser.add_argument("--events", type=int, default=10, help="Number of recent events to show.")
    parser.add_argument("--agents", action="store_true",
                         help="List each inhabitant individually (name, needs, goal).")
    parser.add_argument("--json", action="store_true", help="Print raw JSON summary instead of text.")
    args = parser.parse_args(argv)

    with open_db(args.db) as conn:
        world = load_latest_snapshot(conn, runtime_config=Config(db_path=args.db))
        if world is None:
            print(f"No snapshot found in {args.db} — has the server been run yet?")
            return

        summary = world.summary()
        events = recent_events(conn, limit=args.events)
        agents = [a.to_dict() for a in world.population.agents] if args.agents else None

    if args.json:
        payload = {"summary": summary, "recent_events": events}
        if agents is not None:
            payload["agents"] = agents
        print(json.dumps(payload, indent=2))
        return

    settlement_name = summary["settlement"]["name"]
    header = f"=== Hearthmind world: {args.db} ===" if not settlement_name else f"=== {settlement_name} ({args.db}) ==="
    print(header)
    print(f"Tick:        {summary['tick']}")
    print(f"Date:        {summary['date']}  ({summary['clock']})")
    print(f"Weather:     {summary['weather']}")
    print(f"World size:  {summary['world_size']}")
    print("Biome counts:")
    for biome, count in sorted(summary["biome_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {biome:15s} {count}")
    if "climate" in summary:
        c = summary["climate"]
        print(f"Climate:     warming {c['warming']:+.2f}, drying {c['drying']:+.2f} (slow monthly drift, -1..1 each)")
    if "night_factor" in summary:
        print(f"Daylight:    night_factor {summary['night_factor']:.2f} (0=full day, 1=full night)")
    if summary.get("lakes"):
        lake_bits = ", ".join(f"#{lk['id']} {lk['tiles']} tiles, level {lk['level']:+.2f}" for lk in summary["lakes"])
        print(f"Lakes:       {lake_bits}")
    if "disasters" in summary:
        d = summary["disasters"]
        print(
            f"Disasters:   flood pressure {d['flood_pressure']:.2f}, "
            f"{d['active_flood_tiles']} flooded tile(s), {d['active_wildfire_tiles']} wildfire tile(s)"
        )

    pop = summary["population"]
    print(
        f"\nPopulation:  {pop['total']} inhabitants "
        f"({pop['awake']} awake, {pop['resting']} resting)  "
        f"avg hunger {pop['avg_hunger']:.2f}, avg energy {pop['avg_energy']:.2f}, "
        f"avg age {pop['avg_age_ticks']:.0f} ticks"
    )
    print(
        f"             cumulative deaths: {pop['deaths_starvation']} starvation, "
        f"{pop['deaths_old_age']} old age, {pop.get('deaths_predator', 0)} predator"
    )
    print(
        f"             relationships: {pop.get('close_bonds', 0)} close bonds, "
        f"{pop.get('rivalries', 0)} rivalries (avg affinity {pop.get('avg_affinity', 0.0):.2f})"
    )

    llm = summary["llm"]
    print(
        f"LLM:         {llm['calls_total']} calls, {llm['fallback_total']} fell back to "
        f"deterministic ({llm['fallback_rate']:.0%})"
    )

    res = summary["resources"]
    print(
        f"Resources:   {res.get('food_nodes', res['total_nodes'])} bushes, "
        f"{res.get('ore_nodes', 0)} mines ({res['depleted']} depleted total)  "
        f"avg fullness {res['avg_amount']:.2f} (mines {res.get('ore_avg_amount', 0.0):.2f})"
    )

    settle = summary["settlement"]
    print(
        f"Settlement:  {settle['total']} structures "
        f"({settle['under_construction']} under construction, {settle['standing']} standing, "
        f"{settle['ruined']} ruined)  avg condition {settle['avg_condition']:.2f}"
    )
    print(
        f"             {settle['granaries']} granaries, {settle['granary_food']:.1f} food stored, "
        f"{settle['materials']:.1f} materials, {settle['currency']:.1f} currency"
    )
    print(
        f"             tech level {settle.get('tech_level', 0)}, "
        f"education {settle.get('education_level', 0.0):.2f}/{settle.get('education_capacity', 1.0):.2f}"
    )
    print(
        f"             civic buildings: {settle.get('workshops', 0)} workshops, "
        f"{settle.get('schools', 0)} schools, {settle.get('hospitals', 0)} hospitals, "
        f"{settle.get('universities', 0)} universities, {settle.get('factories', 0)} factories"
    )
    print(f"             era: {settle.get('era', 'industrial')} — {settle.get('era_description', '')}")
    if settle.get("founding_scenario"):
        print(f"             founding scenario: \"{settle['founding_scenario']}\"")
    if settle.get("current_priority"):
        print(f"             town brain priority: {settle['current_priority']} — {settle.get('priority_rationale', '')}")
    print(f"             temperament: {settle.get('temperament', 0.0):+.3f} (internal only — deliberately never surfaced to players as 'supernatural')")
    if settle.get("beliefs"):
        print("             the village's own theories about itself:")
        for b in sorted(settle["beliefs"], key=lambda b: -b["confidence"]):
            print(f"               - {b['subject']}: {b['belief']} (confidence {b['confidence']:.2f})")
    if settle["traditions"]:
        print(f"             traditions: {'; '.join(settle['traditions'])}")
    if settle.get("inventions"):
        print(f"             inventions: {'; '.join(settle['inventions'])}")
    if settle.get("festivals"):
        print(f"             festivals: {'; '.join(settle['festivals'])}")
    if settle.get("vehicles"):
        v = settle["vehicles"]
        print(
            f"             vehicles: {v['carts_ready']}/{v['carts_total']} carts ready "
            f"({v['carts_broken']} broken), {v['mounts_ready']}/{v['mounts_total']} mounts ready "
            f"({v['mounts_claimed']} claimed, {v['mounts_broken']} broken)"
        )

    farms = summary["farms"]
    print(f"Farms:       {farms['total']} fields ({farms['growing']} growing, {farms['ready']} ready to harvest)")

    if "wildlife" in summary:
        w = summary["wildlife"]
        print(
            f"Wildlife:    {w['grazer_total']} grazers ({w['grazer_herds']} herds), "
            f"{w['predator_total']} predators ({w['predator_packs']} packs)"
        )
    if "roads" in summary:
        rd = summary["roads"]
        condition = f", currently {rd['condition']} ({rd['speed_multiplier']}x)" if "condition" in rd else ""
        print(f"Roads:       {rd['established_roads']} established ({rd['worn_tiles']} worn tiles){condition}")

    infra = [row for s in world.settlements for row in s.infrastructure_report()]
    infra.sort(key=lambda r: r["condition"])
    needing_attention = [r for r in infra if r["status"] not in ("excellent", "good")]
    if needing_attention:
        print(f"\nInfrastructure needing attention ({len(needing_attention)} of {len(infra)}):")
        for r in needing_attention[:8]:
            print(f"  {r['kind']:12s} ({r['x']:>3},{r['y']:>3})  {r['status']:20s} {round(r['condition'] * 100)}%")

    if agents is not None:
        print(f"\nInhabitants ({len(agents)}):")
        for agent in sorted(agents, key=lambda a: a["name"]):
            maturity = (
                "mature" if agent["age_ticks"] >= MATURITY_TICKS
                else f"matures in {MATURITY_TICKS - agent['age_ticks']}"
            )
            print(
                f"  {agent['name']:20s} ({agent['x']:>3},{agent['y']:>3})  "
                f"{agent['state']:8s} goal={agent['goal']:9s} "
                f"hunger={agent['hunger']:.2f} energy={agent['energy']:.2f} "
                f"age={agent['age_ticks']} ({maturity}) "
                f"starving_ticks={agent['starving_ticks']}"
            )
            if agent["goal_reason"]:
                print(f"    \"{agent['goal_reason']}\"")
            if agent.get("memories"):
                print(f"    memory: {agent['memories'][-1]}")

    print(f"\nRecent events (latest {len(events)}):")
    for event in events:
        when = datetime.datetime.fromtimestamp(event["logged_at"]).strftime("%Y-%m-%d %H:%M:%S")
        print(f"  [tick {event['tick']:>6}] {when}  {event['category']:12s} {event['description']}")


if __name__ == "__main__":
    main()
