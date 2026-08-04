"""Tier 6, L1.2 -- Social structure features (docs/ML-ARCHITECTURE-
2026-08-01.md: "not a GNN" -- one round of message passing over `agents/
ledger.py`'s pair graph, producing per-agent structural features:
neighbourhood sentiment, weighted centrality, community affiliation,
bridge-ness).

**Deliberately downgraded from a full GNN, per the architecture doc's
own text**: `world/graph_algorithms.py` already computes
`build_relationship_graph`/`degree_centrality` (and `bfs_distances`,
used elsewhere) -- the genuine gap was that nothing fed those to any
decision model. This module closes exactly that gap: it reuses those
two functions directly rather than building a parallel graph
representation, and adds the two named features that had no existing
implementation (community affiliation, bridge-ness) as cheap,
deterministic, single-pass graph computations -- no training, no
message-passing iterations, no GNN. Full end-to-end graph learning
stays explicitly out of scope, per the doc's own "revisit only if
L1.2's features prove load-bearing and insufficient."

**Community affiliation is graph-only, not an Institution lookup** --
a real design choice, not an oversight: `hearthmind.ml` sits below
`hearthmind.agents`/`hearthmind.settlement` in this project's own
stated dependency direction ("the substrate should stay reused UPWARD
by Runtime/gameplay code, never the reverse" -- see L3.1's own
docstring for the same discipline). Importing `Population.faction_of`
here would invert that. Instead, `community_id` is a real connected-
component id over the SAME positive-weight relationship graph
`build_relationship_graph` already returns -- a genuine structural
community, independent of (and complementary to) whatever a
settlement's own FACTION institutions separately track.

Standalone infrastructure, same "never big-bang" discipline as every
other Tier 6 module shipped so far -- not wired into any real consumer
this pass (L2.1/L2.2 are the doc's own named future consumers).
"""
from __future__ import annotations

from hearthmind.world.graph_algorithms import build_relationship_graph, degree_centrality


def compute_social_features(agents: list) -> dict:
    """Returns `{agent_id: {feature_name: value}}` for every living
    agent in `agents` -- the one entry point this module exposes.
    `build_relationship_graph`/`degree_centrality` are called exactly
    once each and their results shared across every per-agent feature,
    not recomputed per agent."""
    graph = build_relationship_graph(agents)
    centrality = degree_centrality(graph)
    community_of = _connected_components(graph)
    features = {}
    for agent_id, neighbors in graph.items():
        features[agent_id] = {
            "neighborhood_sentiment": _neighborhood_sentiment(neighbors),
            "weighted_centrality": centrality.get(agent_id, 0.0),
            "community_id": community_of.get(agent_id),
            "bridge_score": _bridge_score(graph, neighbors),
        }
    return features


def _neighborhood_sentiment(neighbors: dict) -> float:
    """Mean edge weight across an agent's own real ties -- how warmly
    regarded this agent's own immediate social circle is, on average.
    An isolated agent (no positive edges) reads 0.0, not undefined."""
    if not neighbors:
        return 0.0
    return sum(neighbors.values()) / len(neighbors)


def _connected_components(graph: dict) -> dict:
    """A real connected-component id per agent over the positive-weight
    relationship graph (every edge `build_relationship_graph` returns
    is already `>= 0.0` by construction, so "positive" here means
    genuinely nonzero) -- one plain BFS pass, deterministic given a
    deterministic node iteration order. Two agents share a
    `community_id` exactly when a real chain of positive relationships
    connects them; an isolated agent is its own singleton community."""
    visited = set()
    component_of = {}
    next_id = 0
    for start in graph:
        if start in visited:
            continue
        stack = [start]
        visited.add(start)
        component_of[start] = next_id
        while stack:
            current = stack.pop()
            for neighbor, weight in graph.get(current, {}).items():
                if weight > 0.0 and neighbor not in visited:
                    visited.add(neighbor)
                    component_of[neighbor] = next_id
                    stack.append(neighbor)
        next_id += 1
    return component_of


def _bridge_score(graph: dict, neighbors: dict) -> float:
    """A real, cheap structural-holes proxy (Burt's constraint, in
    spirit): the fraction of an agent's own neighbor PAIRS that are NOT
    themselves directly connected. High score = this agent's contacts
    mostly don't know each other = the agent genuinely bridges
    otherwise-separate parts of the social graph. An agent with fewer
    than two neighbors has no pairs to measure and scores 0.0 (not a
    bridge by construction, never undefined)."""
    neighbor_ids = list(neighbors.keys())
    if len(neighbor_ids) < 2:
        return 0.0
    total_pairs = 0
    connected_pairs = 0
    for i in range(len(neighbor_ids)):
        for j in range(i + 1, len(neighbor_ids)):
            a, b = neighbor_ids[i], neighbor_ids[j]
            total_pairs += 1
            if graph.get(a, {}).get(b, 0.0) > 0.0 or graph.get(b, {}).get(a, 0.0) > 0.0:
                connected_pairs += 1
    return 1.0 - (connected_pairs / total_pairs)
