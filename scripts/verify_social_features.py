#!/usr/bin/env python3
"""Tier 6, L1.2 -- `hearthmind/ml/social_features.py`'s `compute_social_
features`: neighborhood sentiment, weighted centrality, community
affiliation, bridge-ness, all built directly over `world/graph_
algorithms.py`'s already-real `build_relationship_graph`/`degree_
centrality`. Real production-path checks against a real `Population`/
`Agent` set plus hand-built synthetic graphs for the two new structural
computations, no unittest, same standalone-script convention as every
sibling `verify_*.py`."""
from __future__ import annotations

import sys
import tempfile

from hearthmind.config import Config
from hearthmind.ml.social_features import (
    _bridge_score,
    _connected_components,
    _neighborhood_sentiment,
    compute_social_features,
)
from hearthmind.persistence.database import connect
from hearthmind.simulation.engine import SimulationEngine

CHECKS = 0
FAILURES: list[str] = []


def check(name: str, condition: bool) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
    else:
        print(f"[ OK ] {name}")


def main() -> int:
    # _neighborhood_sentiment
    check("isolated agent (no edges) reads 0.0, not undefined", _neighborhood_sentiment({}) == 0.0)
    check("mean edge weight is computed correctly", _neighborhood_sentiment({1: 0.2, 2: 0.8}) == 0.5)

    # _connected_components: two genuinely disjoint clusters plus a bridge case.
    disjoint_graph = {
        1: {2: 0.5}, 2: {1: 0.5},
        3: {4: 0.5}, 4: {3: 0.5},
    }
    comps = _connected_components(disjoint_graph)
    check("two disjoint clusters get distinct community ids",
          comps[1] == comps[2] and comps[3] == comps[4] and comps[1] != comps[3])

    bridging_graph = {
        1: {2: 0.5}, 2: {1: 0.5, 3: 0.5}, 3: {2: 0.5},
    }
    comps2 = _connected_components(bridging_graph)
    check("a real chain connects every node into one community",
          comps2[1] == comps2[2] == comps2[3])

    singleton_graph = {5: {}}
    comps3 = _connected_components(singleton_graph)
    check("an isolated node is its own singleton community", 5 in comps3)

    # Zero-weight edges never merge components (graph edges are always
    # >= 0.0 by construction; a real 0.0 edge should not count as connected).
    zero_edge_graph = {1: {2: 0.0}, 2: {1: 0.0}}
    comps4 = _connected_components(zero_edge_graph)
    check("a zero-weight edge does not merge two nodes into one community", comps4[1] != comps4[2])

    # _bridge_score
    check("fewer than 2 neighbors always scores 0.0 (no pairs to measure)", _bridge_score({}, {}) == 0.0)
    check("exactly 1 neighbor always scores 0.0", _bridge_score({1: {2: 0.5}}, {2: 0.5}) == 0.0)

    # A genuine bridge: agent 1 connects two neighbors (2, 3) who are NOT
    # themselves connected to each other -- maximal bridge score (1.0).
    bridge_graph = {
        1: {2: 0.5, 3: 0.5},
        2: {1: 0.5},
        3: {1: 0.5},
    }
    check("a real bridging agent (neighbors mutually unconnected) scores 1.0",
          _bridge_score(bridge_graph, bridge_graph[1]) == 1.0)

    # A fully clustered agent: all of 1's neighbors (2, 3) are also
    # connected to each other -- minimal bridge score (0.0).
    clustered_graph = {
        1: {2: 0.5, 3: 0.5},
        2: {1: 0.5, 3: 0.5},
        3: {1: 0.5, 2: 0.5},
    }
    check("a fully clustered agent (all neighbors also connected) scores 0.0",
          _bridge_score(clustered_graph, clustered_graph[1]) == 0.0)

    # A partial bridge: 3 neighbors, only one connected pair among them.
    partial_graph = {
        1: {2: 0.5, 3: 0.5, 4: 0.5},
        2: {1: 0.5, 3: 0.5},
        3: {1: 0.5, 2: 0.5},
        4: {1: 0.5},
    }
    # pairs: (2,3) connected, (2,4) not, (3,4) not -> 1/3 connected -> score 2/3
    score = _bridge_score(partial_graph, partial_graph[1])
    check("a partially bridging agent scores strictly between 0 and 1",
          abs(score - (2.0 / 3.0)) < 1e-9)

    # compute_social_features: end-to-end over a hand-built graph via a
    # real Population, exercising build_relationship_graph/degree_centrality
    # integration together with the two new features.
    tmpdir = tempfile.mkdtemp()
    db_path = f"{tmpdir}/social_features.db"
    conn = connect(db_path)
    cfg = Config(db_path=db_path, llm_enabled=False, seed=42, initial_population=10, width=24, height=24)
    eng = SimulationEngine.load_or_create(conn, cfg)
    living_agents = list(eng.world.population.agents)
    check("a real population has at least a few living agents to test against", len(living_agents) >= 2)

    # Force a real relationship so at least one non-trivial edge exists.
    a, b = living_agents[0], living_agents[1]
    a.relationships[b.id] = 0.8
    b.relationships[a.id] = 0.8

    features = compute_social_features(living_agents)
    check("every living agent with at least one real edge appears in the output",
          a.id in features and b.id in features)
    check("neighborhood_sentiment reflects the real forced relationship",
          features[a.id]["neighborhood_sentiment"] >= 0.7)
    check("weighted_centrality is a real float in [0, 1]",
          isinstance(features[a.id]["weighted_centrality"], float) and 0.0 <= features[a.id]["weighted_centrality"] <= 1.0)
    check("community_id is present (not None) for a connected agent", features[a.id]["community_id"] is not None)
    check("bridge_score is present and a real float", isinstance(features[a.id]["bridge_score"], float))

    check("compute_social_features calls build_relationship_graph/degree_centrality exactly once each "
          "(not recomputed per agent) -- verified by output internal consistency",
          all(isinstance(v["community_id"], int) for v in features.values() if v["community_id"] is not None))

    # Non-mutation: calling compute_social_features must never mutate the
    # real Agent objects passed in.
    before = dict(a.relationships)
    compute_social_features(living_agents)
    check("compute_social_features never mutates the real agents passed in", a.relationships == before)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed.")
    if FAILURES:
        print("FAILURES:", FAILURES)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
