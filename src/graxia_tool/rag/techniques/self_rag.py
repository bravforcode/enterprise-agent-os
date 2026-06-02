"""Enterprise Agent OS — Self-RAG (Self-Reflective RAG) Technique.

Implements self-reflective retrieval with reflection tokens:
[IsRelevant], [IsSupported], [IsUseful] for adaptive retrieval
and self-critique loops.

Based on Self-RAG (Asai et al., 2023-2024) and follow-up work.
"""
from __future__ import annotations
import re
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..chunker import Chunk


@dataclass
class ReflectionTokens:
    """Reflection tokens indicating retrieval quality."""
    is_relevant: bool = False
    is_supported: bool = False
    is_useful: bool = False
    relevance_score: float = 0.0
    support_score: float = 0.0
    usefulness_score: float = 0.0
    reasoning: str = ""


@dataclass
class SelfRAGResult:
    """Result from Self-RAG pipeline."""
    answer: str
    reflection: ReflectionTokens
    retrieved_chunks: List[Chunk]
    iteration: int
    should_retrieve: bool
    final_score: float


def should_retrieve(
    query: str,
    query_embedding: Optional[List[float]] = None,
    threshold: float = 0.3,
) -> Tuple[bool, float]:
    """Decide whether retrieval is necessary for this query.

    Uses heuristic signals to determine if the query needs external context.

    Args:
        query: The user query.
        query_embedding: Optional embedding for semantic analysis.
        threshold: Confidence threshold for retrieval decision.

    Returns:
        Tuple of (should_retrieve, confidence_score).
    """
    query_lower = query.lower().strip()
    confidence = 0.0
    signals = 0

    # Signal 1: Question words suggest need for information
    question_words = ["what", "how", "why", "when", "where", "who", "which", "describe", "explain"]
    if any(query_lower.startswith(w) for w in question_words):
        confidence += 0.3
        signals += 1

    # Signal 2: Specific terminology suggests factual query
    specific_patterns = [
        r"\b\d{4}\b",  # Years
        r"\b\d+%\b",   # Percentages
        r"\b[A-Z]{2,}\b",  # Acronyms
    ]
    for pattern in specific_patterns:
        if re.search(pattern, query):
            confidence += 0.15
            signals += 1

    # Signal 3: Length suggests complexity
    word_count = len(query_lower.split())
    if word_count > 8:
        confidence += 0.2
        signals += 1
    elif word_count > 4:
        confidence += 0.1
        signals += 1

    # Signal 4: Negation or comparison suggests need for context
    negation_patterns = ["not", "never", "unlike", "compared", "difference", "versus"]
    if any(w in query_lower for w in negation_patterns):
        confidence += 0.2
        signals += 1

    # Signal 5: Technical/complex terms
    technical_indicators = [
        "algorithm", "methodology", "implementation", "architecture",
        "framework", "paradigm", "mechanism", "protocol", "specification",
    ]
    if any(w in query_lower for w in technical_indicators):
        confidence += 0.15
        signals += 1

    # High confidence if multiple signals
    if signals >= 3:
        confidence = min(confidence, 1.0)
    else:
        confidence = min(confidence, 0.8)

    return confidence >= threshold, confidence


def assess_relevance(
    query: str,
    chunk: Chunk,
) -> Tuple[bool, float]:
    """Assess whether a retrieved chunk is relevant to the query.

    Implements [IsRelevant] reflection token.

    Args:
        query: Original query.
        chunk: Retrieved chunk.

    Returns:
        Tuple of (is_relevant, relevance_score).
    """
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(chunk.content))

    if not q_tokens:
        return False, 0.0

    # Jaccard overlap
    intersection = q_tokens & c_tokens
    union = q_tokens | c_tokens
    jaccard = len(intersection) / max(len(union), 1)

    # Term coverage: what fraction of query terms appear in chunk
    coverage = len(intersection) / len(q_tokens)

    # Position weight: terms appearing early in chunk are more important
    early_content = chunk.content[:200].lower()
    early_matches = sum(1 for t in q_tokens if t in early_content)
    position_bonus = early_matches / max(len(q_tokens), 1) * 0.2

    score = 0.4 * jaccard + 0.4 * coverage + position_bonus
    is_relevant = score >= 0.3

    return is_relevant, min(score, 1.0)


