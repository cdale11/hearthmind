"""A16 "Graph representation + graph algorithms" (docs/MASTERCHECKLIST-
2026-07-22.md, Part A, Stage I step 3): the pairwise ledger
(`agents/ledger.py`) is already an edge store — this module is the
first real *algorithm* run over it, not a second graph structure.
Scoped to real, cheap, deterministic algorithms over graphs the
codebase already has rather than the doc's full wishlist (betweenness,
trade-as-network-flow) — same "ship one genuine consumer, prove the
shape" discipline `world/emergence.py` used for A22. Community
detection (the doc's other headline example) is already shipped as
`InstitutionKind.FACTION` detection (v0.80.0, `Population._maybe_
detect_faction`'s trust-graph union-find) under a different name — not
duplicated here.

Second algorithm (roadmap A16's "tech-as-DAG" piece): the Innovation
Layer's `InventedConcept.lineage` (world/ontology.py) is already a real
DAG — `ancestor_ids`/`shares_lineage` below are the first genuine
traversal over it, consumed by `SimulationEngine._maybe_schedule_
ontology_evolution`'s merge-pair selection to block a concept from
being merged with its own kin.

Third algorithm (roadmap A16's "information-propagation-as-graph-
algorithm" piece): `bfs_distances` below, consumed by `Population.
spread_rumor`'s listener selection.

Fourth and last algorithm (roadmap A16's "trade-as-network-flow"
piece, closing A16 entirely): `build_settlement_trade_graph`/
`max_flow` below, a real Edmonds-Karp max-flow over `Settlement.
relations` (already a real weighted inter-settlement graph, previously
only ever read as a flat average multiplier), consumed by
`SimulationEngine._maybe_tick_settlement_trade`.

Deliberately reuses `Agent.relationships` (the ledger's fondness view)
directly rather than materializing a separate adjacency structure:
degree centrality only needs each node's own edge weights, never a
full traversal, so there's nothing a real graph object would buy here
that the existing per-agent dict doesn't already give for free."""
from __future__ import annotations

from collections import deque


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


def ancestor_ids(world, concept_id: int, _seen: "set[int] | None" = None) -> "set[int]":
    """A16's second real graph algorithm: transitive closure over the
    Innovation ontology's lineage DAG (`InventedConcept.lineage`'s
    `evolved_from`/`merged_from` edges, world/ontology.py) — a real
    upward traversal, not just the single-hop parent read `_referenced_
    ids` already does for pruning-protection. Returns every ancestor
    id reachable from `concept_id`, however many generations back;
    empty for an original (generation-0) concept or an unknown id.
    `_seen` guards against a corrupt/cyclic lineage (should never
    happen — `register_concept` only ever points a child at already-
    existing parents — but a graph traversal should never infinite-loop
    on bad data regardless)."""
    seen = _seen if _seen is not None else set()
    concept = world.invented_concepts.get(concept_id)
    if concept is None:
        return set()
    ancestors: set[int] = set()
    parent_ids = []
    evolved_from = concept.lineage.get("evolved_from")
    if evolved_from is not None:
        parent_ids.append(evolved_from)
    parent_ids.extend(concept.lineage.get("merged_from") or ())
    for parent_id in parent_ids:
        if parent_id in seen:
            continue
        seen.add(parent_id)
        ancestors.add(parent_id)
        ancestors |= ancestor_ids(world, parent_id, seen)
    return ancestors


def bfs_distances(graph: dict[str, dict[str, float]], source: str) -> dict[str, int]:
    """A16's third algorithm ("information-propagation-as-graph-
    algorithm"): shortest-hop-distance from `source` to every other
    reachable node, via a real breadth-first traversal of the same
    weighted relationship graph `build_relationship_graph` produces —
    only a genuine positive tie (`weight > 0`) counts as a social path;
    an absent or zero-weight edge doesn't carry news. `source` itself
    is distance 0; an unreachable node is simply absent from the
    result (no path exists, not an infinite distance to represent).

    Real consumer: `Population.spread_rumor`'s listener selection (see
    its own docstring) — previously every listener was drawn by pure
    `rng.sample` over the WHOLE population, with no notion that news
    should ripple outward through a social circle rather than
    teleporting to unconnected strangers. This is deliberately BFS
    (unweighted hop count), not a weighted shortest-path — "how many
    people does this have to pass through" is the real epidemiological
    quantity a rumor's reach should track, not cumulative tie
    strength (`propagation_weight` already covers strength-of-a-single-
    hop; this covers a genuinely different axis, distance)."""
    if source not in graph:
        return {}
    distances: dict[str, int] = {source: 0}
    frontier: deque = deque([source])
    while frontier:
        node = frontier.popleft()
        for neighbor, weight in graph.get(node, {}).items():
            if weight <= 0.0 or neighbor in distances:
                continue
            distances[neighbor] = distances[node] + 1
            frontier.append(neighbor)
    return distances


