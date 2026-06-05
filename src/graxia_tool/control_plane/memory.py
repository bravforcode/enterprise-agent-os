"""Persistent memory manager with tier-based storage for Graxia Tool system.

Provides SQLite + FTS5 storage with four memory tiers:
- session: In-memory only, cleared on daemon restart
- working: TTL-based expiry (default 1 hour)
- longterm: No expiry, persists across sessions
- project: Scoped to a project identifier
"""

import hashlib
import json
import logging
import sqlite3
import time
import threading
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class MemoryTier(str, Enum):
    SESSION = "session"
    WORKING = "working"
    LONGTERM = "longterm"
    PROJECT = "project"


class MemoryManager:
    """Tier-based memory manager with SQLite persistence and FTS5 search."""

    DEFAULT_WORKING_TTL = 3600  # 1 hour
    DEFAULT_LONGTERM_TTL = 0  # no expiry
    DEFAULT_SESSION_TTL = 0  # no persistence

    def __init__(self, db_path: str = ":memory:", working_ttl: int = DEFAULT_WORKING_TTL):
        self.db_path = db_path
        self.working_ttl = working_ttl
        self._session_store: dict[str, dict[str, Any]] = {}
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._init_tables()

    def _init_tables(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                tier TEXT NOT NULL,
                project TEXT,
                key TEXT,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                accessed_at REAL NOT NULL,
                expires_at REAL,
                access_count INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_memories_tier ON memories(tier);
            CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project);
            CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash);
            CREATE INDEX IF NOT EXISTS idx_memories_expires_at ON memories(expires_at);

            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                key,
                tier,
                content=memories,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, key, tier)
                VALUES (new.rowid, new.content, new.key, new.tier);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, key, tier)
                VALUES ('delete', old.rowid, old.content, old.key, old.tier);
            END;

            CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, key, tier)
                VALUES ('delete', old.rowid, old.content, old.key, old.tier);
                INSERT INTO memories_fts(rowid, content, key, tier)
                VALUES (new.rowid, new.content, new.key, new.tier);
            END;
        """)
        self._conn.commit()

    def _compute_hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _now(self) -> float:
        return time.time()

    def store(
        self,
        content: str,
        tier: MemoryTier = MemoryTier.WORKING,
        project: Optional[str] = None,
        key: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> str:
        # Convert string to enum if needed
        if isinstance(tier, str):
            tier = MemoryTier(tier)
        now = self._now()
        content_hash = self._compute_hash(content)
        memory_id = str(uuid.uuid4())

        if tier == MemoryTier.SESSION:
            self._session_store[memory_id] = {
                "content": content,
                "tier": tier.value,
                "project": project,
                "key": key,
                "metadata": metadata or {},
                "created_at": now,
                "accessed_at": now,
                "access_count": 0,
            }
            return memory_id

        if tier == MemoryTier.WORKING:
            expires_at = now + (ttl or self.working_ttl)
        else:
            expires_at = None

        self._conn.execute(
            """INSERT INTO memories (id, tier, project, key, content, content_hash, metadata,
               created_at, accessed_at, expires_at, access_count)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (memory_id, tier.value, project, key, content, content_hash,
             json.dumps(metadata or {}), now, now, expires_at),
        )
        self._conn.commit()
        return memory_id

    def recall(
        self,
        memory_id: Optional[str] = None,
        key: Optional[str] = None,
        tier: Optional[MemoryTier] = None,
        project: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if memory_id:
            row = self._session_store.get(memory_id)
            if row:
                row["access_count"] += 1
                row["accessed_at"] = self._now()
                return [row]
            row = self._conn.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
            if row:
                self._update_access(row["id"])
                return [self._row_to_dict(row)]
            return []

        if query:
            return self._fts_search(query, tier=tier, project=project, limit=limit)

        conditions = []
        params: list[Any] = []
        if tier:
            conditions.append("tier = ?")
            params.append(tier.value)
        if project:
            conditions.append("project = ?")
            params.append(project)
        if key:
            conditions.append("key = ?")
            params.append(key)

        sql = "SELECT * FROM memories"
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY accessed_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _fts_search(
        self,
        query: str,
        tier: Optional[MemoryTier] = None,
        project: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT m.* FROM memories m
            JOIN memories_fts f ON m.rowid = f.rowid
            WHERE memories_fts MATCH ?
        """
        params: list[Any] = [query]

        if tier:
            sql += " AND m.tier = ?"
            params.append(tier.value)
        if project:
            sql += " AND m.project = ?"
            params.append(project)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def delete(self, memory_id: str) -> bool:
        if memory_id in self._session_store:
            del self._session_store[memory_id]
            return True
        cur = self._conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear_expired(self) -> int:
        now = self._now()
        cur = self._conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        self._conn.commit()
        return cur.rowcount

    def stats(self) -> dict[str, Any]:
        self.clear_expired()
        tier_counts = {}
        for row in self._conn.execute("SELECT tier, COUNT(*) as cnt FROM memories GROUP BY tier"):
            tier_counts[row["tier"]] = row["cnt"]
        tier_counts["session"] = len(self._session_store)

        total = sum(tier_counts.values())
        projects = [
            r["project"] for r in self._conn.execute(
                "SELECT DISTINCT project FROM memories WHERE project IS NOT NULL"
            )
        ]
        return {
            "total": total,
            "by_tier": tier_counts,
            "projects": projects,
            "db_path": self.db_path,
        }

    def _update_access(self, memory_id: str) -> None:
        now = self._now()
        self._conn.execute(
            "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
            (now, memory_id),
        )
        self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "tier": row["tier"],
            "project": row["project"],
            "key": row["key"],
            "content": row["content"],
            "content_hash": row["content_hash"],
            "metadata": json.loads(row["metadata"]),
            "created_at": row["created_at"],
            "accessed_at": row["accessed_at"],
            "expires_at": row["expires_at"],
            "access_count": row["access_count"],
        }

    def close(self) -> None:
        self.stop_persist()
        self._conn.close()

    def auto_persist(self, interval: int = 300) -> threading.Thread:
        """Start background thread that snapshots working → longterm every `interval` seconds.

        Returns the thread (daemon=True, auto-dies with parent).
        """
        self._stop_event = threading.Event()

        def _persist_loop():
            while not self._stop_event.is_set():
                try:
                    self._snapshot_working_to_longterm()
                except Exception:
                    logger.exception("Failed to snapshot working → longterm")
                self._stop_event.wait(interval)

        t = threading.Thread(target=_persist_loop, daemon=True, name="memory-auto-persist")
        t.start()
        return t

    def stop_persist(self) -> None:
        """Signal the auto-persist background thread to stop."""
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    def _snapshot_working_to_longterm(self, buffer_seconds: int = 3600) -> int:
        """Copy near-expiry working entries to longterm tier.

        Selects entries expiring within `buffer_seconds` from now to avoid
        a race condition with clear_expired().
        """
        now = self._now()
        rows = self._conn.execute(
            "SELECT * FROM memories WHERE tier = 'working' AND expires_at IS NOT NULL AND expires_at < ?",
            (now + buffer_seconds,),
        ).fetchall()
        count = 0
        for row in rows:
            self._conn.execute(
                """INSERT OR REPLACE INTO memories
                   (id, tier, project, key, content, content_hash, metadata,
                    created_at, accessed_at, expires_at, access_count)
                   VALUES (?, 'longterm', ?, ?, ?, ?, ?, ?, ?, NULL, ?)""",
                (row["id"], row["project"], row["key"], row["content"],
                 row["content_hash"], row["metadata"], row["created_at"],
                 now, row["access_count"]),
            )
            count += 1
        if count:
            self._conn.commit()
        return count

    def __enter__(self) -> "MemoryManager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
