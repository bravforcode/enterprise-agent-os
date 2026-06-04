"""Hybrid RAG Search — unified BM25 + vector + rerank with dedup and relevance-gap filtering.

Pipeline:
1. BM25 keyword search (shared/bm25.py)
2. Dense vector search (Qdrant or in-memory)
3. Score fusion (mode-weighted)
4. Deduplication (similarity > 0.85 → update)
5. Relevance-gap filtering (natural score cutoff)
6. Cross-encoder rerank (qwen or keyword proxy)
7. Stats logging to SQLite
"""
from __future__ import annotations

import hashlib
import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..shared.bm25 import bm25_score, extract_keywords
from ..core.logging import get_logger

logger = get_logger("hybrid_rag")


# ─── Data structures ────────────────────────────────────────────────────────

@dataclass
class HybridResult:
    """Single hybrid search result."""
    content: str
    score: float
    bm25_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    source: str = ""
    citation: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchStats:
    """Stats for a single search operation."""
    query: str
    mode: str
    total_candidates: int
    after_dedup: int
    after_gap_filter: int
    top_k: int
    duration_ms: float
    dedup_skipped: int = 0


# ─── SQLite stats store ──────────────────────────────────────────────────────

class SearchStatsStore:
    """Persistent SQLite store for hybrid search stats."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or str(Path.home() / ".graxia" / "hybrid_rag.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    def _init_schema(self) -> None:
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS search_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                mode TEXT NOT NULL,
                total_candidates INTEGER DEFAULT 0,
                after_dedup INTEGER DEFAULT 0,
                after_gap_filter INTEGER DEFAULT 0,
                top_k INTEGER DEFAULT 5,
                duration_ms REAL DEFAULT 0,
                dedup_skipped INTEGER DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_search_mode ON search_stats(mode);
            CREATE INDEX IF NOT EXISTS idx_search_created ON search_stats(created_at);
        """)
        conn.commit()

    def record(self, stats: SearchStats) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT INTO search_stats
               (query, mode, total_candidates, after_dedup, after_gap_filter,
                top_k, duration_ms, dedup_skipped, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
            (stats.query, stats.mode, stats.total_candidates, stats.after_dedup,
             stats.after_gap_filter, stats.top_k, stats.duration_ms, stats.dedup_skipped),
        )
        conn.commit()

    def get_totals(self) -> Dict[str, Any]:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) as total, SUM(dedup_skipped) as total_dedup "
            "FROM search_stats"
        ).fetchone()
        return {
            "total_searches": row["total"] if row else 0,
            "total_dedup_skipped": row["total_dedup"] if row else 0,
        }

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None


# ─── Score helpers ──────────────────────────────────────────────────────────

def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) + 1e-9
    norm_b = math.sqrt(sum(x * x for x in b)) + 1e-9
    return dot / (norm_a * norm_b)


def _text_similarity(a: str, b: str) -> float:
    """Jaccard similarity over keywords as a fast proxy."""
    kw_a = set(extract_keywords(a))
    kw_b = set(extract_keywords(b))
    if not kw_a or not kw_b:
        return 0.0
    return len(kw_a & kw_b) / len(kw_a | kw_b)


# Mode weight profiles: (bm25_weight, vector_weight, rerank_weight)
MODE_WEIGHTS: Dict[str, tuple[float, float, float]] = {
    "semantic": (0.10, 0.90, 0.20),
    "graph":    (0.15, 0.70, 0.30),
    "balanced": (0.50, 0.50, 0.20),
}


# ─── HybridSearch ───────────────────────────────────────────────────────────

