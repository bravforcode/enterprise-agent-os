"""Enterprise Agent OS — GraphRAG (Knowledge Graph RAG) Technique.

Builds a knowledge graph from document chunks with entity extraction,
relationship detection, community detection, and personalized PageRank
for multi-hop reasoning retrieval.

Based on Microsoft GraphRAG (2024-2025) patterns.
"""
from __future__ import annotations
import re
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..chunker import Chunk


@dataclass
class Entity:
    """A named entity extracted from text."""
    name: str
    entity_type: str  # PERSON, ORG, CONCEPT, EVENT, LOCATION, etc.
    mentions: List[str] = field(default_factory=list)
    chunk_ids: List[str] = field(default_factory=list)


@dataclass
class Relationship:
    """A relationship between two entities."""
    source: str
    target: str
    relation_type: str
    weight: float = 1.0
    chunk_ids: List[str] = field(default_factory=list)


@dataclass
class Community:
    """A detected community (cluster) in the knowledge graph."""
    id: int
    entities: List[str]
    summary: str = ""
    centrality: float = 0.0


class KnowledgeGraph:
    """In-memory knowledge graph using adjacency lists."""

    def __init__(self):
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.adjacency: Dict[str, List[Tuple[str, float, str]]] = defaultdict(list)
        self.communities: List[Community] = []

    def add_entity(self, entity: Entity) -> None:
        """Add an entity to the graph."""
        key = entity.name.lower()
        if key in self.entities:
            existing = self.entities[key]
            existing.mentions.extend(entity.mentions)
            existing.chunk_ids.extend(entity.chunk_ids)
        else:
            self.entities[key] = entity

    def add_relationship(self, rel: Relationship) -> None:
        """Add a relationship to the graph."""
        self.relationships.append(rel)
        src = rel.source.lower()
        tgt = rel.target.lower()
        self.adjacency[src].append((tgt, rel.weight, rel.relation_type))
        self.adjacency[tgt].append((src, rel.weight, rel.relation_type))

    def get_neighbors(self, entity_name: str) -> List[Tuple[str, float, str]]:
        """Get neighboring entities with edge weights and relation types."""
        return self.adjacency.get(entity_name.lower(), [])

    def get_entity(self, name: str) -> Optional[Entity]:
        """Get an entity by name."""
        return self.entities.get(name.lower())


# ---------------------------------------------------------------------------
# Entity Extraction (rule-based, no external deps)
# ---------------------------------------------------------------------------