def assess_support(
    claim: str,
    evidence_chunks: List[Chunk],
    min_support_ratio: float = 0.3,
) -> Tuple[bool, float, str]:
    """Assess whether the evidence supports the generated claim.

    Implements [IsSupported] reflection token.

    Args:
        claim: The generated claim/answer.
        evidence_chunks: Chunks used as evidence.
        min_support_ratio: Minimum ratio of claim terms supported.

    Returns:
        Tuple of (is_supported, support_score, reasoning).
    """
    claim_tokens = set(_tokenize(claim))
    if not claim_tokens:
        return True, 1.0, "Empty claim"

    # Collect all evidence tokens
    evidence_tokens = set()
    for chunk in evidence_chunks:
        evidence_tokens.update(_tokenize(chunk.content))

    # Check support for each claim term
    supported = claim_tokens & evidence_tokens
    unsupported = claim_tokens - evidence_tokens
    support_ratio = len(supported) / len(claim_tokens)

    # Partial matches (substring)
    partial_support = 0
    for term in unsupported:
        for ev_token in evidence_tokens:
            if len(term) > 3 and (term in ev_token or ev_token in term):
                partial_support += 1
                break

    adjusted_ratio = (len(supported) + partial_support * 0.5) / len(claim_tokens)
    is_supported = adjusted_ratio >= min_support_ratio

    reasoning = f"Supported: {len(supported)}/{len(claim_tokens)} terms ({support_ratio:.1%})"
    if partial_support:
        reasoning += f", partial: {partial_support}"

    return is_supported, min(adjusted_ratio, 1.0), reasoning


def assess_usefulness(
    query: str,
    answer: str,
    reflection: ReflectionTokens,
) -> Tuple[bool, float]:
    """Assess whether the generated answer is useful for the query.

    Implements [IsUseful] reflection token.

    Args:
        query: Original query.
        answer: Generated answer.
        reflection: Current reflection state.

    Returns:
        Tuple of (is_useful, usefulness_score).
    """
    if not answer.strip():
        return False, 0.0

    # Length appropriateness
    answer_words = len(answer.split())
    length_score = 1.0
    if answer_words < 5:
        length_score = 0.3
    elif answer_words > 200:
        length_score = 0.7

    # Specificity: proper nouns, numbers, technical terms suggest useful answer
    specificity_patterns = [
        r"\b[A-Z][a-z]+\b",  # Proper nouns
        r"\b\d+\.?\d*\b",     # Numbers
        r"\b\w+\.\w+\b",      # Dotted terms (e.g., file.ext)
    ]
    specificity = 0.0
    for pattern in specificity_patterns:
        matches = re.findall(pattern, answer)
        specificity += min(len(matches) * 0.1, 0.3)

    # Grounding: answer should be grounded in retrieved evidence
    grounding = 0.0
    if reflection.is_supported:
        grounding = reflection.support_score
    elif reflection.is_relevant:
        grounding = reflection.relevance_score * 0.5

    # Combined usefulness
    score = 0.3 * length_score + 0.3 * specificity + 0.4 * grounding
    is_useful = score >= 0.4 and reflection.is_relevant

    return is_useful, min(score, 1.0)


def self_critique(
    query: str,
    answer: str,
    chunks: List[Chunk],
    max_revisions: int = 2,
) -> Tuple[str, ReflectionTokens, int]:
    """Self-critique loop: evaluate and refine the answer.

    Args:
        query: Original query.
        answer: Initial generated answer.
        chunks: Retrieved chunks used.
        max_revisions: Maximum revision attempts.

    Returns:
        Tuple of (final_answer, reflection, revision_count).
    """
    current_answer = answer
    revision_count = 0

    for revision in range(max_revisions + 1):
        # Assess all reflection dimensions
        is_rel, rel_score = assess_relevance(query, chunks[0] if chunks else Chunk(
            id="", doc_id="", content="", index=0,
            start_char=0, end_char=0, doc_type="", source="",
        ))
        is_sup, sup_score, sup_reasoning = assess_support(current_answer, chunks)
        is_use, use_score = assess_usefulness(query, current_answer, ReflectionTokens(
            is_relevant=is_rel,
            relevance_score=rel_score,
            is_supported=is_sup,
            support_score=sup_score,
        ))

        reflection = ReflectionTokens(
            is_relevant=is_rel,
            is_supported=is_sup,
            is_useful=is_use,
            relevance_score=rel_score,
            support_score=sup_score,
            usefulness_score=use_score,
            reasoning=sup_reasoning,
        )

        # If all good, we're done
        if is_rel and is_sup and is_use:
            return current_answer, reflection, revision_count

        # Need revision
        if revision < max_revisions:
            # Generate revision instructions
            issues = []
            if not is_rel:
                issues.append("The answer may not directly address the query")
            if not is_sup:
                issues.append("Some claims lack sufficient evidence from retrieved chunks")
            if not is_use:
                issues.append("The answer could be more specific or detailed")

            # Simple revision: append clarification based on issues
            revision_note = "\n\n[Self-critique: " + "; ".join(issues) + ". Consider revising.]"
            current_answer = current_answer + revision_note
            revision_count += 1

    return current_answer, reflection, revision_count