def build_settlement_trade_graph(settlements: list) -> dict[int, dict[int, float]]:
    """A16's last named algorithm ("trade-as-network-flow"): the
    settlement-pair `Settlement.relations` walk (settlement/buildings.py,
    seeded at fission, nudged by cross-settlement dialogue) is already a
    real weighted graph over named settlements — it just had no
    consumer beyond flat AVERAGE-relation multipliers on price/caravan
    chance (`market_relation_factor`/`caravan_relation_factor`), never
    a genuine per-PAIR routing question. `weight = max(0.0, relation)`:
    a cold or hostile relation carries no trade capacity at all — goods
    don't flow along a route the settlements themselves refuse."""
    named = [s for s in settlements if s.name]
    graph: dict[int, dict[int, float]] = {s.id: {} for s in named}
    named_ids = {s.id for s in named}
    for settlement in named:
        for other_id, relation in settlement.relations.items():
            if other_id not in named_ids:
                continue
            graph[settlement.id][other_id] = max(0.0, relation)
    return graph


def max_flow(capacity: dict, source, sink) -> float:
    """A real Edmonds-Karp max-flow: repeatedly finds an augmenting
    path via BFS over the residual graph and pushes flow along it until
    none remains. `capacity` is a directed dict-of-dicts (an undirected
    graph like `build_settlement_trade_graph`'s just has matching
    entries both ways); this deliberately doesn't mutate the caller's
    `capacity` — it works over its own residual copy. Returns 0.0 if
    `source == sink`, either is absent from the graph, or no path
    exists between them at all.

    Real consumer: `SimulationEngine._maybe_tick_settlement_trade` — a
    settlement in materials surplus can supply one in deficit not only
    directly, but ALSO through a third settlement they're both on warm
    terms with even if the surplus and deficit settlements themselves
    are cold toward each other. That "route around a hostile direct
    link" case is the genuinely distinct thing a flow algorithm proves
    that a flat pairwise multiplier (`market_relation_factor`, etc.)
    structurally cannot express."""
    if source == sink or source not in capacity or sink not in capacity:
        return 0.0
    residual: dict = {u: dict(edges) for u, edges in capacity.items()}
    for u in list(residual.keys()):
        for v in list(residual[u].keys()):
            residual.setdefault(v, {})
            residual[v].setdefault(u, 0.0)

    def _augmenting_path():
        parent = {source: None}
        frontier = deque([source])
        while frontier:
            u = frontier.popleft()
            if u == sink:
                return parent
            for v, cap in residual.get(u, {}).items():
                if cap > 1e-9 and v not in parent:
                    parent[v] = u
                    frontier.append(v)
        return None

    total = 0.0
    while True:
        parent = _augmenting_path()
        if parent is None or sink not in parent:
            break
        bottleneck = float("inf")
        node = sink
        while node != source:
            prev = parent[node]
            bottleneck = min(bottleneck, residual[prev][node])
            node = prev
        node = sink
        while node != source:
            prev = parent[node]
            residual[prev][node] -= bottleneck
            residual[node][prev] += bottleneck
            node = prev
        total += bottleneck
    return total


def shares_lineage(world, id_a: int, id_b: int) -> bool:
    """True if two concepts are the same idea's own kin — one is a
    (however-distant) ancestor of the other, or they share any common
    ancestor. Real consumer: `SimulationEngine._maybe_schedule_
    ontology_evolution`'s merge-pair selection (roadmap A16) — without
    this check, evolve/merge could freely combine a concept with its
    own parent or grandparent (a degenerate "the idea absorbs itself"
    case that made no sense narratively and was previously entirely
    unguarded)."""
    if id_a == id_b:
        return True
    ancestors_a = ancestor_ids(world, id_a)
    ancestors_b = ancestor_ids(world, id_b)
    if id_a in ancestors_b or id_b in ancestors_a:
        return True
    return bool(ancestors_a & ancestors_b)
