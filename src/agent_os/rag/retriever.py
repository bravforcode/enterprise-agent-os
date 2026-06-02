"""Enterprise Agent OS — Hybrid Retriever (BM25 + Dense + Rerank).

Pipeline:
1. BM25 keyword search
2. Dense vector search (Qdrant)
3. Reciprocal Rank Fusion
4. Cross-encoder reranking
5. Return top-K with citations
"""
from __future__ import annotations
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional
from .chunker import Chunk
from .ingestion import Document, load_document
from ..core.logging import get_logger

logger = get_logger("retriever")


@dataclass
class RetrievalResult:
    """A single retrieval result with score and citation."""
    chunk: Chunk
    score: float
    bm25_score: float = 0.0
    dense_score: float = 0.0
    rerank_score: float = 0.0
    citation: str = ""


class BM25:
    """Simple BM25 implementation."""
    def __init__(self, corpus_tokens: list[list[str]]):
        self.corpus = corpus_tokens
        self.N = len(corpus_tokens)
        self.avgdl = sum(len(d) for d in corpus_tokens) / max(self.N, 1)
        self.k1 = 1.5
        self.b = 0.75
        self.df: dict[str, int] = defaultdict(int)
        for doc in corpus_tokens:
            for t in set(doc):
                self.df[t] += 1
        self.idf = {t: math.log((self.N - df + 0.5) / (df + 0.5) + 1) for t, df in self.df.items()}

    def score(self, query_tokens: list[str]) -> list[float]:
        scores = [0.0] * self.N
        for q in query_tokens:
            if q not in self.idf:
                continue
            idf = self.idf[q]
            for i, doc in enumerate(self.corpus):
                tf = doc.count(q)
                if tf == 0:
                    continue
                dl = len(doc)
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[i] += idf * (tf * (self.k1 + 1)) / denom
        return scores


TOKEN_RE = re.compile(r"[a-z0-9\u0E00-\u0E7F]+")
def tokenize(s: str) -> list[str]:
    return [t for t in TOKEN_RE.findall(s.lower()) if len(t) > 1]


class HybridRetriever:
    """
    Hybrid retriever combining BM25 + dense vector search.
    With optional reranking.
    """

    def __init__(self):
        self.chunks: list[Chunk] = []
        self.embeddings: list[list[float]] = []
        self.bm25: Optional[BM25] = None
        self._corpus_tokens: list[list[str]] = []

    def index(self, chunks: list[Chunk], embeddings: Optional[list[list[float]]] = None) -> None:
        """Index a list of chunks."""
        self.chunks = chunks
        self.embeddings = embeddings or []
        # Build BM25 index
        self._corpus_tokens = [tokenize(c.content) for c in chunks]
        self.bm25 = BM25(self._corpus_tokens)
        logger.info("indexed_chunks", count=len(chunks))

    def add(self, chunk: Chunk, embedding: Optional[list[float]] = None) -> None:
        """Add a single chunk."""
        self.chunks.append(chunk)
        if embedding:
            self.embeddings.append(embedding)
        # Rebuild BM25 (for simplicity; in prod, use incremental)
        self._corpus_tokens = [tokenize(c.content) for c in self.chunks]
        self.bm25 = BM25(self._corpus_tokens)

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        query_embedding: Optional[list[float]] = None,
        rerank: bool = True,
    ) -> list[RetrievalResult]:
        """
        Retrieve top-K chunks for a query.

        Args:
            query: The search query
            top_k: Number of results
            query_embedding: Pre-computed query embedding (for dense)
            rerank: Whether to apply cross-encoder reranking

        Returns:
            List of RetrievalResult with scores and citations
        """
        n = len(self.chunks)
        if n == 0:
            return []

        # Step 1: BM25
        q_tokens = tokenize(query)
        bm25_scores = self.bm25.score(q_tokens) if self.bm25 else [0.0] * n

        # Step 2: Dense
        dense_scores = [0.0] * n
        if query_embedding and self.embeddings and len(self.embeddings) == n:
            for i, emb in enumerate(self.embeddings):
                if not emb:
                    continue
                score = self._cosine(query_embedding, emb)
                dense_scores[i] = score

        # Step 3: RRF (Reciprocal Rank Fusion)
        K_RRF = 60
        bm25_ranked = sorted(range(n), key=lambda i: -bm25_scores[i])
        dense_ranked = sorted(range(n), key=lambda i: -dense_scores[i])
        rrf = [0.0] * n
        for rank, idx in enumerate(bm25_ranked):
            if bm25_scores[idx] > 0:
                rrf[idx] += 1.0 / (K_RRF + rank + 1)
        for rank, idx in enumerate(dense_ranked):
            if dense_scores[idx] > 0.05:
                rrf[idx] += 1.0 / (K_RRF + rank + 1)

        # Step 4: Top-15 for reranking
        pre_ranked = sorted(range(n), key=lambda i: -rrf[i])
        candidates = pre_ranked[:15]

        # Step 5: Rerank (simple keyword overlap as proxy for cross-encoder)
        if rerank:
            for idx in candidates:
                content_words = set(tokenize(self.chunks[idx].content))
                overlap = len(content_words & set(q_tokens))
                rrf[idx] += overlap * 0.01

        # Step 6: Final ranking
        final_ranked = sorted(candidates, key=lambda i: -rrf[i])[:top_k]
        results = []
        for idx in final_ranked:
            chunk = self.chunks[idx]
            citation = f"{chunk.source}#{chunk.index}"
            if chunk.title:
                citation = f"{chunk.title} — {citation}"
            results.append(RetrievalResult(
                chunk=chunk,
                score=round(rrf[idx], 4),
                bm25_score=round(bm25_scores[idx], 4),
                dense_score=round(dense_scores[idx], 4),
                citation=citation,
            ))

        logger.info("retrieved", query=query[:30], results=len(results))
        return results

    def _cosine(self, a: list[float], b: list[float]) -> float:
        """Cosine similarity."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a)) + 1e-9
        norm_b = math.sqrt(sum(x * x for x in b)) + 1e-9
        return dot / (norm_a * norm_b)
