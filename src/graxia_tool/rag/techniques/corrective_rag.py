"""Enterprise Agent OS — Corrective RAG (CRAG) Technique.

Assesses retrieval confidence, refines knowledge by extracting key info
and filtering noise, with web search fallback for incorrect retrieval.

Based on Corrective RAG (Yan et al., 2024-2025) patterns.
"""
from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..chunker import Chunk


@dataclass
class RetrievalAssessment:
    """Assessment of retrieval quality."""
    confidence: str  # "correct", "ambiguous", "incorrect"
    score: float  # 0.0 - 1.0
    reasoning: str = ""


@dataclass
class RefinedKnowledge:
    """Refined knowledge extracted from retrieved chunks."""
    key_facts: List[str]
    filtered_chunks: List[Chunk]
    noise_removed: float  # fraction of noise removed
    confidence: float


@dataclass
class CRAGResult:
    """Result from the CRAG pipeline."""
    answer: str
    assessment: RetrievalAssessment
    refined_knowledge: RefinedKnowledge
    used_web_fallback: bool
    final_score: float


# ---------------------------------------------------------------------------
# Retrieval Assessment
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in re.findall(r"[a-z0-9\u0E00-\u0E7F]+", text.lower()) if len(t) > 1]


def assess_retrieval(
    query: str,
    chunks: List[Chunk],
    correct_threshold: float = 0.5,
    ambiguous_threshold: float = 0.2,
) -> RetrievalAssessment:
    """Assess the confidence level of retrieved results.

    Classifies retrieval as:
    - correct: high confidence, results are relevant
    - ambiguous: medium confidence, some relevant info exists
    - incorrect: low confidence, results are not useful

    Args:
        query: Original search query.
        chunks: Retrieved chunks.
        correct_threshold: Minimum score for "correct" classification.
        ambiguous_threshold: Minimum score for "ambiguous" classification.

    Returns:
        RetrievalAssessment with confidence level and score.
    """
    if not chunks:
        return RetrievalAssessment(
            confidence="incorrect",
            score=0.0,
            reasoning="No chunks retrieved",
        )

    q_tokens = set(_tokenize(query))

    # Calculate aggregate relevance scores
    relevance_scores = []
    keyword_scores = []
    length_scores = []

    for chunk in chunks:
        c_tokens = set(_tokenize(chunk.content))

        # Semantic relevance (keyword overlap)
        if q_tokens:
            overlap = len(q_tokens & c_tokens)
            relevance = overlap / len(q_tokens)
        else:
            relevance = 0.0
        relevance_scores.append(relevance)

        # Keyword density in chunk
        chunk_text = chunk.content.lower()
        kw_hits = sum(1 for qt in q_tokens if qt in chunk_text)
        kw_density = kw_hits / max(len(q_tokens), 1)
        keyword_scores.append(kw_density)

        # Length appropriateness (not too short, not too long)
        words = len(chunk.content.split())
        if words < 10:
            length_scores.append(0.2)
        elif words > 500:
            length_scores.append(0.6)
        else:
            length_scores.append(0.9)

    # Aggregate metrics
    avg_relevance = sum(relevance_scores) / len(relevance_scores)
    max_relevance = max(relevance_scores)
    avg_keyword = sum(keyword_scores) / len(keyword_scores)
    avg_length = sum(length_scores) / len(length_scores)

    # Consistency: how similar are the scores across chunks
    if len(relevance_scores) > 1:
        variance = sum((s - avg_relevance) ** 2 for s in relevance_scores) / len(relevance_scores)
        consistency = 1.0 - min(math.sqrt(variance) * 2, 1.0)
    else:
        consistency = 1.0

    # Combined score
    combined = (
        0.35 * avg_relevance +
        0.25 * max_relevance +
        0.20 * avg_keyword +
        0.10 * avg_length +
        0.10 * consistency
    )

    # Classify
    if combined >= correct_threshold:
        confidence = "correct"
        reasoning = f"High relevance (avg={avg_relevance:.2f}, max={max_relevance:.2f})"
    elif combined >= ambiguous_threshold:
        confidence = "ambiguous"
        reasoning = f"Moderate relevance (avg={avg_relevance:.2f}, consistency={consistency:.2f})"
    else:
        confidence = "incorrect"
        reasoning = f"Low relevance (avg={avg_relevance:.2f}, kw_density={avg_keyword:.2f})"

    return RetrievalAssessment(
        confidence=confidence,
        score=combined,
        reasoning=reasoning,
    )


