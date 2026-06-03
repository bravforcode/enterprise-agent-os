"""Cost optimization utilities.

Smart strategies to reduce LLM costs:
- Batch similar requests
- Cache frequent patterns
- Use cheaper models for simple tasks
- Compress prompts aggressively
- Share context across requests
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Awaitable

from ..core.logging import get_logger
from ..core.cost_ledger import CostLedger
from ..core.prompt_cache import PromptCache
from ..core.model_router import ModelRouter
from ..core.context_compressor import ContextCompressor
from ..observability.prometheus import record_cache, record_compression

logger = get_logger(__name__)


@dataclass
class OptimizationConfig:
    """Cost optimization configuration."""
    enable_batching: bool = True
    batch_size: int = 5
    batch_timeout_ms: int = 100
    enable_smart_cache: bool = True
    cache_ttl_seconds: int = 3600
    enable_compression: bool = True
    compression_threshold_tokens: int = 2000
    enable_model_downgrade: bool = True
    downgrade_confidence_threshold: float = 0.8
    enable_request_dedup: bool = True
    dedup_window_seconds: int = 5


@dataclass
class CostSavings:
    """Track cost savings."""
    cache_hits: int = 0
    cache_savings_usd: float = 0.0
    compression_savings_tokens: int = 0
    batched_requests: int = 0
    deduped_requests: int = 0
    downgraded_requests: int = 0
    total_savings_usd: float = 0.0
    period_start: datetime = field(default_factory=datetime.utcnow)


class CostOptimizer:
    """Orchestrates cost optimization strategies.

    Wraps an LLM call function and applies:
    - Request deduplication
    - Prompt caching
    - Batch processing
    - Model downgrade for simple tasks
    - Context compression
    """

    def __init__(
        self,
        config: OptimizationConfig | None = None,
        cost_ledger: CostLedger | None = None,
        prompt_cache: PromptCache | None = None,
        model_router: ModelRouter | None = None,
        compressor: ContextCompressor | None = None,
    ) -> None:
        self.config = config or OptimizationConfig()
        self.cost_ledger = cost_ledger
        self.prompt_cache = prompt_cache
        self.model_router = model_router or ModelRouter()
        self.compressor = compressor or ContextCompressor()
        self.savings = CostSavings()

        # In-flight request tracking (for dedup)
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._inflight_lock = asyncio.Lock()

        # Batch queue
        self._batch_queue: list[tuple[str, asyncio.Future[Any]]] = []
        self._batch_lock = asyncio.Lock()

    async def optimize_call(
        self,
        prompt: str,
        llm_func: Callable[[str, str], Awaitable[str]],
        agent_name: str = "default",
        force_model: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Optimize a single LLM call.

        Returns:
            (response, metadata) where metadata describes optimizations applied
        """
        metadata: dict[str, Any] = {
            "optimizations": [],
            "cache_hit": False,
            "compressed": False,
            "model_used": None,
        }

        # 1. Deduplication: check if identical prompt is in-flight
        if self.config.enable_request_dedup:
            prompt_hash = self._hash_prompt(prompt)
            async with self._inflight_lock:
                if prompt_hash in self._inflight:
                    self.savings.deduped_requests += 1
                    metadata["optimizations"].append("dedup")
                    logger.info("cost.dedup_hit", prompt_hash=prompt_hash[:8])
                    response = await self._inflight[prompt_hash]
                    return response, metadata

        # 2. Cache check
        if self.config.enable_smart_cache and self.prompt_cache:
            cache_key = self._hash_prompt(prompt)
            cached = self.prompt_cache.get(cache_key)
            # Handle both sync and async cache
            if asyncio.iscoroutine(cached):
                cached = await cached
            if cached is not None:
                self.savings.cache_hits += 1
                self.savings.cache_savings_usd += 0.001  # estimate
                metadata["cache_hit"] = True
                metadata["optimizations"].append("cache")
                record_cache("prompt", True)
                logger.info("cost.cache_hit", cache_key=cache_key[:8])
                return cached, metadata
            record_cache("prompt", False)

        # 3. Compression
        compressed_prompt = prompt
        if self.config.enable_compression:
            approx_tokens = len(prompt) // 4
            if approx_tokens > self.config.compression_threshold_tokens:
                compressed = self.compressor.compress(prompt)
                if compressed.was_compressed:
                    compressed_prompt = compressed.text
                    ratio = len(prompt) / max(len(compressed.text), 1)
                    self.savings.compression_savings_tokens += (
                        len(prompt) - len(compressed.text)
                    ) // 4
                    metadata["compressed"] = True
                    metadata["optimizations"].append("compression")
                    record_compression("lossy", ratio)
                    logger.info("cost.compressed", ratio=ratio)

        # 4. Model selection (downgrade for simple tasks)
        model = force_model
        if model is None and self.config.enable_model_downgrade:
            # Simple heuristic: short prompts → cheap model
            if len(compressed_prompt) < 500:
                model = "haiku"  # cheap model
                self.savings.downgraded_requests += 1
                metadata["optimizations"].append("model_downgrade")
            else:
                model = "main"
        metadata["model_used"] = model or "default"

        # 5. Execute
        # Register as in-flight for dedup
        prompt_hash = self._hash_prompt(prompt)
        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        async with self._inflight_lock:
            self._inflight[prompt_hash] = future

        try:
            response = await llm_func(model or "default", compressed_prompt)
            metadata["optimizations"].append("execute")
            # Cache result
            if self.config.enable_smart_cache and self.prompt_cache:
                set_result = self.prompt_cache.set(prompt_hash, response, ttl=self.config.cache_ttl_seconds)
                if asyncio.iscoroutine(set_result):
                    await set_result
            future.set_result(response)
            return response, metadata
        finally:
            async with self._inflight_lock:
                self._inflight.pop(prompt_hash, None)

    def _hash_prompt(self, prompt: str) -> str:
        """Hash a prompt for cache/dedup key."""
        return hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    def get_savings_report(self) -> dict[str, Any]:
        """Get current cost savings report."""
        return {
            "cache_hits": self.savings.cache_hits,
            "cache_savings_usd": self.savings.cache_savings_usd,
            "compression_savings_tokens": self.savings.compression_savings_tokens,
            "deduped_requests": self.savings.deduped_requests,
            "downgraded_requests": self.savings.downgraded_requests,
            "period_start": self.savings.period_start.isoformat(),
        }

    def reset_savings(self) -> None:
        """Reset savings counters."""
        self.savings = CostSavings()


