"""Graxia Tool — Persistent storage backends.

Backends:
- PostgresCache: persistent cache for prompt cache (PostgreSQL)
- QdrantMemory: persistent vector memory (Qdrant)
- InMemoryCache / InMemoryMemory: dev/test fallbacks
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger("graxia_tool.storage")

POSTGRES_URL = os.environ.get("GRAXIA_POSTGRES_URL", "postgresql://graxia:graxia@127.0.0.1:5432/graxia")
QDRANT_URL = os.environ.get("GRAXIA_QDRANT_URL", "http://127.0.0.1:6333")


# =====================================================================
# Cache Backends
# =====================================================================

class CacheBackend:
    """Abstract cache interface — same as in-memory SemanticCache."""
    async def get(self, key: str) -> Optional[str]:
        raise NotImplementedError

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        raise NotImplementedError

    async def stats(self) -> Dict[str, Any]:
        raise NotImplementedError


class InMemoryCacheBackend(CacheBackend):
    """Fallback when Postgres is not available."""

    def __init__(self):
        self._store: Dict[str, str] = {}
        self._expiry: Dict[str, float] = {}
        self.hits = 0
        self.misses = 0

    async def get(self, key: str) -> Optional[str]:
        if key in self._expiry and time.time() > self._expiry[key]:
            del self._store[key]
            del self._expiry[key]
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        return None

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        self._store[key] = value
        self._expiry[key] = time.time() + ttl

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
        self._expiry.pop(key, None)

    async def stats(self) -> Dict[str, Any]:
        total = self.hits + self.misses
        return {
            "backend": "in_memory",
            "size": len(self._store),
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


class PostgresCacheBackend(CacheBackend):
    """PostgreSQL-backed cache for production persistence.

    Schema:
        cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            hit_count INTEGER DEFAULT 0
        )
    """

    def __init__(self, dsn: str = POSTGRES_URL):
        self.dsn = dsn
        self._pool: Optional[Any] = None
        self.connected = False

    async def connect(self) -> bool:
        if self.connected:
            return True
        try:
            import asyncpg  # type: ignore
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=5)
            assert self._pool is not None
            async with self._pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        expires_at DOUBLE PRECISION NOT NULL,
                        hit_count INTEGER DEFAULT 0
                    )
                """)
                await conn.execute("CREATE INDEX IF NOT EXISTS cache_expires ON cache(expires_at)")
            self.connected = True
            logger.info("Postgres cache connected: %s", self.dsn.split("@")[-1])
            return True
        except Exception as e:
            logger.warning("Postgres cache unavailable: %s", e)
            self.connected = False
            return False

    async def get(self, key: str) -> Optional[str]:
        if not self.connected and not await self.connect():
            return None
        assert self._pool is not None
        try:
            async with self._pool.acquire() as conn:  # type: ignore
                row = await conn.fetchrow(
                    "SELECT value, expires_at FROM cache WHERE key = $1", key
                )
                if row is None:
                    return None
                if time.time() > row["expires_at"]:
                    await conn.execute("DELETE FROM cache WHERE key = $1", key)
                    return None
                await conn.execute(
                    "UPDATE cache SET hit_count = hit_count + 1 WHERE key = $1", key
                )
                return row["value"]
        except Exception as e:
            logger.error("Postgres get failed: %s", e)
            return None

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        if not self.connected and not await self.connect():
            return
        assert self._pool is not None
        try:
            async with self._pool.acquire() as conn:  # type: ignore
                await conn.execute("""
                    INSERT INTO cache (key, value, expires_at) VALUES ($1, $2, $3)
                    ON CONFLICT (key) DO UPDATE SET value = $2, expires_at = $3
                """, key, value, time.time() + ttl)
        except Exception as e:
            logger.error("Postgres set failed: %s", e)

    async def delete(self, key: str) -> None:
        if not self.connected:
            return
        assert self._pool is not None
        try:
            async with self._pool.acquire() as conn:  # type: ignore
                await conn.execute("DELETE FROM cache WHERE key = $1", key)
        except Exception as e:
            logger.error("Postgres delete failed: %s", e)

    async def stats(self) -> Dict[str, Any]:
        if not self.connected:
            await self.connect()
        if not self.connected:
            return {"backend": "postgres", "connected": False}
        assert self._pool is not None
        async with self._pool.acquire() as conn:  # type: ignore
            count = await conn.fetchval("SELECT COUNT(*) FROM cache")
            hits = await conn.fetchval("SELECT COALESCE(SUM(hit_count), 0) FROM cache")
        return {
            "backend": "postgres",
            "connected": True,
            "size": count,
            "total_hits": hits,
        }

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
            self.connected = False


def create_cache_backend(prefer: str = "auto") -> CacheBackend:
    """Factory — picks Postgres if available, else in-memory."""
    if prefer == "postgres" or prefer == "auto":
        backend = PostgresCacheBackend()
        # Note: we don't connect here to avoid blocking; connect on first use
        return backend
    return InMemoryCacheBackend()