# ---------------------------------------------------------------------------
# Knowledge Refinement
# ---------------------------------------------------------------------------

def _extract_key_facts(text: str, max_facts: int = 5) -> List[str]:
    """Extract key factual statements from text.

    Uses sentence-level heuristics to identify factual content.

    Args:
        text: Source text.
        max_facts: Maximum facts to extract.

    Returns:
        List of key fact strings.
    """
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]

    if not sentences:
        return [text[:200]] if text else []

    # Score sentences for factual content
    scored = []
    for sent in sentences:
        score = 0.0
        lower = sent.lower()

        # Factual signals
        factual_patterns = [
            r"\b\d+\.?\d*\b",       # Numbers
            r"\bis defined as\b",    # Definitions
            r"\brefers to\b",        # References
            r"\baccording to\b",     # Citations
            r"\bresults in\b",       # Causal
            r"\bconsists of\b",      # Compositional
            r"\bprovides\b",         # Functional
        ]
        for pattern in factual_patterns:
            if re.search(pattern, lower):
                score += 0.2

        # Penalize hedging/noise
        noise_patterns = [
            r"\bmaybe\b", r"\bperhaps\b", r"\bmight\b",
            r"\bI think\b", r"\bin my opinion\b",
            r"\betc\b", r"\bfor example\b",
        ]
        for pattern in noise_patterns:
            if re.search(pattern, lower):
                score -= 0.15

        # Length bonus (medium-length sentences are most informative)
        words = len(sent.split())
        if 10 <= words <= 40:
            score += 0.1

        scored.append((sent, max(score, 0.0)))

    # Sort by score and take top facts
    scored.sort(key=lambda x: -x[1])
    return [sent for sent, _ in scored[:max_facts]]


def refine_knowledge(
    chunks: List[Chunk],
    query: str,
    noise_filter_threshold: float = 0.3,
) -> RefinedKnowledge:
    """Refine retrieved knowledge by extracting key info and filtering noise.

    Args:
        chunks: Retrieved chunks to refine.
        query: Original query for relevance filtering.
        noise_filter_threshold: Minimum relevance for a chunk to be kept.

    Returns:
        RefinedKnowledge with extracted facts and filtered chunks.
    """
    if not chunks:
        return RefinedKnowledge(
            key_facts=[],
            filtered_chunks=[],
            noise_removed=1.0,
            confidence=0.0,
        )

    q_tokens = set(_tokenize(query))

    # Filter chunks by relevance
    scored_chunks = []
    for chunk in chunks:
        c_tokens = set(_tokenize(chunk.content))
        if q_tokens:
            overlap = len(q_tokens & c_tokens) / len(q_tokens)
        else:
            overlap = 0.5
        scored_chunks.append((chunk, overlap))

    # Sort by relevance and filter noise
    scored_chunks.sort(key=lambda x: -x[1])
    total = len(scored_chunks)
    kept_threshold = max(1, int(total * (1 - noise_filter_threshold)))

    filtered_chunks = [c for c, s in scored_chunks[:kept_threshold]]
    noise_removed = 1.0 - (len(filtered_chunks) / max(total, 1))

    # Extract key facts from filtered chunks
    all_text = "\n".join(c.content for c in filtered_chunks)
    key_facts = _extract_key_facts(all_text)

    # Confidence based on average relevance
    avg_score = sum(s for _, s in scored_chunks[:kept_threshold]) / max(kept_threshold, 1)

    return RefinedKnowledge(
        key_facts=key_facts,
        filtered_chunks=filtered_chunks,
        noise_removed=noise_removed,
        confidence=avg_score,
    )


# ---------------------------------------------------------------------------
# Web Search Fallback
# ---------------------------------------------------------------------------

def web_search_fallback(
    query: str,
    llm_func: Optional[Callable[[str], str]] = None,
) -> str:
    """Simulate web search fallback for incorrect retrieval.

    In production, this would call a search API. Here we provide
    a template for integration.

    Args:
        query: The search query.
        llm_func: Optional LLM function for generating search results.

    Returns:
        Search result text (simulated).
    """
    # Placeholder: in production, integrate with search API
    # This demonstrates the interface for web search fallback
    if llm_func:
        prompt = (
            f"Search the web for information about: {query}\n"
            f"Provide a factual summary based on search results."
        )
        return llm_func(prompt)

    return f"[Web search placeholder for: {query}]"


