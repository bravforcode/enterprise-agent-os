"""Enterprise Agent OS — Agentic RAG (A-RAG style) Technique.

Multi-step retrieval with query decomposition, iterative
retrieval-generation loops, query expansion, and confidence-based
stopping criteria.

Based on Agentic RAG patterns from 2025 research.
"""
from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..chunker import Chunk


@dataclass
class QueryDecomposition:
    """Decomposed sub-queries from a complex query."""
    original_query: str
    sub_queries: List[str]
    strategy: str  # "sequential", "parallel", "conditional"
    dependencies: Dict[int, List[int]]  # sub_query_idx -> depends on


@dataclass
class RetrievalStep:
    """A single step in the agentic retrieval process."""
    step_id: int
    query: str
    chunks: List[Chunk]
    scores: List[float]
    confidence: float
    reasoning: str = ""


@dataclass
class AgenticResult:
    """Result from the agentic RAG pipeline."""
    answer: str
    steps: List[RetrievalStep]
    total_retrievals: int
    final_confidence: float
    converged: bool


# ---------------------------------------------------------------------------
# Query Decomposition
# ---------------------------------------------------------------------------

def decompose_query(query: str) -> QueryDecomposition:
    """Decompose a complex query into simpler sub-queries.

    Uses pattern-based heuristics to identify multi-part questions
    and break them into atomic sub-queries.

    Args:
        query: Complex user query.

    Returns:
        QueryDecomposition with sub-queries and dependencies.
    """
    query_lower = query.lower().strip()

    # Check for multi-part questions
    conjunctions = ["and", "also", "additionally", "furthermore", "moreover", "plus"]
    parts = []
    for conj in conjunctions:
        pattern = rf"\s+{conj}\s+"
        split_parts = re.split(pattern, query_lower, maxsplit=1)
        if len(split_parts) > 1:
            parts = split_parts
            break

    # Check for comparison questions
    comparison_patterns = [
        r"(?:compare|difference between|versus|vs\.?|compared to)\s+(.+?)\s+and\s+(.+?)(?:\?|$)",
        r"(?:what are the)\s+(?:pros|advantages|disadvantages|differences)\s+(?:of|between)\s+(.+?)(?:\?|$)",
    ]
    for pattern in comparison_patterns:
        match = re.search(pattern, query_lower)
        if match:
            parts = [query_lower]
            break

    # Check for sequential/process questions
    sequential_patterns = [
        r"(?:how (?:do|does|can|should))\s+(.+?)(?:\?|$)",
        r"(?:what (?:are|is) the (?:steps|process|method))\s+(.+?)(?:\?|$)",
        r"(?:explain|describe)\s+(?:the\s+)?(?:process|steps|method)\s+(?:of\s+)?(.+?)(?:\?|$)",
    ]
    for pattern in sequential_patterns:
        match = re.search(pattern, query_lower)
        if match:
            parts = [query_lower]
            break

    # If no decomposition possible, return as-is
    if len(parts) <= 1:
        return QueryDecomposition(
            original_query=query,
            sub_queries=[query],
            strategy="sequential",
            dependencies={},
        )

    # Clean up sub-queries
    sub_queries = [p.strip().rstrip("?") + "?" for p in parts if p.strip()]

    return QueryDecomposition(
        original_query=query,
        sub_queries=sub_queries,
        strategy="parallel" if len(sub_queries) <= 3 else "sequential",
        dependencies={i: [i - 1] for i in range(1, len(sub_queries))},
    )


# ---------------------------------------------------------------------------
# Query Expansion
# ---------------------------------------------------------------------------

