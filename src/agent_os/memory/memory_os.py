"""Enterprise Agent OS — Memory OS.

Unified memory system with 8 layers.
- Working memory: ephemeral (Redis)
- Short-term: session-level (Redis + DB)
- Long-term: persistent facts (DB + Qdrant)
- Episodic: past events (DB)
- Semantic: concepts (Qdrant)
- Procedural: how-to (DB)
- Failure: mistakes to avoid (DB)
- Preference: user prefs (DB)

All memories are:
- Decay over time (Ebbinghaus curve)
- Accessed-counted (popular memories stay)
- Embedding-indexed (Qdrant for semantic search)
"""
from __future__ import annotations
import uuid
import time
import math
import json
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func

from ..core.models import MemoryEntry
from ..core.database import async_session_factory
from ..core.logging import get_logger
from .layers import MemoryLayer, LAYER_CONFIG

logger = get_logger("memory_os")


class MemoryOS:
    """
    Memory OS — manages 8 memory layers.
    """

    def __init__(self, redis_url: str | None = None, qdrant_url: str | None = None):
        self.redis_url = redis_url
        self.qdrant_url = qdrant_url
        self._redis = None
        self._qdrant = None

    # --- Store ---
    async def store(
        self,
        user_id: uuid.UUID,
        layer: MemoryLayer,
        content: str,
        extra: Optional[dict[str, Any]] = None,
        embedding: Optional[list[float]] = None,
        expires_at: Optional[datetime] = None,
    ) -> uuid.UUID:
        """
        Store a memory entry.

        Args:
            user_id: User who owns this memory
            layer: Which of 8 layers
            content: The memory text
            extra: Additional metadata
            embedding: Optional pre-computed embedding (for Qdrant)
            expires_at: When this memory expires (optional)

        Returns:
            Memory ID
        """
        memory_id = uuid.uuid4()
        config = LAYER_CONFIG[layer]

        # Determine TTL
        if expires_at is None and config["ttl_seconds"] > 0:
            expires_at = datetime.utcnow().timestamp() + config["ttl_seconds"]

        # Store in DB
        async with async_session_factory() as db:
            entry = MemoryEntry(
                id=memory_id,
                user_id=user_id,
                layer=layer.value,
                content=content,
                extra_data=extra or {},
                embedding_id=str(memory_id) if embedding else None,
                created_at=datetime.utcnow(),
                expires_at=expires_at,
            )
            db.add(entry)
            await db.commit()

        # Also store in Redis if it's working/short-term
        if layer in (MemoryLayer.WORKING, MemoryLayer.SHORT_TERM):
            await self._store_redis(user_id, layer, memory_id, content, extra)

        # Also store embedding in Qdrant if provided
        if embedding and layer in (MemoryLayer.LONG_TERM, MemoryLayer.SEMANTIC):
            await self._store_qdrant(layer, memory_id, embedding, content)

        logger.info(
            "memory_stored",
            id=str(memory_id),
            user=str(user_id),
            layer=layer.value,
        )
        return memory_id

    # --- Recall ---
    async def recall(
        self,
        user_id: uuid.UUID,
        query: str,
        layers: Optional[list[MemoryLayer]] = None,
        top_k: int = 5,
        query_embedding: Optional[list[float]] = None,
    ) -> list[dict[str, Any]]:
        """
        Recall memories matching a query.

        If query_embedding is provided, uses vector search.
        Otherwise, uses keyword search.

        Returns:
            List of {id, layer, content, score, extra, created_at}
        """
        layers = layers or list(MemoryLayer)
        results: list[dict[str, Any]] = []

        # Vector search if embedding available
        if query_embedding and self.qdrant_url:
            results = await self._recall_qdrant(user_id, query_embedding, layers, top_k)
        else:
            # Keyword search via DB
            results = await self._recall_db(user_id, query, layers, top_k)

        # Apply decay scores
        for r in results:
            r["effective_score"] = r["score"] * self._decay(r["created_at"], r.get("access_count", 0))

        # Sort by effective score
        results.sort(key=lambda x: -x["effective_score"])
        return results[:top_k]

    async def _recall_db(
        self,
        user_id: uuid.UUID,
        query: str,
        layers: list[MemoryLayer],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Recall via DB keyword search."""
        layer_values = [l.value for l in layers]
        query_words = query.lower().split()

        async with async_session_factory() as db:
            result = await db.execute(
                select(MemoryEntry)
                .where(MemoryEntry.user_id == user_id)
                .where(MemoryEntry.layer.in_(layer_values))
                .order_by(MemoryEntry.created_at.desc())
                .limit(top_k * 5)  # oversample
            )
            entries = list(result.scalars().all())

        # Score by keyword overlap
        scored = []
        for entry in entries:
            content_words = entry.content.lower().split()
            overlap = sum(1 for w in query_words if w in content_words)
            if overlap > 0:
                scored.append({
                    "id": str(entry.id),
                    "layer": entry.layer,
                    "content": entry.content,
                    "score": overlap / max(len(query_words), 1),
                    "access_count": entry.access_count,
                    "created_at": entry.created_at,
                    "extra": entry.extra_data,
                })
        return scored[:top_k]

    # --- Update access ---
    async def access(self, memory_id: uuid.UUID) -> None:
        """Increment access count + update last_accessed."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(MemoryEntry).where(MemoryEntry.id == memory_id)
            )
            entry = result.scalar_one_or_none()
            if entry:
                entry.access_count = (entry.access_count or 0) + 1
                entry.last_accessed = datetime.utcnow()
                await db.commit()

    # --- Forget ---
    async def forget(
        self,
        user_id: uuid.UUID,
        memory_id: Optional[uuid.UUID] = None,
        layer: Optional[MemoryLayer] = None,
        older_than_days: Optional[int] = None,
    ) -> int:
        """Forget memories. Returns count deleted."""
        async with async_session_factory() as db:
            query = delete(MemoryEntry).where(MemoryEntry.user_id == user_id)
            if memory_id:
                query = query.where(MemoryEntry.id == memory_id)
            if layer:
                query = query.where(MemoryEntry.layer == layer.value)
            if older_than_days:
                cutoff = datetime.utcnow().timestamp() - (older_than_days * 86400)
                query = query.where(MemoryEntry.created_at < cutoff)
            result = await db.execute(query)
            await db.commit()
            count = result.rowcount
        logger.info("memory_forgotten", user=str(user_id), count=count)
        return count

    # --- Stats ---
    async def get_stats(self, user_id: uuid.UUID) -> dict[str, int]:
        """Get memory counts per layer for a user."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(MemoryEntry.layer, func.count(MemoryEntry.id))
                .where(MemoryEntry.user_id == user_id)
                .group_by(MemoryEntry.layer)
            )
            stats = {row[0]: int(row[1]) for row in result}
        # Add zero counts for unused layers
        for layer in MemoryLayer:
            if layer.value not in stats:
                stats[layer.value] = 0
        return stats

    # --- Decay ---
    def _decay(
        self,
        created_at: datetime,
        access_count: int,
        half_life_days: float = 30.0,
    ) -> float:
        """Ebbinghaus decay curve with access boost."""
        if not created_at:
            return 1.0
        age_days = (datetime.utcnow() - created_at).total_seconds() / 86400
        decay = 0.5 ** (age_days / half_life_days)
        # Access boost: more accesses = slower decay
        boost = 1.0 + math.log1p(access_count) * 0.1
        return min(decay * boost, 1.0)

    # --- Redis helpers (working/short-term) ---
    async def _store_redis(
        self,
        user_id: uuid.UUID,
        layer: MemoryLayer,
        memory_id: uuid.UUID,
        content: str,
        extra: Optional[dict],
    ) -> None:
        """Store in Redis for fast access."""
        try:
            import redis.asyncio as aioredis
            if self._redis is None:
                self._redis = aioredis.from_url(self.redis_url or "redis://localhost:6379/0")
            ttl = LAYER_CONFIG[layer]["ttl_seconds"]
            key = f"aos:mem:{layer.value}:{user_id}:{memory_id}"
            value = json.dumps({
                "id": str(memory_id),
                "content": content,
                "extra": extra or {},
                "created_at": datetime.utcnow().isoformat(),
            })
            await self._redis.set(key, value, ex=ttl)
        except Exception as e:
            logger.warning("redis_store_failed", error=str(e))

    # --- Qdrant helpers (long-term/semantic) ---
    async def _store_qdrant(
        self,
        layer: MemoryLayer,
        memory_id: uuid.UUID,
        embedding: list[float],
        content: str,
    ) -> None:
        """Store embedding in Qdrant."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import PointStruct
            if self._qdrant is None:
                self._qdrant = QdrantClient(url=self.qdrant_url or "http://localhost:6333")
            self._qdrant.upsert(
                collection_name="agent_memory",
                points=[PointStruct(
                    id=str(memory_id),
                    vector=embedding,
                    payload={"layer": layer.value, "content": content},
                )],
            )
        except Exception as e:
            logger.warning("qdrant_store_failed", error=str(e))

    async def _recall_qdrant(
        self,
        user_id: uuid.UUID,
        embedding: list[float],
        layers: list[MemoryLayer],
        top_k: int,
    ) -> list[dict[str, Any]]:
        """Recall via Qdrant vector search."""
        try:
            from qdrant_client import QdrantClient
            if self._qdrant is None:
                self._qdrant = QdrantClient(url=self.qdrant_url or "http://localhost:6333")
            layer_values = [l.value for l in layers]
            results = self._qdrant.search(
                collection_name="agent_memory",
                query_vector=embedding,
                query_filter={"must": [{"key": "layer", "match": {"any": layer_values}}]},
                limit=top_k,
            )
            return [
                {
                    "id": str(r.id),
                    "layer": r.payload.get("layer", ""),
                    "content": r.payload.get("content", ""),
                    "score": r.score,
                    "access_count": 0,
                    "created_at": datetime.utcnow(),
                    "extra": {},
                }
                for r in results
            ]
        except Exception as e:
            logger.warning("qdrant_recall_failed", error=str(e))
            return []