# ---------------------------------------------------------------------------
# CRAG Pipeline
# ---------------------------------------------------------------------------

def correct_knowledge(
    query: str,
    chunks: List[Chunk],
    generate_func: Optional[Callable[[str, str], str]] = None,
    llm_func: Optional[Callable[[str], str]] = None,
    top_k: int = 5,
    use_web_fallback: bool = True,
) -> CRAGResult:
    """Run the full Corrective RAG pipeline.

    Pipeline:
    1. Assess retrieval confidence
    2. If correct: refine knowledge, generate answer
    3. If ambiguous: refine with caution, generate with caveats
    4. If incorrect: fallback to web search, combine results

    Args:
        query: User query.
        chunks: Retrieved chunks.
        generate_func: Function(query, context) -> answer.
        llm_func: Optional LLM for web fallback.
        top_k: Number of chunks to process.
        use_web_fallback: Whether to use web search for incorrect retrieval.

    Returns:
        CRAGResult with answer, assessment, and refined knowledge.
    """
    # Step 1: Assess retrieval
    assessment = assess_retrieval(query, chunks[:top_k])

    # Step 2: Refine knowledge
    refined = refine_knowledge(chunks[:top_k], query)

    # Step 3: Generate based on assessment
    used_web = False
    web_results = ""

    if assessment.confidence == "correct":
        # High confidence: use refined knowledge directly
        context = "\n\n".join(c.content for c in refined.filtered_chunks)
        context += "\n\nKey facts: " + "; ".join(refined.key_facts)

    elif assessment.confidence == "ambiguous":
        # Medium confidence: use with caveats
        context = "\n\n".join(c.content for c in refined.filtered_chunks)
        context += "\n\nNote: Information may be incomplete. Key facts: " + "; ".join(refined.key_facts)

    else:
        # Low confidence: web fallback
        if use_web_fallback:
            web_results = web_search_fallback(query, llm_func)
            used_web = True
            # Combine: use refined chunks + web results
            refined_context = "\n\n".join(c.content for c in refined.filtered_chunks)
            context = f"[Refined from limited retrieval]\n{refined_context}\n\n[Web search results]\n{web_results}"
        else:
            context = "\n\n".join(c.content for c in refined.filtered_chunks)

    # Generate answer
    if generate_func:
        answer = generate_func(query, context)
    else:
        # Heuristic: use key facts and first chunk
        if refined.key_facts:
            answer = ". ".join(refined.key_facts[:3]) + "."
        elif refined.filtered_chunks:
            answer = refined.filtered_chunks[0].content[:500]
        else:
            answer = f"Insufficient information found for: {query}"

    # Calculate final score
    final_score = assessment.score
    if used_web:
        final_score = max(final_score, 0.5)  # Boost for web fallback

    return CRAGResult(
        answer=answer,
        assessment=assessment,
        refined_knowledge=refined,
        used_web_fallback=used_web,
        final_score=final_score,
    )


def crag_pipeline(
    query: str,
    chunks: List[Chunk],
    generate_func: Optional[Callable[[str, str], str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """High-level CRAG pipeline returning a dict result.

    Args:
        query: User query.
        chunks: Retrieved chunks.
        generate_func: Optional generation function.
        top_k: Number of chunks to process.

    Returns:
        Dict with answer, assessment, refined knowledge, and metadata.
    """
    result = correct_knowledge(
        query, chunks, generate_func=generate_func, top_k=top_k,
    )

    return {
        "query": query,
        "answer": result.answer,
        "assessment": {
            "confidence": result.assessment.confidence,
            "score": round(result.assessment.score, 4),
            "reasoning": result.assessment.reasoning,
        },
        "refined_knowledge": {
            "key_facts": result.refined_knowledge.key_facts,
            "chunks_kept": len(result.refined_knowledge.filtered_chunks),
            "noise_removed": round(result.refined_knowledge.noise_removed, 4),
            "confidence": round(result.refined_knowledge.confidence, 4),
        },
        "used_web_fallback": result.used_web_fallback,
        "final_score": round(result.final_score, 4),
    }