def iterative_self_rag(
    query: str,
    chunks: List[Chunk],
    generate_func: Callable[[str, str], str],
    top_k: int = 5,
    max_iterations: int = 3,
    relevance_threshold: float = 0.3,
) -> SelfRAGResult:
    """Run the full Self-RAG iterative pipeline.

    Args:
        query: User query.
        chunks: Available chunks for retrieval.
        generate_func: Function that takes (query, context) and returns an answer.
        top_k: Number of chunks to retrieve.
        max_iterations: Maximum retrieval-generation cycles.
        relevance_threshold: Threshold for retrieval relevance check.

    Returns:
        SelfRAGResult with answer, reflection, and metadata.
    """
    # Step 1: Decide whether to retrieve
    should_ret, retrieval_confidence = should_retrieve(query)

    if not should_ret:
        # Generate without retrieval
        context = ""
        answer = generate_func(query, context)
        return SelfRAGResult(
            answer=answer,
            reflection=ReflectionTokens(
                is_relevant=True,
                is_supported=True,
                is_useful=True,
                relevance_score=1.0,
                support_score=1.0,
                usefulness_score=1.0,
                reasoning="No retrieval needed",
            ),
            retrieved_chunks=[],
            iteration=0,
            should_retrieve=False,
            final_score=retrieval_confidence,
        )

    # Step 2: Iterative retrieval-generation loop
    retrieved_chunks = chunks[:top_k]  # Simplified: take top-k
    best_answer = ""
    best_reflection = ReflectionTokens()
    best_score = 0.0

    for iteration in range(max_iterations):
        # Generate answer with current context
        context = "\n\n".join(c.content for c in retrieved_chunks)
        answer = generate_func(query, context)

        # Self-critique
        final_answer, reflection, _ = self_critique(query, answer, retrieved_chunks)

        # Calculate overall score
        overall_score = (
            0.3 * reflection.relevance_score +
            0.4 * reflection.support_score +
            0.3 * reflection.usefulness_score
        )

        if overall_score > best_score:
            best_answer = final_answer
            best_reflection = reflection
            best_score = overall_score

        # If quality is sufficient, stop early
        if reflection.is_relevant and reflection.is_supported and reflection.is_useful:
            break

        # Re-rank chunks based on reflection (simulate retrieval refinement)
        # In practice, this would re-query with expanded terms
        retrieved_chunks = retrieved_chunks[:max(1, len(retrieved_chunks) - 1)]

    return SelfRAGResult(
        answer=best_answer,
        reflection=best_reflection,
        retrieved_chunks=retrieved_chunks,
        iteration=iteration + 1,
        should_retrieve=True,
        final_score=best_score,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TOKEN_RE = re.compile(r"[a-z0-9\u0E00-\u0E7F]+")


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) > 1]


def self_rag_pipeline(
    query: str,
    chunks: List[Chunk],
    generate_func: Optional[Callable[[str, str], str]] = None,
    top_k: int = 5,
) -> Dict[str, Any]:
    """High-level Self-RAG pipeline.

    Args:
        query: User query.
        chunks: Available document chunks.
        generate_func: Optional generation function (query, context) -> answer.
        top_k: Number of chunks to use.

    Returns:
        Dict with answer, reflection tokens, and pipeline metadata.
    """
    # Decide whether to retrieve
    should_ret, confidence = should_retrieve(query)

    # Retrieve relevant chunks
    retrieved = chunks[:top_k] if should_ret else []

    # Simple generation fallback if no generate_func provided
    if generate_func:
        context = "\n\n".join(c.content for c in retrieved)
        answer = generate_func(query, context)
    else:
        # Heuristic answer from retrieved content
        if retrieved:
            answer = retrieved[0].content[:500]
        else:
            answer = f"Based on available information regarding: {query}"

    # Self-critique
    final_answer, reflection, revisions = self_critique(query, answer, retrieved)

    return {
        "query": query,
        "answer": final_answer,
        "reflection": {
            "is_relevant": reflection.is_relevant,
            "is_supported": reflection.is_supported,
            "is_useful": reflection.is_useful,
            "relevance_score": round(reflection.relevance_score, 4),
            "support_score": round(reflection.support_score, 4),
            "usefulness_score": round(reflection.usefulness_score, 4),
            "reasoning": reflection.reasoning,
        },
        "should_retrieve": should_ret,
        "retrieval_confidence": round(confidence, 4),
        "retrieved_chunks": len(retrieved),
        "revisions": revisions,
    }