def expand_query(query: str, context: str = "", max_expansions: int = 3) -> List[str]:
    """Expand a query with related terms and reformulations.

    Generates alternative query formulations to improve recall.

    Args:
        query: Original query.
        context: Optional context from previous retrieval steps.
        max_expansions: Maximum number of expanded queries.

    Returns:
        List of expanded query strings (including original).
    """
    expanded = [query]
    words = query.split()
    query_lower = query.lower()

    # Strategy 1: Add synonyms/related terms
    tech_expansions = {
        "how": ["method", "approach", "technique", "process"],
        "what": ["definition", "description", "explanation"],
        "why": ["reason", "cause", "purpose", "rationale"],
        "when": ["time", "date", "when", "timing"],
        "where": ["location", "place", "where", "source"],
        "who": ["person", "author", "creator", "who"],
        "implement": ["build", "create", "develop", "code"],
        "optimize": ["improve", "enhance", "speed up", "accelerate"],
        "fix": ["resolve", "repair", "debug", "troubleshoot"],
        "error": ["bug", "issue", "problem", "failure"],
        "performance": ["speed", "latency", "throughput", "efficiency"],
        "security": ["safety", "protection", "authentication", "authorization"],
    }

    expansion_terms = []
    for word in words:
        lower = word.lower()
        if lower in tech_expansions:
            expansion_terms.extend(tech_expansions[lower][:2])

    if expansion_terms:
        # Create expanded query with additional terms
        extra_terms = " ".join(expansion_terms[:max_expansions])
        expanded.append(f"{query} {extra_terms}")

    # Strategy 2: Rephrase as different question types
    if query_lower.startswith("what is"):
        topic = query_lower.replace("what is", "").strip().rstrip("?")
        expanded.append(f"Explain {topic}")
        expanded.append(f"Define {topic}")
    elif query_lower.startswith("how to"):
        action = query_lower.replace("how to", "").strip().rstrip("?")
        expanded.append(f"What is the process for {action}")
        expanded.append(f"Steps to {action}")

    # Strategy 3: Add context-based expansion
    if context:
        context_tokens = set(_tokenize(context))
        query_tokens = set(_tokenize(query))
        new_terms = context_tokens - query_tokens
        if new_terms:
            extra = " ".join(list(new_terms)[:3])
            expanded.append(f"{query} {extra}")

    return expanded[:max_expansions + 1]


# ---------------------------------------------------------------------------
# Confidence Assessment
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in re.findall(r"[a-z0-9\u0E00-\u0E7F]+", text.lower()) if len(t) > 1]


def assess_step_confidence(
    query: str,
    chunks: List[Chunk],
    scores: List[float],
    previous_chunks: Optional[List[Chunk]] = None,
) -> float:
    """Assess confidence of a retrieval step.

    Args:
        query: Query used for this step.
        chunks: Retrieved chunks.
        scores: Retrieval scores.
        previous_chunks: Chunks from previous steps (for diversity check).

    Returns:
        Confidence score between 0 and 1.
    """
    if not chunks or not scores:
        return 0.0

    q_tokens = set(_tokenize(query))

    # Signal 1: Average relevance
    avg_score = sum(scores) / len(scores)

    # Signal 2: Top result quality
    top_score = max(scores)

    # Signal 3: Query coverage
    all_content = " ".join(c.content for c in chunks)
    c_tokens = set(_tokenize(all_content))
    coverage = len(q_tokens & c_tokens) / max(len(q_tokens), 1)

    # Signal 4: Diversity (if previous chunks available)
    diversity = 1.0
    if previous_chunks:
        prev_ids = {c.id for c in previous_chunks}
        new_chunks = [c for c in chunks if c.id not in prev_ids]
        diversity = len(new_chunks) / max(len(chunks), 1)

    # Signal 5: Score consistency
    if len(scores) > 1:
        variance = sum((s - avg_score) ** 2 for s in scores) / len(scores)
        consistency = 1.0 - min(math.sqrt(variance), 1.0)
    else:
        consistency = 0.5

    confidence = (
        0.30 * avg_score +
        0.25 * top_score +
        0.25 * coverage +
        0.10 * diversity +
        0.10 * consistency
    )

    return min(max(confidence, 0.0), 1.0)


def should_stop(
    steps: List[RetrievalStep],
    confidence_threshold: float = 0.7,
    max_steps: int = 5,
    min_improvement: float = 0.05,
) -> Tuple[bool, str]:
    """Decide whether to stop the agentic retrieval loop.

    Args:
        steps: History of retrieval steps.
        confidence_threshold: Target confidence to stop.
        max_steps: Maximum allowed steps.
        min_improvement: Minimum improvement between steps to continue.

    Returns:
        Tuple of (should_stop, reason).
    """
    if not steps:
        return False, "No steps completed"

    # Stop if max steps reached
    if len(steps) >= max_steps:
        return True, f"Max steps ({max_steps}) reached"

    # Stop if confidence threshold met
    latest = steps[-1]
    if latest.confidence >= confidence_threshold:
        return True, f"Confidence {latest.confidence:.2f} >= {confidence_threshold}"

    # Stop if no improvement
    if len(steps) >= 2:
        prev_confidence = steps[-2].confidence
        improvement = latest.confidence - prev_confidence
        if improvement < min_improvement:
            return True, f"Insufficient improvement ({improvement:.4f} < {min_improvement})"

    # Stop if confidence is declining
    if len(steps) >= 2 and latest.confidence < steps[-2].confidence:
        return True, "Confidence declining"

    return False, "继续 (continue)"


# ---------------------------------------------------------------------------
# Agentic RAG Pipeline
# ---------------------------------------------------------------------------

