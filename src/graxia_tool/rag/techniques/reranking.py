"""Enterprise Agent OS — Reranking Techniques.

Provides multiple reranking strategies for improving retrieval quality:
1. Cross-encoder reranking (cosine similarity between query and chunk)
2. LLM-based reranking (uses Ollama to score relevance)
3. Simple keyword overlap reranking (no external deps)

Based on reranking patterns from rag-techniques.
"""
from __future__ import annotations
import math
import re
from typing import List, Optional, Tuple

from ..chunker import Chunk
from ..retriever import RetrievalResult


TOKEN_RE = re.compile(r"[a-z0-9\u0E00-\u0E7F]+")


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) > 1]


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) + 1e-9
    norm_b = math.sqrt(sum(x * x for x in b)) + 1e-9
    return dot / (norm_a * norm_b)


def keyword_overlap_score(query: str, content: str) -> float:
    """Score based on keyword overlap between query and content.

    Simple but effective for exact-match scenarios. No external deps.
    """
    q_tokens = set(_tokenize(query))
    c_tokens = set(_tokenize(content))
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens)
    return overlap / len(q_tokens)


def semantic_rerank(
    query: str,
    query_embedding: List[float],
    chunk_embeddings: List[Tuple[Chunk, List[float]]],
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Rerank chunks using cosine similarity with query embedding.

    Args:
        query: Original search query.
        query_embedding: Embedding vector for the query.
        chunk_embeddings: List of (chunk, embedding) pairs.
        top_k: Number of results to return.

    Returns:
        List of (chunk, rerank_score) sorted by score desc.
    """
    scored = []
    for chunk, emb in chunk_embeddings:
        score = _cosine_similarity(query_embedding, emb)
        scored.append((chunk, score))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def keyword_rerank(
    query: str,
    candidates: List[Tuple[Chunk, float]],
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Rerank using keyword overlap score on top of initial scores.

    Args:
        query: Search query.
        candidates: Initial (chunk, score) pairs from retrieval.
        top_k: Number of results to return.

    Returns:
        Reranked list of (chunk, combined_score).
    """
    scored = []
    for chunk, initial_score in candidates:
        kw_score = keyword_overlap_score(query, chunk.content)
        # Blend: 70% initial + 30% keyword overlap
        combined = 0.7 * initial_score + 0.3 * kw_score
        scored.append((chunk, combined))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def cross_encoder_rerank(
    query: str,
    candidates: List[Tuple[Chunk, float]],
    embeddings: Optional[List[List[float]]] = None,
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Rerank using a lightweight cross-encoder approximation.

    Uses TF-IDF weighted cosine similarity as a proxy for a real cross-encoder.
    This provides better relevance scoring than simple keyword overlap.

    Args:
        query: Search query.
        candidates: Initial (chunk, score) pairs.
        embeddings: Optional precomputed embeddings for chunks.
        top_k: Number of results to return.

    Returns:
        Reranked list of (chunk, cross_encoder_score).
    """
    from .hybrid_search import TFIDFIndex, _tokenize

    # Build TF-IDF for candidates
    contents = [chunk.content for chunk, _ in candidates]
    tfidf = TFIDFIndex(contents)

    # Score each candidate against query
    q_tokens = _tokenize(query)
    scored = []

    for i, (chunk, initial_score) in enumerate(candidates):
        # TF-IDF score
        c_tokens = _tokenize(chunk.content)
        tfidf_score = 0.0
        for qt in q_tokens:
            if qt in tfidf.idf:
                tf = c_tokens.count(qt)
                if tf > 0:
                    dl = len(c_tokens)
                    k1, b = 1.5, 0.75
                    denom = tf + k1 * (1 - b + b * dl / max(tfidf.avgdl, 1))
                    tfidf_score += tfidf.idf[qt] * (tf * (k1 + 1)) / denom

        # Keyword overlap score
        kw_score = keyword_overlap_score(query, chunk.content)

        # Combined score: 50% TF-IDF + 30% initial + 20% keyword overlap
        max_tfidf = max(tfidf_score, 0.001)
        combined = 0.5 * (tfidf_score / max_tfidf) + 0.3 * initial_score + 0.2 * kw_score
        scored.append((chunk, combined))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


async def llm_rerank(
    query: str,
    candidates: List[Tuple[Chunk, float]],
    llm_func=None,
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Rerank using an LLM to score relevance.

    Uses Ollama (or any registered LLM) to rate document relevance on a 0-1 scale.

    Args:
        query: Search query.
        candidates: Initial (chunk, score) pairs.
        llm_func: Async callable that takes a prompt and returns text.
        top_k: Number of results to return.

    Returns:
        Reranked list of (chunk, llm_score).
    """
    if not llm_func:
        # Fallback to keyword reranking
        return keyword_rerank(query, candidates, top_k)

    scored = []
    for chunk, initial_score in candidates:
        # Truncate chunk for LLM context
        content_preview = chunk.content[:500]
        prompt = (
            f"On a scale of 0-1, how relevant is this document to the query?\n\n"
            f"Query: {query}\n\n"
            f"Document: {content_preview}\n\n"
            f"Respond with ONLY a number between 0 and 1."
        )
        try:
            response = await llm_func(prompt)
            llm_score = float(response.strip())
            llm_score = max(0.0, min(1.0, llm_score))
        except (ValueError, Exception):
            llm_score = initial_score

        scored.append((chunk, llm_score))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]
