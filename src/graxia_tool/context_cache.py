"""Enterprise Agent OS — Context Cache. Semantic cache with BM25 keyword matching."""
from __future__ import annotations
import hashlib, json, re, sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional
from .core.logging import get_logger
from .shared.bm25 import bm25_overlap, extract_keywords

logger = get_logger("context_cache")

@dataclass
class CachedContext:
    """A cached routing decision and its result."""

    prompt: str = ""
    decision: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] = field(default_factory=dict)
    prompt_hash: str = ""
    keywords: list[str] = field(default_factory=list)
    created_at: str = ""
    expires_at: str = ""
    hit_count: int = 0

    def __post_init__(self) -> None:
        if not self.prompt_hash:
            self.prompt_hash = _hash_prompt(self.prompt)
        if not self.keywords:
            self.keywords = _extract_keywords(self.prompt)
        now = datetime.utcnow()
        if not self.created_at:
            self.created_at = now.isoformat()
        if not self.expires_at:
            self.expires_at = (now + timedelta(hours=1)).isoformat()

    def is_expired(self) -> bool:
        """Check if this cached context has expired."""
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.utcnow() > exp
        except Exception:
            return False


@dataclass
class CodebaseSnapshot:
    """Cached codebase understanding."""

    path: str = ""
    file_structure: list[str] = field(default_factory=list)
    key_patterns: list[str] = field(default_factory=list)
    architecture_notes: str = ""
    total_files: int = 0
    total_lines: int = 0
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