# ============================================================
# Batch processor
# ============================================================

@dataclass
class BatchResult:
    """Result of a batched operation."""
    responses: list[Any]
    batch_size: int
    duration_ms: float


class BatchProcessor:
    """Batches similar requests to reduce LLM calls.

    Collects requests over a short window, then sends them as a single batch.
    Most LLM providers offer 50% discount on batched requests.
    """

    def __init__(
        self,
        batch_size: int = 5,
        batch_timeout_ms: int = 100,
    ) -> None:
        self.batch_size = batch_size
        self.batch_timeout_ms = batch_timeout_ms
        self._queue: list[tuple[str, asyncio.Future[Any]]] = []
        self._lock = asyncio.Lock()
        self._processing = False

    async def submit(
        self,
        item: str,
        batch_func: Callable[[list[str]], Awaitable[list[Any]]] | None = None,
    ) -> Any:
        """Submit an item to the batch.

        If batch_func is provided, batches will be processed via that function.
        Otherwise, returns the item as-is.
        """
        if batch_func is None:
            return item

        future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()
        async with self._lock:
            self._queue.append((item, future))
            should_flush = len(self._queue) >= self.batch_size

        if should_flush and not self._processing:
            asyncio.create_task(self._flush(batch_func))

        return await future

    async def _flush(
        self,
        batch_func: Callable[[list[str]], Awaitable[list[Any]]],
    ) -> None:
        """Flush the batch queue."""
        self._processing = True
        try:
            await asyncio.sleep(self.batch_timeout_ms / 1000.0)
            async with self._lock:
                if not self._queue:
                    return
                items, futures = zip(*self._queue)
                self._queue = []

            try:
                responses = await batch_func(list(items))
                for future, response in zip(futures, responses):
                    if not future.done():
                        future.set_result(response)
            except Exception as e:
                for future in futures:
                    if not future.done():
                        future.set_exception(e)
        finally:
            self._processing = False


# ============================================================
# Token budget manager
# ============================================================

@dataclass
class TokenBudget:
    """Per-user/per-day token budget enforcement."""
    user_id: str
    daily_limit: int
    per_request_limit: int
    used_today: int = 0
    last_reset: datetime = field(default_factory=datetime.utcnow)

    def can_spend(self, tokens: int) -> bool:
        """Check if user can spend this many tokens."""
        self._maybe_reset()
        if tokens > self.per_request_limit:
            return False
        return self.used_today + tokens <= self.daily_limit

    def spend(self, tokens: int) -> bool:
        """Spend tokens. Returns True if successful."""
        if not self.can_spend(tokens):
            return False
        self.used_today += tokens
        return True

    def _maybe_reset(self) -> None:
        """Reset daily counter at midnight."""
        now = datetime.utcnow()
        if now.date() > self.last_reset.date():
            self.used_today = 0
            self.last_reset = now

    def usage_pct(self) -> float:
        """Get current usage as percentage of daily limit."""
        if self.daily_limit == 0:
            return 0.0
        return self.used_today / self.daily_limit


class TokenBudgetManager:
    """Manages per-user token budgets."""

    DEFAULT_DAILY_LIMIT = 1_000_000
    DEFAULT_PER_REQUEST_LIMIT = 50_000

    def __init__(self) -> None:
        self.budgets: dict[str, TokenBudget] = {}

    def set_budget(
        self,
        user_id: str,
        daily_limit: int = DEFAULT_DAILY_LIMIT,
        per_request_limit: int = DEFAULT_PER_REQUEST_LIMIT,
    ) -> None:
        """Set budget for a user."""
        self.budgets[user_id] = TokenBudget(
            user_id=user_id,
            daily_limit=daily_limit,
            per_request_limit=per_request_limit,
        )

    def can_user_spend(self, user_id: str, tokens: int) -> bool:
        """Check if user can spend tokens."""
        if user_id not in self.budgets:
            self.set_budget(user_id)
        return self.budgets[user_id].can_spend(tokens)

    def record_spend(self, user_id: str, tokens: int) -> bool:
        """Record token spend. Returns True if within budget."""
        if user_id not in self.budgets:
            self.set_budget(user_id)
        return self.budgets[user_id].spend(tokens)

    def get_usage(self, user_id: str) -> dict[str, Any]:
        """Get usage for a user."""
        if user_id not in self.budgets:
            return {"user_id": user_id, "usage_pct": 0.0, "used_today": 0}
        b = self.budgets[user_id]
        return {
            "user_id": user_id,
            "used_today": b.used_today,
            "daily_limit": b.daily_limit,
            "per_request_limit": b.per_request_limit,
            "usage_pct": b.usage_pct(),
        }

    def get_all_usage(self) -> list[dict[str, Any]]:
        """Get usage for all users."""
        return [self.get_usage(uid) for uid in self.budgets]