# =====================================================================
# Memory Backends (vector)
# =====================================================================

@dataclass
class MemoryRecord:
    id: str
    text: str
    metadata: Dict[str, Any]
    embedding: Optional[List[float]] = None


class MemoryBackend:
    """Abstract memory backend."""
    async def add(self, record: MemoryRecord) -> None:
        raise NotImplementedError

    async def search(self, query: str, top_k: int = 5) -> List[MemoryRecord]:
        raise NotImplementedError

    async def stats(self) -> Dict[str, Any]:
        raise NotImplementedError


class InMemoryMemoryBackend(MemoryBackend):
    """In-memory fallback for memory."""
    def __init__(self):
        self._records: List[MemoryRecord] = []
        self.hits = 0

    async def add(self, record: MemoryRecord) -> None:
        self._records.append(record)

    async def search(self, query: str, top_k: int = 5) -> List[MemoryRecord]:
        query_lower = query.lower()
        scored = []
        for r in self._records:
            score = sum(1 for w in query_lower.split() if w in r.text.lower())
            if score:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        self.hits += 1
        return [r for _, r in scored[:top_k]]

    async def stats(self) -> Dict[str, Any]:
        return {
            "backend": "in_memory",
            "size": len(self._records),
        }


class QdrantMemoryBackend(MemoryBackend):
    """Qdrant vector DB backend for persistent memory.

    Collection: graxia_memory
    Payload: {text, metadata}
    """

    def __init__(self, url: str = QDRANT_URL, collection: str = "graxia_memory"):
        self.url = url
        self.collection = collection
        self._client: Optional[Any] = None
        self.connected = False

    async def connect(self) -> bool:
        if self.connected:
            return True
        try:
            from qdrant_client import AsyncQdrantClient  # type: ignore
            from qdrant_client.models import Distance, VectorParams  # type: ignore
            from qdrant_client.http import AsyncApi  # type: ignore
            self._client = AsyncQdrantClient(url=self.url)
            # Ensure collection exists
            await self._client.create_collection(
                collection_name=self.collection,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )
            self.connected = True
            logger.info("Qdrant memory connected: %s", self.url)
            return True
        except Exception as e:
            # "Already exists" is not an error — but connection failure is
            err_str = str(e).lower()
            if "already exist" in err_str:
                self.connected = True
                logger.info("Qdrant memory connected (collection exists): %s", self.url)
                return True
            logger.warning("Qdrant memory unavailable: %s", e)
            self.connected = False
            self._client = None
            return False

    async def add(self, record: MemoryRecord) -> None:
        if not self.connected and not await self.connect():
            return
        if record.embedding is None:
            # Without embeddings, just store text — Qdrant needs vectors, so skip
            logger.debug("Skipping record %s (no embedding)", record.id)
            return
        assert self._client is not None
        try:
            from qdrant_client.models import PointStruct  # type: ignore
            await self._client.upsert(
                collection_name=self.collection,
                points=[
                    PointStruct(
                        id=hash(record.id) % (2**63),
                        vector=record.embedding,
                        payload={"text": record.text, "metadata": record.metadata},
                    )
                ],
            )
        except Exception as e:
            logger.error("Qdrant add failed: %s", e)

    async def search(self, query: str, top_k: int = 5) -> List[MemoryRecord]:
        # Without a real embedding model, fall back to text search via filter
        if not self.connected and not await self.connect():
            return []
        assert self._client is not None
        try:
            from qdrant_client.models import Filter, FieldCondition, MatchText  # type: ignore
            results = await self._client.scroll(
                collection_name=self.collection,
                scroll_filter=Filter(must=[
                    FieldCondition(key="text", match=MatchText(text=query))
                ]),
                limit=top_k,
            )
            return [
                MemoryRecord(
                    id=str(p.id),
                    text=p.payload.get("text", ""),
                    metadata=p.payload.get("metadata", {}),
                )
                for p in results[0]
            ]
        except Exception as e:
            logger.error("Qdrant search failed: %s", e)
            return []

    async def stats(self) -> Dict[str, Any]:
        if not self.connected:
            await self.connect()
        if not self.connected:
            return {"backend": "qdrant", "connected": False}
        assert self._client is not None
        try:
            info = await self._client.get_collection(self.collection)
            return {
                "backend": "qdrant",
                "connected": True,
                "url": self.url,
                "collection": self.collection,
                "vectors_count": info.vectors_count,
                "points_count": info.points_count,
            }
        except Exception as e:
            return {"backend": "qdrant", "connected": True, "error": str(e)}

    async def close(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None
            self.connected = False


def create_memory_backend(prefer: str = "auto") -> MemoryBackend:
    """Factory — picks Qdrant if available, else in-memory."""
    if prefer in ("qdrant", "auto"):
        return QdrantMemoryBackend()
    return InMemoryMemoryBackend()
