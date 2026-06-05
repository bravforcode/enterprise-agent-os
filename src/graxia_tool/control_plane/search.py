"""Hybrid search engine combining BM25 with recency-based scoring."""

import math
import re
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class SearchResult:
    """A single search result with its score."""

    doc_id: str
    source: str
    title: str
    content: str
    score: float
    bm25_score: float
    recency_score: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchConfig:
    """Configuration for hybrid search."""

    db_path: str = "graxia_search.db"
    bm25_weight: float = 0.7
    recency_weight: float = 0.3
    recency_half_life_hours: float = 72.0
    max_results: int = 20
    min_score: float = 0.01


class HybridSearch:
    """Hybrid search engine with BM25 + recency scoring.

    Features:
    - BM25 search via SQLite FTS5
    - Keyword extraction from natural language queries
    - Configurable hybrid scoring with recency decay
    - Cross-source search (memory, skills, codebase)
    """

    def __init__(self, config: Optional[SearchConfig] = None):
        self.config = config or SearchConfig()
        self.conn = sqlite3.connect(self.config.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Initialize FTS5 tables."""
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                doc_id UNINDEXED,
                title,
                content,
                source,
                tokenize='porter unicode61'
            );
            """
        )
        self.conn.commit()

    def extract_keywords(self, query: str) -> List[str]:
        """Extract meaningful keywords from a natural language query.

        Strips stop words and short tokens to improve search precision.
        """
        stop_words = {
            "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "out", "off", "over",
            "under", "again", "further", "then", "once", "here", "there", "when",
            "where", "why", "how", "all", "both", "each", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "just", "don", "now", "and", "but", "or",
            "if", "while", "that", "this", "these", "those", "it", "its",
        }

        words = re.findall(r"[a-zA-Z0-9_]{2,}", query.lower())
        return [w for w in words if w not in stop_words and len(w) >= 2]

    def index(
        self,
        doc_id: str,
        source: str,
        title: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Index a document for searching."""
        now = time.time()
        cur = self.conn.cursor()

        cur.execute(
            "DELETE FROM documents WHERE doc_id = ?", (doc_id,)
        )
        cur.execute(
            "DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,)
        )

        cur.execute(
            """
            INSERT INTO documents (doc_id, source, title, content, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (doc_id, source, title, content, now, now, str(metadata or {})),
        )
        cur.execute(
            "INSERT INTO documents_fts (doc_id, title, content, source) VALUES (?, ?, ?, ?)",
            (doc_id, title, content, source),
        )
        self.conn.commit()

    def index_batch(self, documents: List[Dict[str, Any]]) -> int:
        """Index multiple documents at once. Returns count indexed.

        Each dict must have: doc_id, source, title, content.
        Optional: metadata.
        """
        now = time.time()
        cur = self.conn.cursor()
        for doc in documents:
            doc_id = doc["doc_id"]
            cur.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
            cur.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))

        for doc in documents:
            cur.execute(
                """
                INSERT INTO documents (doc_id, source, title, content, created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc["doc_id"],
                    doc["source"],
                    doc["title"],
                    doc["content"],
                    now,
                    now,
                    str(doc.get("metadata", {})),
                ),
            )
            cur.execute(
                "INSERT INTO documents_fts (doc_id, title, content, source) VALUES (?, ?, ?, ?)",
                (doc["doc_id"], doc["title"], doc["content"], doc["source"]),
            )
        self.conn.commit()
        return len(documents)

    def search(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[SearchResult]:
        """Run hybrid search with BM25 + recency scoring.

        Args:
            query: Natural language search query.
            sources: Filter by source types (e.g. ['memory', 'skill']).
            limit: Max results to return.

        Returns:
            Ranked list of SearchResult objects.
        """
        limit = limit or self.config.max_results
        keywords = self.extract_keywords(query)
        if not keywords:
            return []

        fts_query = " OR ".join(keywords)

        cur = self.conn.cursor()

        if sources:
            placeholders = ",".join("?" * len(sources))
            cur.execute(
                f"""
                SELECT d.doc_id, d.source, d.title, d.content, d.created_at, d.metadata,
                       bm25(documents_fts) as bm25_score
                FROM documents_fts f
                JOIN documents d ON d.doc_id = f.doc_id
                WHERE documents_fts MATCH ? AND d.source IN ({placeholders})
                ORDER BY bm25(documents_fts)
                LIMIT ?
                """,
                (fts_query, *sources, limit * 3),
            )
        else:
            cur.execute(
                """
                SELECT d.doc_id, d.source, d.title, d.content, d.created_at, d.metadata,
                       bm25(documents_fts) as bm25_score
                FROM documents_fts f
                JOIN documents d ON d.doc_id = f.doc_id
                WHERE documents_fts MATCH ?
                ORDER BY bm25(documents_fts)
                LIMIT ?
                """,
                (fts_query, limit * 3),
            )

        rows = cur.fetchall()
        now = time.time()
        results = []

        for row in rows:
            bm25_raw = abs(row["bm25_score"]) if row["bm25_score"] else 0.0

            age_hours = max((now - row["created_at"]) / 3600, 0.001)
            half_life = self.config.recency_half_life_hours
            recency = math.exp(-0.693 * age_hours / half_life)

            score = (
                self.config.bm25_weight * bm25_raw
                + self.config.recency_weight * recency
            )

            if score < self.config.min_score:
                continue

            try:
                metadata = eval(row["metadata"])
            except Exception:
                metadata = {}

            results.append(
                SearchResult(
                    doc_id=row["doc_id"],
                    source=row["source"],
                    title=row["title"],
                    content=row["content"],
                    score=score,
                    bm25_score=bm25_raw,
                    recency_score=recency,
                    metadata=metadata,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def search_memory(self, query: str, limit: int = 10) -> List[SearchResult]:
        """Search only memory sources."""
        return self.search(query, sources=["memory", "task", "preference"], limit=limit)

    def search_skills(self, query: str, limit: int = 10) -> List[SearchResult]:
        """Search only skill sources."""
        return self.search(query, sources=["skill"], limit=limit)

    def search_codebase(self, query: str, limit: int = 10) -> List[SearchResult]:
        """Search only codebase sources."""
        return self.search(query, sources=["codebase", "code"], limit=limit)

    def delete(self, doc_id: str) -> bool:
        """Delete a document by ID."""
        cur = self.conn.cursor()
        cur.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        cur.execute("DELETE FROM documents_fts WHERE doc_id = ?", (doc_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) as total FROM documents")
        total = cur.fetchone()["total"]

        cur.execute(
            "SELECT source, COUNT(*) as cnt FROM documents GROUP BY source"
        )
        by_source = {row["source"]: row["cnt"] for row in cur.fetchall()}

        return {"total_documents": total, "by_source": by_source}

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
