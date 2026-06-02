"""Enterprise Agent OS — Hybrid Search Technique.

Combines keyword-based (BM25/TF-IDF) and semantic (vector) search using
Reciprocal Rank Fusion (RRF) for robust retrieval.

Based on fusion_retrieval pattern from rag-techniques.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from ..chunker import Chunk
from ..retriever import RetrievalResult


TOKEN_RE = re.compile(r"[a-z0-9\u0E00-\u0E7F]+")


def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in TOKEN_RE.findall(text.lower()) if len(t) > 1]


class TFIDFIndex:
    """Lightweight TF-IDF index for keyword search without external deps."""

    def __init__(self, documents: List[str]):
        self.documents = documents
        self.N = len(documents)
        self.doc_tokens: List[List[str]] = [_tokenize(d) for d in documents]
        self.avgdl = sum(len(t) for t in self.doc_tokens) / max(self.N, 1)

        # Build document frequency
        self.df: Dict[str, int] = defaultdict(int)
        for tokens in self.doc_tokens:
            for t in set(tokens):
                self.df[t] += 1

        # Precompute IDF
        self.idf: Dict[str, float] = {}
        for term, freq in self.df.items():
            self.idf[term] = math.log((self.N - freq + 0.5) / (freq + 0.5) + 1)

    def search(self, query: str, top_k: int = 20) -> List[Tuple[int, float]]:
        """Search using BM25 scoring. Returns list of (doc_index, score)."""
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        scores = [0.0] * self.N
        k1, b = 1.5, 0.75

        for q in q_tokens:
            if q not in self.idf:
                continue
            idf = self.idf[q]
            for i, doc_tokens in enumerate(self.doc_tokens):
                tf = doc_tokens.count(q)
                if tf == 0:
                    continue
                dl = len(doc_tokens)
                denom = tf + k1 * (1 - b + b * dl / max(self.avgdl, 1))
                scores[i] += idf * (tf * (k1 + 1)) / denom

        ranked = sorted(range(self.N), key=lambda i: -scores[i])
        return [(i, scores[i]) for i in ranked[:top_k] if scores[i] > 0]


class VectorIndex:
    """In-memory vector index using brute-force cosine similarity."""

    def __init__(self, embeddings: List[List[float]], chunk_ids: List[str]):
        self.embeddings = embeddings
        self.chunk_ids = chunk_ids
        self.N = len(embeddings)

    def search(
        self, query_embedding: List[float], top_k: int = 20
    ) -> List[Tuple[int, float]]:
        """Search using cosine similarity. Returns list of (index, score)."""
        if not self.embeddings or not query_embedding:
            return []

        scores = []
        q_norm = math.sqrt(sum(x * x for x in query_embedding)) + 1e-9
        for i, emb in enumerate(self.embeddings):
            if not emb or len(emb) != len(query_embedding):
                scores.append((i, 0.0))
                continue
            dot = sum(a * b for a, b in zip(query_embedding, emb))
            e_norm = math.sqrt(sum(x * x for x in emb)) + 1e-9
            scores.append((i, dot / (q_norm * e_norm)))

        scores.sort(key=lambda x: -x[1])
        return [(i, s) for i, s in scores[:top_k] if s > 0.01]


def reciprocal_rank_fusion(
    rankings: List[List[Tuple[int, float]]],
    k: int = 60,
    alpha: float = 0.5,
) -> List[Tuple[int, float]]:
    """Combine multiple ranked lists using Reciprocal Rank Fusion.

    Args:
        rankings: List of ranked results, each as (doc_index, score) tuples.
        k: RRF constant (higher = less influence from ranking).
        alpha: Weight for first ranking (remaining weight split among others).

    Returns:
        Fused ranking as (doc_index, combined_score) sorted by score desc.
    """
    doc_scores: Dict[int, float] = defaultdict(float)
    total_weight = alpha + (1.0 - alpha) * max(len(rankings) - 1, 1)

    for rank_idx, ranking in enumerate(rankings):
        weight = alpha if rank_idx == 0 else (1.0 - alpha) / max(len(rankings) - 1, 1)
        for rank, (doc_idx, _) in enumerate(ranking):
            doc_scores[doc_idx] += weight / (k + rank + 1)

    fused = sorted(doc_scores.items(), key=lambda x: -x[1])
    return fused


def hybrid_search(
    query: str,
    chunks: List[Chunk],
    query_embedding: Optional[List[float]] = None,
    embeddings: Optional[List[List[float]]] = None,
    top_k: int = 5,
    prefilter_k: int = 15,
    alpha: float = 0.5,
) -> List[Tuple[Chunk, float]]:
    """Perform hybrid search combining keyword and semantic retrieval.

    Args:
        query: Search query text.
        chunks: List of indexed chunks.
        query_embedding: Optional embedding vector for the query.
        embeddings: Optional list of chunk embeddings (parallel to chunks).
        top_k: Number of final results to return.
        prefilter_k: Number of candidates to consider before fusion.
        alpha: Weight for BM25 vs semantic (0=pure semantic, 1=pure keyword).

    Returns:
        List of (chunk, score) tuples sorted by relevance.
    """
    if not chunks:
        return []

    # Step 1: Keyword search via TF-IDF
    tfidf = TFIDFIndex([c.content for c in chunks])
    keyword_results = tfidf.search(query, top_k=prefilter_k)

    # Step 2: Semantic search via vector index
    semantic_results: List[Tuple[int, float]] = []
    if query_embedding and embeddings and len(embeddings) == len(chunks):
        vec_idx = VectorIndex(embeddings, [c.id for c in chunks])
        semantic_results = vec_idx.search(query_embedding, top_k=prefilter_k)

    # Step 3: Fuse with RRF
    rankings = [keyword_results]
    if semantic_results:
        rankings.append(semantic_results)
    fused = reciprocal_rank_fusion(rankings, k=60, alpha=alpha)

    # Step 4: Return top-k chunks with scores
    results = []
    for doc_idx, score in fused[:top_k]:
        if doc_idx < len(chunks):
            results.append((chunks[doc_idx], round(score, 6)))

    return results