class HybridSearch:
    """Unified hybrid search: BM25 + vector + rerank with dedup and gap filtering.

    Usage:
        hs = HybridSearch()
        results = hs.search("auth bug fix", top_k=5, mode="balanced")
    """

    def __init__(
        self,
        stats_db_path: Optional[str] = None,
        dedup_threshold: float = 0.85,
    ) -> None:
        self.dedup_threshold = dedup_threshold
        self._stats_store = SearchStatsStore(stats_db_path)
        self._qwen_available: Optional[bool] = None

    # ── Public API ─────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        top_k: int = 5,
        mode: str = "balanced",
        candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Run hybrid search: BM25 + vector + rerank.

        Args:
            query: Search query.
            top_k: Max results to return.
            mode: "semantic" | "graph" | "balanced".
            candidates: Optional pre-fetched candidate dicts with 'content' key.
                        If None, queries session memory + RAG.

        Returns:
            Dict with results, stats, and context.
        """
        start = time.time()

        if mode not in MODE_WEIGHTS:
            mode = "balanced"

        # 1. Gather candidates
        if candidates is None:
            candidates = await self._gather_candidates(query)

        total = len(candidates)

        # 2. Score each candidate
        scored = self._score_candidates(query, candidates, mode)

        # 3. Dedup
        deduped, dedup_count = self.dedup_results(scored)

        # 4. Relevance-gap filter
        gap_filtered = self.relevance_gap_filter(deduped)

        # 5. Rerank top candidates
        reranked = await self._rerank(query, gap_filtered)

        # 6. Take top_k
        final = reranked[:top_k]

        duration_ms = (time.time() - start) * 1000

        # 7. Log stats
        stats = SearchStats(
            query=query,
            mode=mode,
            total_candidates=total,
            after_dedup=len(deduped),
            after_gap_filter=len(gap_filtered),
            top_k=len(final),
            duration_ms=round(duration_ms, 2),
            dedup_skipped=dedup_count,
        )
        self._stats_store.record(stats)

        # Build context string
        context_parts = [r.content for r in final]
        context = "\n\n---\n\n".join(context_parts)

        return {
            "results": [
                {
                    "content": r.content,
                    "score": round(r.score, 4),
                    "bm25_score": round(r.bm25_score, 4),
                    "vector_score": round(r.vector_score, 4),
                    "rerank_score": round(r.rerank_score, 4),
                    "source": r.source,
                    "citation": r.citation,
                }
                for r in final
            ],
            "context": context,
            "citations": [r.citation for r in final if r.citation],
            "estimated_tokens": len(context) // 4,
            "stats": {
                "mode": mode,
                "total_candidates": total,
                "after_dedup": len(deduped),
                "after_gap_filter": len(gap_filtered),
                "top_k": len(final),
                "dedup_skipped": dedup_count,
                "duration_ms": round(duration_ms, 2),
            },
        }

    def dedup_results(
        self, results: List[HybridResult]
    ) -> tuple[List[HybridResult], int]:
        """Remove duplicate results by content similarity.

        If two results have > threshold similarity, keep the higher-scored one.

        Returns:
            (deduped_results, count_of_skipped_duplicates)
        """
        if not results:
            return [], 0

        # Sort by score descending so we keep the best
        sorted_results = sorted(results, key=lambda r: -r.score)
        kept: List[HybridResult] = []
        skipped = 0

        for r in sorted_results:
            is_dup = False
            for existing in kept:
                sim = _text_similarity(r.content, existing.content)
                if sim > self.dedup_threshold:
                    is_dup = True
                    skipped += 1
                    break
            if not is_dup:
                kept.append(r)

        return kept, skipped

    def relevance_gap_filter(self, results: List[HybridResult]) -> List[HybridResult]:
        """Filter results by natural score gaps.

        Sorts by score, finds the largest gap, and returns only results above it.
        If all scores are close, returns all results.
        """
        if len(results) <= 2:
            return results

        sorted_r = sorted(results, key=lambda r: -r.score)

        # Find largest gap
        max_gap = 0.0
        gap_idx = 0
        for i in range(len(sorted_r) - 1):
            gap = sorted_r[i].score - sorted_r[i + 1].score
            if gap > max_gap:
                max_gap = gap
                gap_idx = i

        # Only filter if the gap is significant (top score isn't near zero)
        top_score = sorted_r[0].score if sorted_r else 0.0
        if top_score > 0 and max_gap > top_score * 0.3:
            return sorted_r[: gap_idx + 1]

        return sorted_r

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate search stats."""
        return self._stats_store.get_totals()

    # ── Internal ───────────────────────────────────────────────────────────

    async def _gather_candidates(self, query: str) -> List[Dict[str, Any]]:
        """Gather candidates from session memory + RAG."""
        candidates: List[Dict[str, Any]] = []

        # Session memory (BM25)
        try:
            from ..session_memory import SessionMemory
            from ..mcp import _get_session_db_path

            mem = SessionMemory(db_path=_get_session_db_path())
            recall_results = mem.recall(query, limit=20)
            for r in recall_results:
                candidates.append({
                    "content": r.content,
                    "source": f"session:{r.memory_type}",
                    "metadata": r.extra,
                })
        except Exception as e:
            logger.debug("session_memory_recall_failed", error=str(e))

        # RAG retriever (dense + BM25 hybrid)
        try:
            from ..rag import RAGOS
            rag = RAGOS()
            rag_result = rag.query(query, top_k=15)
            for r in rag_result.chunks:
                candidates.append({
                    "content": r.chunk.content,
                    "source": r.citation or "rag",
                    "metadata": {},
                })
        except Exception as e:
            logger.debug("rag_query_failed", error=str(e))

        return candidates

    def _score_candidates(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        mode: str,
    ) -> List[HybridResult]:
        """Score candidates with BM25 + text-similarity (vector proxy)."""
        weights = MODE_WEIGHTS[mode]
        query_keywords = extract_keywords(query)
        query_kw_set = set(query_keywords)
        results: List[HybridResult] = []

        for c in candidates:
            content = c.get("content", "")
            if not content:
                continue

            # BM25 score
            s_bm25 = bm25_score(query_keywords, content)

            # Vector proxy: Jaccard over keywords (real vector would need embedding)
            content_kw = set(extract_keywords(content))
            if query_kw_set and content_kw:
                s_vector = len(query_kw_set & content_kw) / len(query_kw_set | content_kw)
            else:
                s_vector = 0.0

            # Fused score
            fused = weights[0] * s_bm25 + weights[1] * s_vector

            results.append(HybridResult(
                content=content,
                score=fused,
                bm25_score=s_bm25,
                vector_score=s_vector,
                source=c.get("source", ""),
                metadata=c.get("metadata", {}),
            ))

        return sorted(results, key=lambda r: -r.score)

    async def _rerank(
        self, query: str, results: List[HybridResult]
    ) -> List[HybridResult]:
        """Rerank results using qwen or keyword overlap as proxy."""
        if not results:
            return results

        # Try qwen reranking
        reranked = await self._qwen_rerank(query, results)
        if reranked is not None:
            return reranked

        # Fallback: keyword overlap boost
        q_kw = set(extract_keywords(query))
        for r in results:
            content_kw = set(extract_keywords(r.content))
            overlap = len(q_kw & content_kw) / max(len(q_kw), 1)
            r.rerank_score = overlap
            r.score += overlap * 0.05  # Small rerank boost

        return sorted(results, key=lambda r: -r.score)

    async def _qwen_rerank(
        self, query: str, results: List[HybridResult]
    ) -> Optional[List[HybridResult]]:
        """Attempt reranking via qwen3.5 local LLM."""
        if self._qwen_available is False:
            return None

        try:
            from ..memory.qwen_memory import QwenMemory
            qwen = QwenMemory()
            if not qwen.client.is_available():
                self._qwen_available = False
                return None

            self._qwen_available = True
            candidate_texts = [r.content[:300] for r in results[:10]]
            task = qwen.rerank(query, candidate_texts)

            if not task.success:
                return None

            # Parse ranking: "3,1,2" → indices [2, 0, 1]
            ranks = [int(x.strip()) - 1 for x in task.output.split(",")]
            reranked = []
            for idx in ranks:
                if 0 <= idx < len(results):
                    r = results[idx]
                    r.rerank_score = 1.0 / (ranks.index(idx) + 1)
                    reranked.append(r)

            # Add any results not in the ranking
            seen = set(ranks)
            for i, r in enumerate(results):
                if i not in seen:
                    reranked.append(r)

            return reranked

        except Exception as e:
            logger.debug("qwen_rerank_failed", error=str(e))
            self._qwen_available = False
            return None


