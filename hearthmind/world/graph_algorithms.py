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