def agentic_retrieve(
    query: str,
    chunks: List[Chunk],
    retrieve_func: Callable[[str, List[Chunk], int], List[Tuple[Chunk, float]]],
    generate_func: Optional[Callable[[str, str], str]] = None,
    top_k: int = 5,
    max_steps: int = 3,
    confidence_threshold: float = 0.7,
) -> AgenticResult:
    """Run the agentic RAG pipeline with multi-step retrieval.

    Args:
        query: User query.
        chunks: Available document chunks.
        retrieve_func: Function(query, chunks, top_k) -> List[(chunk, score)].
        generate_func: Optional function(query, context) -> answer.
        top_k: Number of results per step.
        max_steps: Maximum retrieval steps.
        confidence_threshold: Target confidence.

    Returns:
        AgenticResult with answer, steps, and metadata.
    """
    # Decompose query
    decomposition = decompose_query(query)

    steps: List[RetrievalStep] = []
    all_retrieved_chunks: List[Chunk] = []
    all_retrieved_scores: List[float] = []

    # Process sub-queries
    for sub_idx, sub_query in enumerate(decomposition.sub_queries):
        if len(steps) >= max_steps:
            break

        # Expand query
        expanded_queries = expand_query(sub_query)

        # Retrieve for each expansion
        sub_chunks = []
        sub_scores = []
        for exp_query in expanded_queries:
            try:
                results = retrieve_func(exp_query, chunks, top_k)
                for chunk, score in results:
                    if chunk.id not in {c.id for c in sub_chunks}:
                        sub_chunks.append(chunk)
                        sub_scores.append(score)
            except Exception:
                continue

        # Take top-k
        if sub_scores:
            paired = sorted(zip(sub_chunks, sub_scores), key=lambda x: -x[1])
            sub_chunks = [c for c, _ in paired[:top_k]]
            sub_scores = [s for _, s in paired[:top_k]]

        # Assess confidence
        confidence = assess_step_confidence(
            sub_query, sub_chunks, sub_scores, all_retrieved_chunks
        )

        step = RetrievalStep(
            step_id=len(steps),
            query=sub_query,
            chunks=sub_chunks,
            scores=sub_scores,
            confidence=confidence,
            reasoning=f"Sub-query {sub_idx + 1}/{len(decomposition.sub_queries)}",
        )
        steps.append(step)

        all_retrieved_chunks.extend(sub_chunks)
        all_retrieved_scores.extend(sub_scores)

        # Check stopping criteria
        stop, reason = should_stop(steps, confidence_threshold, max_steps)
        if stop:
            break

    # Generate answer
    if generate_func and all_retrieved_chunks:
        context = "\n\n".join(c.content for c in all_retrieved_chunks[:top_k * 2])
        answer = generate_func(query, context)
    elif all_retrieved_chunks:
        # Heuristic answer
        answer = all_retrieved_chunks[0].content[:500]
    else:
        answer = f"No relevant information found for: {query}"

    # Calculate final confidence
    if steps:
        final_confidence = steps[-1].confidence
    else:
        final_confidence = 0.0

    return AgenticResult(
        answer=answer,
        steps=steps,
        total_retrievals=len(all_retrieved_chunks),
        final_confidence=final_confidence,
        converged=final_confidence >= confidence_threshold,
    )


def agentic_rag_pipeline(
    query: str,
    chunks: List[Chunk],
    retrieve_func: Optional[Callable[[str, List[Chunk], int], List[Tuple[Chunk, float]]]] = None,
    generate_func: Optional[Callable[[str, str], str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """High-level agentic RAG pipeline.

    Args:
        query: User query.
        chunks: Available document chunks.
        retrieve_func: Optional retrieval function (uses TF-IDF fallback).
        generate_func: Optional generation function.
        top_k: Number of results.

    Returns:
        Dict with answer, steps, and pipeline metadata.
    """
    # Default retrieve function using TF-IDF
    if retrieve_func is None:
        from .hybrid_search import TFIDFIndex, _tokenize

        def default_retrieve(q: str, cs: List[Chunk], k: int) -> List[Tuple[Chunk, float]]:
            tfidf = TFIDFIndex([c.content for c in cs])
            results = tfidf.search(q, top_k=k)
            return [(cs[idx], score) for idx, score in results if idx < len(cs)]

        retrieve_func = default_retrieve

    result = agentic_retrieve(
        query, chunks, retrieve_func, generate_func, top_k,
    )

    return {
        "query": query,
        "answer": result.answer,
        "steps": [
            {
                "step_id": s.step_id,
                "query": s.query,
                "chunks_retrieved": len(s.chunks),
                "confidence": round(s.confidence, 4),
                "reasoning": s.reasoning,
            }
            for s in result.steps
        ],
        "total_retrievals": result.total_retrievals,
        "final_confidence": round(result.final_confidence, 4),
        "converged": result.converged,
    }