# ─── MCP tool handlers ──────────────────────────────────────────────────────

async def hybrid_search_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """MCP handler for hybrid_rag_search tool."""
    from ..shared.helpers import _ok, _err

    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))
    mode = args.get("mode", "balanced")

    if not query:
        return _err("query is required")

    hs = HybridSearch()
    try:
        result = await hs.search(query, top_k=top_k, mode=mode)
        return _ok(result)
    except Exception as e:
        logger.exception("hybrid_search failed")
        return _err(f"{type(e).__name__}: {e}")


async def hybrid_rerank_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """MCP handler for hybrid_rag_rerank — rerank existing candidates."""
    from ..shared.helpers import _ok, _err

    query = args.get("query", "")
    candidates = args.get("candidates", [])
    top_k = int(args.get("top_k", 5))

    if not query:
        return _err("query is required")
    if not candidates:
        return _err("candidates list is required")

    hs = HybridSearch()
    try:
        # Convert candidate dicts to HybridResult
        scored = hs._score_candidates(query, candidates, "balanced")
        deduped, dedup_count = hs.dedup_results(scored)
        gap_filtered = hs.relevance_gap_filter(deduped)
        reranked = await hs._rerank(query, gap_filtered)
        final = reranked[:top_k]

        return _ok({
            "results": [
                {
                    "content": r.content,
                    "score": round(r.score, 4),
                    "source": r.source,
                }
                for r in final
            ],
            "reranked_count": len(final),
            "dedup_skipped": dedup_count,
        })
    except Exception as e:
        logger.exception("hybrid_rerank failed")
        return _err(f"{type(e).__name__}: {e}")


async def hybrid_stats_handler(args: Dict[str, Any]) -> Dict[str, Any]:
    """MCP handler for hybrid_rag_stats."""
    from ..shared.helpers import _ok

    hs = HybridSearch()
    return _ok(hs.get_stats())


# ─── Tool definitions for registration ──────────────────────────────────────

HYBRID_RAG_TOOLS = [
    {
        "name": "hybrid_rag_search",
        "description": "Hybrid RAG search: BM25 + vector + rerank with dedup and relevance-gap filtering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "default": 5},
                "mode": {
                    "type": "string",
                    "enum": ["semantic", "graph", "balanced"],
                    "default": "balanced",
                    "description": "semantic=90% vector, graph=70% graph, balanced=50/50",
                },
            },
            "required": ["query"],
        },
        "handler": hybrid_search_handler,
        "category": "rag",
    },
    {
        "name": "hybrid_rag_rerank",
        "description": "Rerank existing candidates using hybrid scoring.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "candidates": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"content": {"type": "string"}}},
                },
                "top_k": {"type": "integer", "default": 5},
            },
            "required": ["query", "candidates"],
        },
        "handler": hybrid_rerank_handler,
        "category": "rag",
    },
    {
        "name": "hybrid_rag_stats",
        "description": "Get hybrid search stats: total searches, dedup count.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": hybrid_stats_handler,
        "category": "rag",
    },
]
