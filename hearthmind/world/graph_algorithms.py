"""A16 "Graph representation + graph algorithms" (docs/MASTERCHECKLIST-
2026-07-22.md, Part A, Stage I step 3): the pairwise ledger
(`agents/ledger.py`) is already an edge store — this module is the
first real *algorithm* run over it, not a second graph structure.
Scoped to one cheap, deterministic metric (weighted-degree centrality)
over the relationship graph rather than the doc's full wishlist
(betweenness, network-flow, tech-dependency DAGs) — same "ship one
genuine consumer, prove the shape" discipline `world/emergence.py`
used for A22. Community detection (the doc's other headline example)
is already shipped as `InstitutionKind.FACTION` detection (v0.80.0,
`Population._maybe_detect_faction`'s trust-graph union-find) under a
different name — not duplicated here.

Deliberately reuses `Agent.relationships` (the ledger's fondness view)
directly rather than materializing a separate adjacency structure:
degree centrality only needs each node's own edge weights, never a
full traversal, so there's nothing a real graph object would buy here
that the existing per-agent dict doesn't already give for free."""
from __future__ import annotations


def build_relationship_graph(agents: list) -> dict[str, dict[str, float]]:
    """Living-agent-only view of the pairwise relationship ledger as an
    explicit weighted undirected graph: `{agent_id: {other_id: weight}}`,
    weight = max(0.0, fondness) — a negative relationship is a real
    edge in the ledger but shouldn't pull an agent's centrality *down*
    (this is "how connected," not "how well-liked"); a feud is absence
    of positive connection, not a negative one for this purpose."""
    living_ids = {a.id for a in agents}
    graph: dict[str, dict[str, float]] = {a.id: {} for a in agents}
    for agent in agents:
        for other_id, fondness in agent.relationships.items():
            if other_id not in living_ids or other_id == agent.id:
                continue
            graph[agent.id][other_id] = max(0.0, fondness)
    return graph


def degree_centrality(graph: dict[str, dict[str, float]]) -> dict[str, float]:
    """Sum of each node's own edge weights, normalized 0..1 against the
    graph's own maximum — cheap (O(V+E), no traversal), deterministic,
    and exactly the "who does this settlement's social network actually
    center on" signal A16 asks for. An isolated node (no positive
    edges) scores 0.0, not undefined."""
    raw = {node: sum(edges.values()) for node, edges in graph.items()}
    peak = max(raw.values(), default=0.0)
    if peak <= 0.0:
        return {node: 0.0 for node in raw}
    return {node: value / peak for node, value in raw.items()}


def most_central_agent(graph: dict[str, dict[str, float]]) -> str | None:
    """Returns the single highest-degree-centrality node, or `None` if
    every node scores 0.0 (no positive relationship edges at all yet —
    a freshly founded settlement, say). Ties break on the lower agent
    id for determinism (never RNG — this is a structural fact, not a
    judgment call)."""
    scores = degree_centrality(graph)
    positive = {node: score for node, score in scores.items() if score > 0.0}
    if not positive:
        return None
    return min(positive.items(), key=lambda item: (-item[1], item[0]))[0]
