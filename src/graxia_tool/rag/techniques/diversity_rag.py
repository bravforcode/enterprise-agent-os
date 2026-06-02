"""Enterprise Agent OS — Diversity-Focused RAG (DF-RAG) Technique.

Implements Maximal Marginal Relevance (MMR) for diverse retrieval,
query-adaptive diversity parameters, redundancy penalty, and balance
between relevance and diversity.

Based on MMR and DF-RAG patterns from 2025 research.
"""
from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..chunker import Chunk


@dataclass
class DiversityConfig:
    """Configuration for diversity-focused retrieval."""
    lambda_param: float = 0.7  # Relevance vs diversity balance (0=pure diversity, 1=pure relevance)
    redundancy_penalty: float = 0.3  # Penalty for redundant results
    min_diversity: float = 0.1  # Minimum diversity threshold
    max_similar: int = 2  # Maximum similar results allowed


@dataclass
class DiversityResult:
    """Result with diversity metadata."""
    chunk: Chunk
    relevance_score: float
    diversity_score: float
    combined_score: float
    is_redundant: bool
    similar_to: List[str]  # IDs of similar chunks


# ---------------------------------------------------------------------------
# Similarity Functions
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in re.findall(r"[a-z0-9\u0E00-\u0E7F]+", text.lower()) if len(t) > 1]


def _jaccard_similarity(text_a: str, text_b: str) -> float:
    """Compute Jaccard similarity between two texts."""
    tokens_a = set(_tokenize(text_a))
    tokens_b = set(_tokenize(text_b))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def _cosine_similarity_tfidf(text_a: str, text_b: str) -> float:
    """Compute TF-IDF weighted cosine similarity (lightweight approximation)."""
    tokens_a = _tokenize(text_a)
    tokens_b = _tokenize(text_b)

    if not tokens_a or not tokens_b:
        return 0.0

    # Build term frequency vectors
    all_terms = set(tokens_a) | set(tokens_b)
    tf_a = {t: tokens_a.count(t) for t in all_terms}
    tf_b = {t: tokens_b.count(t) for t in all_terms}

    # Simple IDF approximation (assume uniform)
    # In practice, would use corpus statistics
    dot = sum(tf_a[t] * tf_b[t] for t in all_terms)
    norm_a = math.sqrt(sum(v * v for v in tf_a.values())) + 1e-9
    norm_b = math.sqrt(sum(v * v for v in tf_b.values())) + 1e-9

    return dot / (norm_a * norm_b)


def _content_similarity(chunk_a: Chunk, chunk_b: Chunk) -> float:
    """Compute similarity between two chunks using combined metrics."""
    # Jaccard for keyword overlap
    jaccard = _jaccard_similarity(chunk_a.content, chunk_b.content)

    # Cosine for term frequency similarity
    cosine = _cosine_similarity_tfidf(chunk_a.content, chunk_b.content)

    # Source similarity (same document = more similar)
    source_sim = 1.0 if chunk_a.source == chunk_b.source else 0.0

    # Combined similarity
    return 0.4 * jaccard + 0.4 * cosine + 0.2 * source_sim


# ---------------------------------------------------------------------------
# Maximal Marginal Relevance (MMR)
# ---------------------------------------------------------------------------