# Common entity patterns
_ENTITY_PATTERNS = [
    # Capitalized multi-word names (e.g., "New York", "John Smith")
    (r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", "PERSON"),
    # Organizations (Inc, Corp, LLC, Ltd, University, etc.)
    (r"\b([A-Z][a-zA-Z\s]+(?:Inc|Corp|LLC|Ltd|University|Institute|Company|Group|Foundation|Association|Organization|Federal|National|Global|International))\b", "ORG"),
    # Acronyms (e.g., NASA, FDA, AI, ML)
    (r"\b([A-Z]{2,6})\b", "ACRONYM"),
    # Quoted terms
    (r'"([^"]{2,60})"', "CONCEPT"),
    # Parenthetical abbreviations
    (r"\b([A-Z][a-z]+)\s+\(([A-Z]{2,6})\)", "ORG"),
]


def extract_entities(text: str, chunk_id: str = "") -> List[Entity]:
    """Extract named entities from text using pattern-based heuristics.

    Args:
        text: Source text to extract entities from.
        chunk_id: ID of the chunk this text belongs to.

    Returns:
        List of extracted Entity objects.
    """
    entities: Dict[str, Entity] = {}

    for pattern, etype in _ENTITY_PATTERNS:
        for match in re.finditer(pattern, text):
            name = match.group(1) if match.lastindex else match.group(0)
            key = name.lower()
            if key in entities:
                entities[key].mentions.append(match.group(0))
                if chunk_id:
                    entities[key].chunk_ids.append(chunk_id)
            else:
                entities[key] = Entity(
                    name=name,
                    entity_type=etype,
                    mentions=[match.group(0)],
                    chunk_ids=[chunk_id] if chunk_id else [],
                )

    return list(entities.values())


def extract_relationships(
    text: str,
    entities: List[Entity],
    chunk_id: str = "",
) -> List[Relationship]:
    """Extract relationships between co-occurring entities.

    Uses proximity-based heuristic: entities within the same sentence
    are considered related.

    Args:
        text: Source text.
        entities: Pre-extracted entities.
        chunk_id: Chunk ID for tracking.

    Returns:
        List of Relationship objects.
    """
    entity_names = {e.name.lower(): e.name for e in entities}
    relationships = []

    # Split into sentences
    sentences = re.split(r"[.!?]\s+", text)

    for sentence in sentences:
        # Find entities present in this sentence
        present = []
        for name_lower, name_orig in entity_names.items():
            if name_lower in sentence.lower():
                present.append(name_orig)

        # Create relationships for co-occurring entities
        for i in range(len(present)):
            for j in range(i + 1, min(i + 3, len(present))):  # Limit to nearby entities
                # Determine relation type based on sentence patterns
                rel_type = _infer_relation_type(sentence, present[i], present[j])
                relationships.append(Relationship(
                    source=present[i],
                    target=present[j],
                    relation_type=rel_type,
                    weight=1.0,
                    chunk_ids=[chunk_id] if chunk_id else [],
                ))

    return relationships


def _infer_relation_type(sentence: str, entity_a: str, entity_b: str) -> str:
    """Infer relationship type from sentence context."""
    lower = sentence.lower()
    a_lower = entity_a.lower()
    b_lower = entity_b.lower()

    # Find the position of each entity
    pos_a = lower.find(a_lower)
    pos_b = lower.find(b_lower)
    if pos_a < 0 or pos_b < 0:
        return "related_to"

    # Extract the text between entities
    start = min(pos_a + len(entity_a), pos_b + len(entity_b))
    end = max(pos_a, pos_b)
    between = lower[start:end] if start < end else ""

    # Pattern-based relation inference
    if any(w in between for w in ["is", "was", "are", "were"]):
        return "is_a"
    elif any(w in between for w in ["of", "from", "in", "at"]):
        return "part_of"
    elif any(w in between for w in ["works", "leads", "manages", "founded"]):
        return "works_with"
    elif any(w in between for w in ["uses", "requires", "depends"]):
        return "uses"
    elif any(w in between for w in ["creates", "produces", "generates"]):
        return "creates"
    else:
        return "related_to"


# ---------------------------------------------------------------------------
# Community Detection (Louvain-inspired)
# ---------------------------------------------------------------------------

def detect_communities(
    graph: KnowledgeGraph,
    resolution: float = 1.0,
    max_iterations: int = 20,
) -> List[Community]:
    """Detect communities in the knowledge graph using a Louvain-inspired method.

    Args:
        graph: The knowledge graph.
        resolution: Resolution parameter (higher = more communities).
        max_iterations: Maximum optimization iterations.

    Returns:
        List of detected communities.
    """
    if not graph.entities:
        return []

    # Initialize: each entity in its own community
    entity_names = list(graph.entities.keys())
    community_map = {name: i for i, name in enumerate(entity_names)}

    # Calculate total edge weight
    total_weight = 0.0
    for neighbors in graph.adjacency.values():
        for _, weight, _ in neighbors:
            total_weight += weight
    total_weight = max(total_weight, 1.0)

    # Degree (weighted) per node
    degree: Dict[str, float] = {}
    for name in entity_names:
        degree[name] = sum(w for _, w, _ in graph.adjacency.get(name, []))

    # Iterative optimization
    for _ in range(max_iterations):
        improved = False
        for name in entity_names:
            current_comm = community_map[name]
            best_comm = current_comm
            best_delta = 0.0

            # Calculate gain from moving to each neighbor's community
            neighbor_comms: Dict[int, float] = defaultdict(float)
            for neighbor, weight, _ in graph.adjacency.get(name, []):
                if neighbor in community_map:
                    neighbor_comms[community_map[neighbor]] += weight

            for comm, comm_weight in neighbor_comms.items():
                if comm == current_comm:
                    continue
                # Modularity gain approximation
                sigma_in = comm_weight
                sigma_tot = sum(
                    degree[n] for n in entity_names if community_map[n] == comm
                )
                k_i = degree.get(name, 0.0)
                delta = (sigma_in - sigma_tot * k_i / total_weight) * resolution
                if delta > best_delta:
                    best_delta = delta
                    best_comm = comm

            if best_comm != current_comm:
                community_map[name] = best_comm
                improved = True

        if not improved:
            break

    # Build community objects
    comm_entities: Dict[int, List[str]] = defaultdict(list)
    for name, comm_id in community_map.items():
        comm_entities[comm_id].append(name)

    communities = []
    for comm_id, members in comm_entities.items():
        if len(members) >= 2:  # Only keep non-trivial communities
            # Calculate centrality as average degree within community
            internal_weight = 0.0
            for m in members:
                for neighbor, weight, _ in graph.adjacency.get(m, []):
                    if neighbor in members:
                        internal_weight += weight
            centrality = internal_weight / max(len(members), 1)
            communities.append(Community(
                id=comm_id,
                entities=members,
                centrality=centrality,
            ))

    graph.communities = communities
    return communities


# ---------------------------------------------------------------------------
# Personalized PageRank
# ---------------------------------------------------------------------------

def personalized_pagerank(
    graph: KnowledgeGraph,
    query_entities: List[str],
    damping: float = 0.85,
    max_iterations: int = 30,
    tolerance: float = 1e-6,
) -> Dict[str, float]:
    """Run Personalized PageRank seeded with query entities.

    Args:
        graph: The knowledge graph.
        query_entities: Seed entities to start traversal from.
        damping: Damping factor (probability of following edges).
        max_iterations: Maximum iterations.
        tolerance: Convergence tolerance.

    Returns:
        Dict mapping entity names to PageRank scores.
    """
    entity_names = list(graph.entities.keys())
    n = len(entity_names)
    if n == 0:
        return {}

    name_to_idx = {name: i for i, name in enumerate(entity_names)}

    # Initialize personalization vector (seed distribution)
    personalization = [0.0] * n
    seed_count = 0
    for qe in query_entities:
        key = qe.lower()
        if key in name_to_idx:
            personalization[name_to_idx[key]] = 1.0
            seed_count += 1

    if seed_count == 0:
        # Uniform distribution as fallback
        personalization = [1.0 / n] * n
    else:
        total = sum(personalization)
        personalization = [p / total for p in personalization]

    # Build transition matrix (sparse)
    out_degree = [0.0] * n
    for name, idx in name_to_idx.items():
        neighbors = graph.adjacency.get(name, [])
        out_degree[idx] = sum(w for _, w, _ in neighbors)

    # Iterate
    scores = [1.0 / n] * n
    for _ in range(max_iterations):
        new_scores = [0.0] * n
        # Damping: random jump to personalization
        for i in range(n):
            new_scores[i] = (1.0 - damping) * personalization[i]

        # Edge contributions
        for name, idx in name_to_idx.items():
            neighbors = graph.adjacency.get(name, [])
            if not neighbors or out_degree[idx] == 0:
                # Dangling node: redistribute to all
                for j in range(n):
                    new_scores[j] += damping * scores[idx] * personalization[j]
            else:
                total_w = sum(w for _, w, _ in neighbors)
                for neighbor, weight, _ in neighbors:
                    if neighbor in name_to_idx:
                        n_idx = name_to_idx[neighbor]
                        new_scores[n_idx] += damping * scores[idx] * (weight / total_w)

        # Check convergence
        diff = sum(abs(new_scores[i] - scores[i]) for i in range(n))
        scores = new_scores
        if diff < tolerance:
            break

    return {entity_names[i]: scores[i] for i in range(n)}


# ---------------------------------------------------------------------------
# Graph-Enhanced Retrieval
# ---------------------------------------------------------------------------

def graph_rag_retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
    max_hops: int = 2,
    use_communities: bool = True,
) -> List[Tuple[Chunk, float, Dict[str, Any]]]:
    """Retrieve chunks using GraphRAG multi-hop reasoning.

    Extracts entities from query, traverses the knowledge graph,
    and ranks chunks by graph-augmented relevance.

    Args:
        query: Search query.
        chunks: List of document chunks.
        top_k: Number of results to return.
        max_hops: Maximum graph hops for multi-hop reasoning.
        use_communities: Whether to use community detection for boosting.

    Returns:
        List of (chunk, score, metadata) tuples sorted by relevance.
    """
    # Step 1: Build knowledge graph from chunks
    graph = KnowledgeGraph()
    chunk_entity_map: Dict[str, List[str]] = {}  # chunk_id -> entity names

    for chunk in chunks:
        entities = extract_entities(chunk.content, chunk.id)
        relationships = extract_relationships(chunk.content, entities, chunk.id)

        for entity in entities:
            graph.add_entity(entity)
        for rel in relationships:
            graph.add_relationship(rel)

        chunk_entity_map[chunk.id] = [e.name.lower() for e in entities]

    if not graph.entities:
        # Fallback: no entities found, return empty
        return []

    # Step 2: Extract query entities
    query_entities = extract_entities(query, "query")
    query_entity_names = [e.name for e in query_entities]

    if not query_entity_names:
        # Fallback: use all high-mention entities
        sorted_entities = sorted(
            graph.entities.values(),
            key=lambda e: len(e.chunk_ids),
            reverse=True,
        )
        query_entity_names = [e.name for e in sorted_entities[:3]]

    # Step 3: Community detection (optional)
    communities = {}
    if use_communities:
        comms = detect_communities(graph)
        for comm in comms:
            for entity in comm.entities:
                communities[entity] = comm

    # Step 4: Personalized PageRank
    pagerank_scores = personalized_pagerank(graph, query_entity_names)

    # Step 5: Multi-hop entity expansion
    expanded_entities = set(query_entity_names)
    frontier = set(e.lower() for e in query_entity_names)
    for hop in range(max_hops):
        next_frontier = set()
        for entity in frontier:
            for neighbor, weight, rel_type in graph.get_neighbors(entity):
                if neighbor not in expanded_entities:
                    expanded_entities.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier

    # Step 6: Score chunks
    scored_chunks: List[Tuple[Chunk, float, Dict[str, Any]]] = []
    for chunk in chunks:
        chunk_entities = set(chunk_entity_map.get(chunk.id, []))

        # Direct entity overlap
        overlap = chunk_entities & expanded_entities
        if not overlap:
            continue

        # Base score from entity overlap
        overlap_score = len(overlap) / max(len(query_entity_names), 1)

        # PageRank boost
        pr_score = sum(pagerank_scores.get(e, 0.0) for e in overlap)
        pr_boost = min(pr_score * 10, 1.0)  # Normalize

        # Community boost
        community_boost = 0.0
        if use_communities:
            chunk_community_ids = {communities[e].id for e in overlap if e in communities}
            if chunk_community_ids:
                chunk_communities = [communities[e] for e in overlap if e in communities and communities[e].id in chunk_community_ids]
                max_centrality = max(c.centrality for c in chunk_communities)
                community_boost = min(max_centrality * 0.5, 0.3)

        # Combined score
        combined = 0.5 * overlap_score + 0.3 * pr_boost + 0.2 * community_boost

        metadata = {
            "matched_entities": list(overlap),
            "pagerank_score": pr_score,
            "community_boost": community_boost,
            "graph_hops": max_hops,
        }
        scored_chunks.append((chunk, combined, metadata))

    scored_chunks.sort(key=lambda x: -x[1])
    return scored_chunks[:top_k]


def graph_rag_full(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
    max_hops: int = 2,
) -> Dict[str, Any]:
    """Full GraphRAG pipeline: extract, build graph, detect communities, retrieve.

    Args:
        query: Search query.
        chunks: Document chunks.
        top_k: Number of results.
        max_hops: Max traversal hops.

    Returns:
        Dict with results, graph stats, and community info.
    """
    graph = KnowledgeGraph()

    for chunk in chunks:
        entities = extract_entities(chunk.content, chunk.id)
        relationships = extract_relationships(chunk.content, entities, chunk.id)
        for e in entities:
            graph.add_entity(e)
        for r in relationships:
            graph.add_relationship(r)

    communities = detect_communities(graph) if graph.entities else []

    results = graph_rag_retrieve(query, chunks, top_k, max_hops)

    return {
        "query": query,
        "results": [
            {
                "content": c.content,
                "score": round(s, 4),
                "source": c.source,
                "metadata": m,
            }
            for c, s, m in results
        ],
        "graph_stats": {
            "entities": len(graph.entities),
            "relationships": len(graph.relationships),
            "communities": len(communities),
        },
        "communities": [
            {"id": c.id, "members": c.entities, "centrality": round(c.centrality, 4)}
            for c in communities[:10]
        ],
    }