# Helpers now imported from shared.bm25: bm25_overlap, extract_keywords
# Keep local aliases for backward compat with CachedContext.__post_init__
def _hash_prompt(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", prompt.strip().lower())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]

# Re-export for any code referencing these directly
def _extract_keywords(text: str) -> list[str]:
    return extract_keywords(text)

def _bm25_overlap(kw1: list[str], kw2: list[str]) -> float:
    return bm25_overlap(kw1, kw2)


# ─────────────────────────────────────────────────────────────────────────────
# Context Cache
# ─────────────────────────────────────────────────────────────────────────────

class ContextCache:
    """Caches compiled routing decisions and their results.

    Uses SQLite for storage and BM25 keyword overlap for semantic matching.

    Usage:
        cache = ContextCache()
        cache.set("Fix the auth bug", decision, {"output": "Fixed"})
        cached = cache.get("Fix the auth bug")
    """

    def __init__(self, db_path: Optional[str] = None, default_ttl_hours: float = 1.0) -> None:
        """Initialize the context cache.

        Args:
            db_path: SQLite path. None = in-memory.
            default_ttl_hours: Default TTL for cached entries.
        """
        self._db_path = db_path
        self._default_ttl_hours = default_ttl_hours
        self._conn: Optional[sqlite3.Connection] = None
        self._hits: int = 0
        self._misses: int = 0
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        """Open SQLite connection."""
        if self._db_path:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS cached_contexts (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                prompt_hash TEXT NOT NULL,
                decision TEXT DEFAULT '{}',
                result TEXT DEFAULT '{}',
                keywords TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                hit_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS codebase_snapshots (
                path TEXT PRIMARY KEY,
                file_structure TEXT DEFAULT '[]',
                key_patterns TEXT DEFAULT '[]',
                architecture_notes TEXT DEFAULT '',
                total_files INTEGER DEFAULT 0,
                total_lines INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cc_hash ON cached_contexts(prompt_hash);
            CREATE INDEX IF NOT EXISTS idx_cc_expires ON cached_contexts(expires_at);
        """)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Core cache operations ────────────────────────────────────────────

    def get(self, prompt: str) -> Optional[CachedContext]:
        """Get cached context for a prompt (semantic match).

        First tries exact hash match, then falls back to BM25 keyword overlap.

        Args:
            prompt: User prompt to look up.

        Returns:
            CachedContext if found and not expired, else None.
        """
        assert self._conn is not None
        prompt_hash = _hash_prompt(prompt)

        # 1. Exact hash match (fast path)
        row = self._conn.execute(
            "SELECT * FROM cached_contexts WHERE prompt_hash = ?",
            (prompt_hash,),
        ).fetchone()

        if row and not self._is_expired_row(row):
            self._hits += 1
            self._conn.execute(
                "UPDATE cached_contexts SET hit_count = hit_count + 1 WHERE id = ?",
                (row["id"],),
            )
            self._conn.commit()
            return self._row_to_cached_context(row)

        # 2. BM25 keyword match (semantic fallback)
        query_kw = _extract_keywords(prompt)
        if not query_kw:
            self._misses += 1
            return None

        # Get recent non-expired entries
        rows = self._conn.execute(
            """SELECT * FROM cached_contexts
               WHERE expires_at > ?
               ORDER BY created_at DESC
               LIMIT 50""",
            (datetime.utcnow().isoformat(),),
        ).fetchall()

        best_score = 0.0
        best_row = None
        for r in rows:
            stored_kw = json.loads(r["keywords"])
            score = _bm25_overlap(query_kw, stored_kw)
            # Boost for exact prompt match (different casing/whitespace)
            if r["prompt_hash"] == prompt_hash:
                score = 1.0
            if score > best_score:
                best_score = score
                best_row = r

        if best_row and best_score >= 0.3:
            self._hits += 1
            self._conn.execute(
                "UPDATE cached_contexts SET hit_count = hit_count + 1 WHERE id = ?",
                (best_row["id"],),
            )
            self._conn.commit()
            ctx = self._row_to_cached_context(best_row)
            ctx.hit_count = best_row["hit_count"] + 1
            return ctx

        self._misses += 1
        return None

    def set(
        self,
        prompt: str,
        decision: Any,
        result: dict[str, Any],
        ttl_hours: Optional[float] = None,
    ) -> str:
        """Cache a routing decision and its result.

        Args:
            prompt: User prompt.
            decision: RoutingDecision or dict.
            result: Result dict from execution.
            ttl_hours: Time-to-live in hours. None = default.

        Returns:
            Cache entry ID.
        """
        assert self._conn is not None
        ttl = ttl_hours or self._default_ttl_hours
        now = datetime.utcnow()
        expires = now + timedelta(hours=ttl)

        prompt_hash = _hash_prompt(prompt)
        keywords = _extract_keywords(prompt)

        # Serialize decision
        if hasattr(decision, "to_dict"):
            decision_dict = decision.to_dict()
        elif isinstance(decision, dict):
            decision_dict = decision
        else:
            decision_dict = {"raw": str(decision)}

        entry_id = prompt_hash
        self._conn.execute(
            """INSERT OR REPLACE INTO cached_contexts
               (id, prompt, prompt_hash, decision, result, keywords,
                created_at, expires_at, hit_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                entry_id,
                prompt,
                prompt_hash,
                json.dumps(decision_dict, default=str),
                json.dumps(result, default=str),
                json.dumps(keywords),
                now.isoformat(),
                expires.isoformat(),
            ),
        )
        self._conn.commit()

        logger.debug("context_cached", prompt_hash=prompt_hash, ttl_hours=ttl)
        return entry_id

    # ── Codebase snapshots ───────────────────────────────────────────────

    def get_codebase_snapshot(self, path: str) -> Optional[CodebaseSnapshot]:
        """Get cached codebase understanding.

        Args:
            path: Directory or file path.

        Returns:
            CodebaseSnapshot if found, else None.
        """
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT * FROM codebase_snapshots WHERE path = ?", (path,)
        ).fetchone()

        if row:
            return CodebaseSnapshot(
                path=row["path"],
                file_structure=json.loads(row["file_structure"]) if row["file_structure"] else [],
                key_patterns=json.loads(row["key_patterns"]) if row["key_patterns"] else [],
                architecture_notes=row["architecture_notes"],
                total_files=row["total_files"],
                total_lines=row["total_lines"],
                created_at=row["created_at"],
            )
        return None

    def store_codebase_snapshot(self, path: str, snapshot: CodebaseSnapshot) -> None:
        """Store codebase understanding.

        Args:
            path: Directory or file path.
            snapshot: CodebaseSnapshot to store.
        """
        assert self._conn is not None
        self._conn.execute(
            """INSERT OR REPLACE INTO codebase_snapshots
               (path, file_structure, key_patterns, architecture_notes,
                total_files, total_lines, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                path,
                json.dumps(snapshot.file_structure),
                json.dumps(snapshot.key_patterns),
                snapshot.architecture_notes,
                snapshot.total_files,
                snapshot.total_lines,
                snapshot.created_at or datetime.utcnow().isoformat(),
            ),
        )
        self._conn.commit()

    # ── Cleanup ──────────────────────────────────────────────────────────

    def cleanup_expired(self) -> int:
        """Remove expired cache entries.

        Returns:
            Number of entries removed.
        """
        assert self._conn is not None
        now = datetime.utcnow().isoformat()
        result = self._conn.execute(
            "DELETE FROM cached_contexts WHERE expires_at < ?", (now,)
        )
        removed = result.rowcount
        self._conn.commit()
        if removed > 0:
            logger.info("cache_cleanup", removed=removed)
        return removed

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with hit rate, entry counts, etc.
        """
        assert self._conn is not None
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        context_count = self._conn.execute(
            "SELECT COUNT(*) as c FROM cached_contexts"
        ).fetchone()["c"]

        expired_count = self._conn.execute(
            "SELECT COUNT(*) as c FROM cached_contexts WHERE expires_at < ?",
            (datetime.utcnow().isoformat(),),
        ).fetchone()["c"]

        snapshot_count = self._conn.execute(
            "SELECT COUNT(*) as c FROM codebase_snapshots"
        ).fetchone()["c"]

        return {
            "total_queries": total,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "cached_contexts": context_count,
            "expired_contexts": expired_count,
            "codebase_snapshots": snapshot_count,
        }

    # ── Internal helpers ─────────────────────────────────────────────────

    def _is_expired_row(self, row: sqlite3.Row) -> bool:
        """Check if a DB row is expired."""
        try:
            exp = datetime.fromisoformat(row["expires_at"])
            return datetime.utcnow() > exp
        except Exception:
            return True

    def _row_to_cached_context(self, row: sqlite3.Row) -> CachedContext:
        """Convert a DB row to CachedContext."""
        return CachedContext(
            prompt=row["prompt"],
            decision=json.loads(row["decision"]) if row["decision"] else {},
            result=json.loads(row["result"]) if row["result"] else {},
            prompt_hash=row["prompt_hash"],
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            hit_count=row["hit_count"],
        )
