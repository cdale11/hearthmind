#!/usr/bin/env python3
"""Tier 6 L1.1's real offline trainer: builds a corpus straight from a
running (or snapshotted) world's OWN already-real text -- `World.
emergence_log` summaries, `Agent.memories`/`semantic_memories`,
`Settlement.beliefs`/`folklore`/`legends`/`records`, and every
cognitive pillar's `world_model` (`hearthmind.ml.corpus.collect_world_
corpus`) -- and trains a `hearthmind.ml.embedding.SkipGramEmbedding`
on it. **Needs no live-LLM training-recorder archive at all** --
unlike `train_goal_policy_from_archive.py`, which specifically needs
recorded `(structured_input, goal)` decision pairs, this only needs
sentences, and this codebase already writes plenty of those even with
the LLM disabled (deterministic event/chronicle templates).

Output: a weights file at the path `SimulationEngine` loads
automatically (`<directory next to your world's db_path>/embedding_
weights.json` -- see `hearthmind.simulation.engine.EMBEDDING_
FILENAME`/`_embedding_path_for`). Absent that file, every world uses
the exact original bag-of-words memory relevance -- dropping this
file in is the entire "wire it live" step.

Usage:
    python3 scripts/train_embedding_from_world.py \\
        --db-path /path/to/world/hearthmind.db \\
        --out /path/to/world/embedding_weights.json

    # Or point --out anywhere and copy it into place yourself:
    python3 scripts/train_embedding_from_world.py \\
        --db-path hearthmind.db --out embedding_weights.json
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from hearthmind.ml.corpus import collect_world_corpus
from hearthmind.ml.embedding import train_skipgram

MIN_SENTENCES_REQUIRED = 20


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db-path", required=True, help="Path to your world's SQLite db")
    parser.add_argument("--out", required=True, help="Output path for the trained embedding weights JSON")
    parser.add_argument("--dim", type=int, default=32, help="Embedding dimension (default: module default, 32)")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    world = load_world(args.db_path)
    print(f"Loaded world at tick {world.clock.tick_count}, "
          f"{len(world.settlements)} settlement(s), "
          f"{len(world.population.agents)} living agent(s).")

    corpus = collect_world_corpus(world)
    print(f"Extracted {len(corpus)} distinct real sentences from this world's own state "
          f"(emergence log, agent memories, settlement beliefs/folklore/legends, pillar world-models).")

    if len(corpus) < MIN_SENTENCES_REQUIRED:
        print(f"ERROR: only {len(corpus)} usable sentences found -- need at least "
              f"{MIN_SENTENCES_REQUIRED}. Let this world run (with the LLM enabled, for richer "
              f"prose) for longer before training an embedding from it.")
        return 1

    embedding = train_skipgram(corpus, dim=args.dim, epochs=args.epochs, seed=args.seed)
    print(f"Trained a {args.dim}-dim embedding over a {len(embedding.vocab)}-word vocabulary.")

    import json
    with open(args.out, "w") as f:
        json.dump(embedding.to_dict(), f)
    print(f"Wrote trained weights to {args.out}")
    print("Drop this file next to your world's db_path as 'embedding_weights.json' to wire it live.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
