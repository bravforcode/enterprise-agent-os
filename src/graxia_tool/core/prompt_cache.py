"""Enterprise Agent OS — Prompt Cache.

Caches LLM responses for identical/similar prompts.
Reduces token usage and latency.
Uses in-memory dict when redis is unavailable (zero-install mode).
"""
from __future__ import annotations
import json
import hashlib
import time
from typing import Any, Optional

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger("prompt_cache")

# Try redis, fall back to in-memory
try:
    import redis.asyncio as aioredis
    _REDIS_AVAILABLE = True
except ImportError:
    aioredis = None  # type: ignore
    _REDIS_AVAILABLE = False


class PromptCache:
    """
    Caches LLM responses by prompt hash.
    Uses Redis if available, otherwise in-memory dict.
    """

    def __init__(self, redis_url: str | None = None, ttl_seconds: int = 3600):
        self.redis_url = redis_url or settings.redis_url
        self.ttl = ttl_seconds
        self._redis = None
        self._memory: dict[str, tuple[str, float]] = {}  # key -> (json_str, expiry)
        self._hits = 0
        self._misses = 0

    async def get_redis(self):
        if self._redis is None and _REDIS_AVAILABLE:
            try:
                self._redis = aioredis.from_url(self.redis_url)
            except Exception:
                pass
        return self._redis

    def _hash_prompt(self, prompt: str, model: str = "") -> str:
        """Hash prompt + model for cache key."""
        content = f"{model}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def get(self, prompt: str, model: str = "") -> Optional[dict[str, Any]]:
        """Get cached response."""
        key = f"aos:cache:prompt:{model}:{self._hash_prompt(prompt, model)}"

        # Try redis first
        r = await self.get_redis()
        if r is not None:
            try:
                data = await r.get(key)
                if data:
                    self._hits += 1
                    return json.loads(data)
            except Exception:
                pass

        # Fallback to in-memory
        if key in self._memory:
            json_str, expiry = self._memory[key]
            if expiry > time.time():
                self._hits += 1
                return json.loads(json_str)
            else:
                del self._memory[key]

        self._misses += 1
        return None

    async def set(
        self,
        prompt: str,
        response: dict[str, Any],
        model: str = "",
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a response."""
        key = f"aos:cache:prompt:{model}:{self._hash_prompt(prompt, model)}"
        data = json.dumps(response, ensure_ascii=False)
        exp = ttl or self.ttl

        # Try redis
        r = await self.get_redis()
        if r is not None:
            try:
                await r.set(key, data, ex=exp)
                return
            except Exception:
                pass

        # Fallback to in-memory
        self._memory[key] = (data, time.time() + exp)

    async def get_or_set(
        self,
        prompt: str,
        compute_func,
        model: str = "",
    ) -> tuple[dict[str, Any], bool]:
        """Get from cache or compute and cache."""
        cached = await self.get(prompt, model)
        if cached:
            return cached, True
        result = await compute_func(prompt)
        await self.set(prompt, result, model)
        return result, False

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total": total,
            "hit_rate": hit_rate,
        }