def mmr_select(
    query: str,
    candidates: List[Tuple[Chunk, float]],
    top_k: int = 5,
    lambda_param: float = 0.7,
) -> List[DiversityResult]:
    """Select results using Maximal Marginal Relevance (MMR).

    Balances relevance to query with diversity among selected results.

    MMR = lambda * Relevance(d, q) - (1 - lambda) * max Similarity(d, d_j)
    where d_j are already selected documents.

    Args:
        query: Search query.
        candidates: List of (chunk, relevance_score) tuples.
        top_k: Number of results to select.
        lambda_param: Balance parameter (0=pure diversity, 1=pure relevance).

    Returns:
        List of DiversityResult with diversity scores.
    """
    if not candidates:
        return []

    selected: List[DiversityResult] = []
    remaining = list(candidates)

    for _ in range(min(top_k, len(remaining))):
        best_score = -float("inf")
        best_idx = 0
        best_result = None

        for idx, (chunk, relevance) in enumerate(remaining):
            # Max similarity to already selected
            max_sim = 0.0
            similar_to = []
            for sel in selected:
                sim = _content_similarity(chunk, sel.chunk)
                if sim > max_sim:
                    max_sim = sim
                if sim > 0.3:
                    similar_to.append(sel.chunk.id)

            # MMR score
            diversity = 1.0 - max_sim
            mmr_score = lambda_param * relevance - (1 - lambda_param) * max_sim

            # Penalize redundancy
            is_redundant = max_sim > 0.7
            if is_redundant:
                mmr_score *= 0.5

            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = idx
                best_result = DiversityResult(
                    chunk=chunk,
                    relevance_score=relevance,
                    diversity_score=diversity,
                    combined_score=mmr_score,
                    is_redundant=is_redundant,
                    similar_to=similar_to,
                )

        if best_result:
            selected.append(best_result)
            remaining.pop(best_idx)

    return selected


# ---------------------------------------------------------------------------
# Query-Adaptive Diversity
# ---------------------------------------------------------------------------

def adaptive_lambda(query: str, base_lambda: float = 0.7) -> float:
    """Compute query-adaptive diversity parameter.

    Adjusts the relevance-diversity balance based on query characteristics.

    - Broad/exploratory queries → lower lambda (more diversity)
    - Specific/focused queries → higher lambda (more relevance)

    Args:
        query: Search query.
        base_lambda: Base lambda parameter.

    Returns:
        Adaptive lambda value.
    """
    query_lower = query.lower()
    word_count = len(query_lower.split())

    # Start with base
    lambda_adj = base_lambda

    # Broad queries → more diversity
    broad_signals = ["all", "every", "various", "different", "types", "kinds", "examples", "list"]
    broad_count = sum(1 for s in broad_signals if s in query_lower)
    if broad_count >= 2 or word_count > 10:
        lambda_adj -= 0.15

    # Specific queries → more relevance
    specific_signals = ["specific", "exact", "particular", "precise", "the", "this", "that"]
    specific_count = sum(1 for s in specific_signals if s in query_lower)
    if specific_count >= 2 or word_count <= 4:
        lambda_adj += 0.1

    # Question words suggest need for comprehensive answer
    question_words = ["what", "how", "why", "explain", "describe"]
    if any(query_lower.startswith(w) for w in question_words):
        lambda_adj -= 0.05

    # Comparison queries need diversity
    comparison_signals = ["compare", "difference", "versus", "vs", "between"]
    if any(s in query_lower for s in comparison_signals):
        lambda_adj -= 0.1

    return max(0.1, min(0.9, lambda_adj))


# ---------------------------------------------------------------------------
# Diversity-Focused Retrieval
# ---------------------------------------------------------------------------

def diversity_retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
    prefilter_k: int = 20,
    config: Optional[DiversityConfig] = None,
) -> List[DiversityResult]:
    """Retrieve with diversity-aware selection.

    Args:
        query: Search query.
        chunks: Available document chunks.
        top_k: Number of results to return.
        prefilter_k: Number of candidates before diversity selection.
        config: Diversity configuration.

    Returns:
        List of DiversityResult sorted by combined score.
    """
    if not chunks:
        return []

    config = config or DiversityConfig()

    # Step 1: Get relevance scores using TF-IDF
    from .hybrid_search import TFIDFIndex
    tfidf = TFIDFIndex([c.content for c in chunks])
    keyword_results = tfidf.search(query, top_k=prefilter_k)

    # Build candidates
    candidates = []
    for idx, score in keyword_results:
        if idx < len(chunks):
            candidates.append((chunks[idx], score))

    if not candidates:
        # Fallback: use first chunks
        candidates = [(c, 0.5) for c in chunks[:prefilter_k]]

    # Step 2: Adaptive lambda
    lambda_param = adaptive_lambda(query, config.lambda_param)

    # Step 3: MMR selection
    results = mmr_select(query, candidates, top_k, lambda_param)

    # Step 4: Post-processing - enforce diversity constraints
    final_results = []
    similar_count: Dict[str, int] = {}

    for result in results:
        source_key = result.chunk.source
        count = similar_count.get(source_key, 0)

        if count < config.max_similar:
            final_results.append(result)
            similar_count[source_key] = count + 1
        elif len(final_results) < top_k:
            # Allow if we need more results
            result.is_redundant = True
            final_results.append(result)

    return final_results[:top_k]


