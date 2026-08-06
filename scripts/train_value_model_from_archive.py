#!/usr/bin/env python3
"""Tier 6 L2.1's real offline trainer: `hearthmind.ml.value_model.
ValueConsequenceModel`, wired (roadmap Phase 2) into `SimulationEngine.
_voice_narrative_extra_scores` (the weekly voice-pair "who's the
protagonist" score).

**Needs no live-LLM training-recorder archive** -- like `train_
embedding_from_world.py`/`train_belief_calibrator_from_archive.py`,
this trains straight from a real, already-persisted World.

**Honest gap, stated plainly** (same discipline as `LLMCostRegressor`'s
own trainer): `world/emergence.py`'s `Observation` entries are NOT
tagged with which agent they're about (no `agent_id` field exists on
the shape today), so a true per-observation "(this agent's state at
the time, did it matter)" pair can't be reconstructed from `World.
emergence_log` alone. Instead, each real LIVING core-cast agent's
CURRENT feature snapshot is paired with a label derived from that same
agent's own already-tracked outcome signals: `Agent.extreme_event_
count` (Phase 3.B's real irreversible-personality counter -- bumped
only at genuinely consequential events: disaster survival, feud/
ostracism, widowhood) as the magnitude proxy, and whether the agent
currently holds any `core_memories` (a real, permanently-retained --
never evicted -- salience-selected memory) as the life-event-followed
signal. Both are real, already-persisted per-agent state, never
fabricated -- but this gives one snapshot in time per agent, not a
true historical time series. Re-running this trainer periodically
against a world as it ages (or against several worlds) is the
practical way to accumulate real variety.

Usage:
    python3 scripts/train_value_model_from_archive.py \\
        --db-path /path/to/world/hearthmind.db \\
        --out-dir /path/to/world/

Writes value_model_weights.json -- see `hearthmind.simulation.engine.
VALUE_MODEL_FILENAME`/`_value_model_path_for` for the exact name
`SimulationEngine` looks for.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, ".")

from hearthmind.ml.value_model import ValueConsequenceModel, make_training_example

MIN_EXAMPLES_REQUIRED = 5
EXTREME_EVENT_MAGNITUDE_SCALE = 3.0
"""Same cadence `Agent.hardened_traits`' own `EXTREME_EVENT_HARDEN_
THRESHOLD` (3) uses elsewhere in this codebase -- three real extreme
events is already "notably marked," so that count reaches magnitude
1.0 rather than needing ten."""


def load_world(db_path: str):
    """Loads the real, already-persisted `World` at `db_path` -- the
    same load path `server.py`/`SimulationEngine` themselves use, not
    a parallel reader."""
    from hearthmind.config import Config
    from hearthmind.persistence.database import connect
    from hearthmind.persistence.snapshot import load_latest_snapshot

    conn = connect(db_path)
    world = load_latest_snapshot(conn, Config(db_path=db_path))
    if world is None:
        raise ValueError(f"no snapshot found in {db_path!r} -- has this world ever ticked and saved?")
    return world


def build_examples(world) -> list:
    """One example per living core-cast agent -- see the module
    docstring for exactly what each field's real source is. Scoped to
    the core cast, matching `_voice_narrative_extra_scores`'s own
    real candidate pool (`select_voice_pair` only ever considers
    core-cast agents)."""
    population = world.population
    alive_ids = {a.id for a in population.agents}
    examples = []
    for agent_id in population.core_agent_ids:
        if agent_id not in alive_ids:
            continue
        agent = population.get(agent_id)
        if agent is None:
            continue
        emotion_intensity = max(agent.emotions.values()) if agent.emotions else 0.0
        if agent.relationships:
            relationship_extremity = sum(abs(v) for v in agent.relationships.values()) / len(agent.relationships)
        else:
            relationship_extremity = 0.0
        features = {
            "emotion_intensity": emotion_intensity,
            "recent_event_count_k": min(1.0, agent.extreme_event_count / 10.0),
            "relationship_extremity": relationship_extremity,
            "is_core_cast": 1.0,
        }
        magnitude = min(1.0, agent.extreme_event_count / EXTREME_EVENT_MAGNITUDE_SCALE)
        life_event_followed = len(agent.core_memories) > 0
        examples.append(make_training_example(features, magnitude, life_event_followed))
    return examples


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="Path to your world's SQLite db")
    parser.add_argument("--out-dir", required=True, help="Directory to write value_model_weights.json into (your world's db directory)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--epochs", type=int, default=80)
    parser.add_argument("--lr", type=float, default=0.05)
    args = parser.parse_args()

    world = load_world(args.db_path)
    print(f"Loaded world at tick {world.clock.tick_count}, "
          f"{len(world.population.core_agent_ids)} core-cast slot(s).")

    examples = build_examples(world)
    print(f"Built {len(examples)} real per-agent (feature snapshot, outcome) pairs from the living core cast.")

    if len(examples) < MIN_EXAMPLES_REQUIRED:
        print(f"Not enough living core-cast agents (need at least {MIN_EXAMPLES_REQUIRED}) — "
              "let this world run longer, or grow its core cast, before trying again.")
        return 1

    model = ValueConsequenceModel.new(seed=args.seed)
    model.train(examples, epochs=args.epochs, learning_rate=args.lr, seed=args.seed)
    loss = model.evaluate(examples)
    print(f"Training-set MSE (0..1-scaled units): {loss:.4f}")

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "value_model_weights.json")
    model.save(out_path)
    print(f"Wrote trained weights to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
