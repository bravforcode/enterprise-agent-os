"""Tests for storage backends (Postgres + Qdrant)."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import sys
from pathlib import Path
ROOT = Path(r"C:\Users\menum\enterprise-agent-os")
sys.path.insert(0, str(ROOT / "src"))


class TestInMemoryCache:
    @pytest.mark.asyncio
    async def test_set_get(self):
        from graxia_tool.storage import InMemoryCacheBackend
        cache = InMemoryCacheBackend()
        await cache.set("k1", "v1")
        v = await cache.get("k1")
        assert v == "v1"

    @pytest.mark.asyncio
    async def test_miss(self):
        from graxia_tool.storage import InMemoryCacheBackend
        cache = InMemoryCacheBackend()
        v = await cache.get("missing")
        assert v is None
        assert cache.misses == 1

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        from graxia_tool.storage import InMemoryCacheBackend
        cache = InMemoryCacheBackend()
        await cache.set("k", "v", ttl=0)
        await asyncio.sleep(0.05)
        v = await cache.get("k")
        assert v is None

    @pytest.mark.asyncio
    async def test_delete(self):
        from graxia_tool.storage import InMemoryCacheBackend
        cache = InMemoryCacheBackend()
        await cache.set("k", "v")
        await cache.delete("k")
        v = await cache.get("k")
        assert v is None

    @pytest.mark.asyncio
    async def test_stats(self):
        from graxia_tool.storage import InMemoryCacheBackend
        cache = InMemoryCacheBackend()
        await cache.set("k1", "v1")
        await cache.get("k1")
        await cache.get("missing")
        stats = await cache.stats()
        assert stats["backend"] == "in_memory"
        assert stats["hits"] == 1
        assert stats["misses"] == 1


class TestPostgresCache:
    @pytest.mark.asyncio
    async def test_factory_returns_postgres(self):
        from graxia_tool.storage import create_cache_backend, PostgresCacheBackend
        b = create_cache_backend("postgres")
        assert isinstance(b, PostgresCacheBackend)

    @pytest.mark.asyncio
    async def test_factory_returns_inmemory(self):
        from graxia_tool.storage import create_cache_backend, InMemoryCacheBackend
        b = create_cache_backend("memory")
        assert isinstance(b, InMemoryCacheBackend)

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully(self):
        from graxia_tool.storage import PostgresCacheBackend
        # Use bad DSN so connect fails fast
        b = PostgresCacheBackend(dsn="postgresql://bad:bad@127.0.0.1:1/none")
        result = await b.connect()
        assert result is False
        assert b.connected is False

    @pytest.mark.asyncio
    async def test_get_when_not_connected(self):
        from graxia_tool.storage import PostgresCacheBackend
        b = PostgresCacheBackend()
        # Without connect, get returns None
        v = await b.get("anything")
        assert v is None


class TestInMemoryMemory:
    @pytest.mark.asyncio
    async def test_add_search(self):
        from graxia_tool.storage import InMemoryMemoryBackend, MemoryRecord
        m = InMemoryMemoryBackend()
        await m.add(MemoryRecord(id="1", text="Python is great for data science", metadata={}))
        await m.add(MemoryRecord(id="2", text="Rust is fast and memory safe", metadata={}))
        results = await m.search("python data", top_k=1)
        assert len(results) == 1
        assert "Python" in results[0].text

    @pytest.mark.asyncio
    async def test_empty_search(self):
        from graxia_tool.storage import InMemoryMemoryBackend
        m = InMemoryMemoryBackend()
        results = await m.search("nothing here")
        assert results == []

    @pytest.mark.asyncio
    async def test_stats(self):
        from graxia_tool.storage import InMemoryMemoryBackend, MemoryRecord
        m = InMemoryMemoryBackend()
        await m.add(MemoryRecord(id="1", text="hello", metadata={}))
        stats = await m.stats()
        assert stats["size"] == 1


class TestQdrantMemory:
    @pytest.mark.asyncio
    async def test_factory_returns_qdrant(self):
        from graxia_tool.storage import create_memory_backend, QdrantMemoryBackend
        b = create_memory_backend("qdrant")
        assert isinstance(b, QdrantMemoryBackend)

    @pytest.mark.asyncio
    async def test_factory_returns_inmemory(self):
        from graxia_tool.storage import create_memory_backend, InMemoryMemoryBackend
        b = create_memory_backend("memory")
        assert isinstance(b, InMemoryMemoryBackend)

    @pytest.mark.asyncio
    async def test_connect_fails_gracefully(self):
        from graxia_tool.storage import QdrantMemoryBackend
        # Use an unreachable IP to force failure
        b = QdrantMemoryBackend(url="http://192.0.2.1:1")  # TEST-NET
        result = await b.connect()
        assert result is False
        assert b.connected is False

    @pytest.mark.asyncio
    async def test_add_without_embedding_skipped(self):
        from graxia_tool.storage import QdrantMemoryBackend, MemoryRecord
        b = QdrantMemoryBackend()
        # Without connect, this should be a no-op
        await b.add(MemoryRecord(id="1", text="x", metadata={}))

    @pytest.mark.asyncio
    async def test_search_when_disconnected(self):
        from graxia_tool.storage import QdrantMemoryBackend
        b = QdrantMemoryBackend()
        results = await b.search("x")
        assert results == []


class TestStorageIntegration:
    @pytest.mark.asyncio
    async def test_cache_factory_auto(self):
        from graxia_tool.storage import create_cache_backend
        b = create_cache_backend("auto")
        # Auto defaults to Postgres (which falls back gracefully)
        assert b is not None

    @pytest.mark.asyncio
    async def test_memory_factory_auto(self):
        from graxia_tool.storage import create_memory_backend
        b = create_memory_backend("auto")
        assert b is not None
