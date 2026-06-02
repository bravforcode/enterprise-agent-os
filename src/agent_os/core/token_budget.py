"""Enterprise Agent OS — Token Budget Manager.

Enforces per-turn and per-day token limits.
Tracks cumulative usage per user/session.
Blocks execution when budget exceeded.
"""
from __future__ import annotations
import time
import json
from datetime import datetime, date
from dataclasses import dataclass, field
from typing import Any, Optional
import redis.asyncio as aioredis

from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger("token_budget")


@dataclass
class BudgetStatus:
    """Current budget status."""
    turn_used: int
    turn_remaining: int
    turn_limit: int
    day_used: int
    day_remaining: int
    day_limit: int
    over_turn_budget: bool
    over_day_budget: bool
    estimated_cost: float


class TokenBudgetManager:
    """
    Manages token budgets using Redis for fast lookup.

    Keys:
    - aos:budget:turn:{session_id} — tokens used this turn
    - aos:budget:day:{user_id}:{date} — tokens used today
    - aos:budget:cost:{user_id}:{date} — cost incurred today
    """

    def __init__(self, redis_url: str | None = None):
        self.redis_url = redis_url or settings.redis_url
        self._redis: Optional[aioredis.Redis] = None
        self.turn_limit = settings.token_budget_per_turn
        self.day_limit = settings.token_budget_per_day

    async def get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(self.redis_url)
        return self._redis

    async def check_budget(
        self, user_id: str, session_id: str, estimated_tokens: int = 0
    ) -> BudgetStatus:
        """Check if operation is within budget."""
        r = await self.get_redis()
        today = date.today().isoformat()

        # Get current usage
        turn_key = f"aos:budget:turn:{session_id}"
        day_key = f"aos:budget:day:{user_id}:{today}"
        cost_key = f"aos:budget:cost:{user_id}:{today}"

        turn_used = int(await r.get(turn_key) or 0)
        day_used = int(await r.get(day_key) or 0)
        cost = float(await r.get(cost_key) or 0)

        over_turn = (turn_used + estimated_tokens) > self.turn_limit
        over_day = (day_used + estimated_tokens) > self.day_limit

        return BudgetStatus(
            turn_used=turn_used,
            turn_remaining=max(0, self.turn_limit - turn_used),
            turn_limit=self.turn_limit,
            day_used=day_used,
            day_remaining=max(0, self.day_limit - day_used),
            day_limit=self.day_limit,
            over_turn_budget=over_turn,
            over_day_budget=over_day,
            estimated_cost=cost,
        )

    async def consume(
        self,
        user_id: str,
        session_id: str,
        tokens: int,
        cost: float = 0.0,
    ) -> BudgetStatus:
        """Consume tokens from budget."""
        r = await self.get_redis()
        today = date.today().isoformat()

        turn_key = f"aos:budget:turn:{session_id}"
        day_key = f"aos:budget:day:{user_id}:{today}"
        cost_key = f"aos:budget:cost:{user_id}:{today}"

        # Increment counters
        pipe = r.pipeline()
        pipe.incrby(turn_key, tokens)
        pipe.expire(turn_key, 300)  # 5 min TTL for turn
        pipe.incrby(day_key, tokens)
        pipe.expire(day_key, 86400 * 2)  # 2 days TTL
        pipe.incrbyfloat(cost_key, cost)
        pipe.expire(cost_key, 86400 * 2)
        await pipe.execute()

        status = await self.check_budget(user_id, session_id)
        if status.over_turn_budget:
            logger.warning("turn_budget_exceeded", user_id=user_id, used=status.turn_used, limit=status.turn_limit)
        if status.over_day_budget:
            logger.warning("day_budget_exceeded", user_id=user_id, used=status.day_used, limit=status.day_limit)

        return status

    async def reset_turn(self, session_id: str) -> None:
        """Reset turn budget (new turn started)."""
        r = await self.get_redis()
        turn_key = f"aos:budget:turn:{session_id}"
        await r.delete(turn_key)

    async def get_stats(self, user_id: str) -> dict[str, Any]:
        """Get budget stats for user."""
        r = await self.get_redis()
        today = date.today().isoformat()
        day_key = f"aos:budget:day:{user_id}:{today}"
        cost_key = f"aos:budget:cost:{user_id}:{today}"

        day_used = int(await r.get(day_key) or 0)
        cost = float(await r.get(cost_key) or 0)

        return {
            "day_used": day_used,
            "day_limit": self.day_limit,
            "day_remaining": max(0, self.day_limit - day_used),
            "cost_usd": cost,
        }
