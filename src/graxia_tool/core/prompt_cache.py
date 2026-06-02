"""Enterprise Agent OS — Prompt Cache.

Caches LLM responses for identical/similar prompts.
Reduces token usage and latency.
"""
from __future__ import annotations
import json
import hashlib
from typing import Any, Optional
import redis.asyncio as aioredis

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger("prompt_cache")


class PromptCache:
    """
    Caches LLM responses by prompt hash.
    Reduces repeated LLM calls for identical queries.
    """

    def __init__(self, redis_url: str | None = None, ttl_seconds: int = 3600):
        self.redis_url = redis_url or settings.redis_url
        self.ttl = ttl_seconds
        self._redis: Optional[aioredis.Redis] = None
        self._hits = 0
        self._misses = 0

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url)
        return self._redis

    def _hash_prompt(self, prompt: str, model: str = "") -> str:
        """Hash prompt + model for cache key."""
        content = f"{model}:{prompt}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def get(self, prompt: str, model: str = "") -> Optional[dict[str, Any]]:
        """Get cached response."""
        r = await self.get_redis()
        key = f"aos:cache:prompt:{model}:{self._hash_prompt(prompt, model)}"
        data = await r.get(key)
        if data:
            self._hits += 1
            logger.debug("cache_hit", key=key[:20])
            return json.loads(data)
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
        r = await self.get_redis()
        key = f"aos:cache:prompt:{model}:{self._hash_prompt(prompt, model)}"
        await r.set(
            key,
            json.dumps(response, ensure_ascii=False),
            ex=ttl or self.ttl,
        )

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
        # Compute
        result = await compute_func(prompt)
        # Cache
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