# ---------------------------------------------------------------------------
# Redundancy Detection
# ---------------------------------------------------------------------------

def detect_redundancy(
    chunks: List[Chunk],
    similarity_threshold: float = 0.6,
) -> List[Tuple[str, str, float]]:
    """Detect redundant chunks in a collection.

    Args:
        chunks: List of chunks to check.
        similarity_threshold: Minimum similarity to consider redundant.

    Returns:
        List of (chunk_id_a, chunk_id_b, similarity) tuples.
    """
    redundancies = []

    for i in range(len(chunks)):
        for j in range(i + 1, len(chunks)):
            sim = _content_similarity(chunks[i], chunks[j])
            if sim >= similarity_threshold:
                redundancies.append((chunks[i].id, chunks[j].id, sim))

    return redundancies


def deduplicate_chunks(
    chunks: List[Chunk],
    similarity_threshold: float = 0.7,
) -> List[Chunk]:
    """Remove near-duplicate chunks, keeping the first occurrence.

    Args:
        chunks: List of chunks.
        similarity_threshold: Similarity threshold for deduplication.

    Returns:
        Deduplicated list of chunks.
    """
    if not chunks:
        return []

    unique = [chunks[0]]
    for chunk in chunks[1:]:
        is_duplicate = False
        for existing in unique:
            if _content_similarity(chunk, existing) >= similarity_threshold:
                is_duplicate = True
                break
        if not is_duplicate:
            unique.append(chunk)

    return unique


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def diversity_rag_pipeline(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
    lambda_param: float = 0.7,
) -> Dict[str, Any]:
    """Full diversity-focused RAG pipeline.

    Args:
        query: Search query.
        chunks: Available document chunks.
        top_k: Number of results.
        lambda_param: Relevance-diversity balance.

    Returns:
        Dict with results, diversity metrics, and metadata.
    """
    config = DiversityConfig(lambda_param=lambda_param)

    # Retrieve with diversity
    results = diversity_retrieve(query, chunks, top_k, config=config)

    # Detect redundancy in full collection
    redundancies = detect_redundancy(chunks[:50])  # Limit for performance

    # Calculate diversity metrics
    if results:
        avg_relevance = sum(r.relevance_score for r in results) / len(results)
        avg_diversity = sum(r.diversity_score for r in results) / len(results)
        redundant_count = sum(1 for r in results if r.is_redundant)
    else:
        avg_relevance = 0.0
        avg_diversity = 0.0
        redundant_count = 0

    adaptive_lam = adaptive_lambda(query, lambda_param)

    return {
        "query": query,
        "results": [
            {
                "content": r.chunk.content,
                "relevance_score": round(r.relevance_score, 4),
                "diversity_score": round(r.diversity_score, 4),
                "combined_score": round(r.combined_score, 4),
                "is_redundant": r.is_redundant,
                "similar_to": r.similar_to,
                "source": r.chunk.source,
            }
            for r in results
        ],
        "diversity_metrics": {
            "avg_relevance": round(avg_relevance, 4),
            "avg_diversity": round(avg_diversity, 4),
            "redundant_results": redundant_count,
            "adaptive_lambda": round(adaptive_lam, 4),
        },
        "redundancy_detection": {
            "total_pairs_found": len(redundancies),
            "chunk_count": len(chunks),
        },
    }
