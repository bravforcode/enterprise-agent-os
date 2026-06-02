"""Enterprise Agent OS — Cost Ledger.

Tracks cost per user, per run, per day.
Provides cost analytics and alerts.
"""
from __future__ import annotations
import uuid
from datetime import datetime, date
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..core.models import TokenLedger, AgentRun
from ..core.database import async_session_factory
from ..core.logging import get_logger

logger = get_logger("cost_ledger")


class CostLedger:
    """
    Tracks and analyzes costs across runs, users, models.
    """

    async def record(
        self,
        run_id: uuid.UUID,
        model: str,
        tokens_input: int,
        tokens_output: int,
        cost_usd: float,
        cached: bool = False,
    ) -> None:
        """Record a cost entry."""
        async with async_session_factory() as db:
            entry = TokenLedger(
                id=uuid.uuid4(),
                run_id=run_id,
                model=model,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                cost_usd=cost_usd,
                cached=cached,
            )
            db.add(entry)
            await db.commit()
        logger.debug(
            "cost_recorded",
            run_id=str(run_id),
            model=model,
            cost=cost_usd,
        )

    async def get_user_costs_today(self, user_id: uuid.UUID) -> dict[str, Any]:
        """Get total cost for user today."""
        async with async_session_factory() as db:
            today = date.today()
            result = await db.execute(
                select(
                    func.sum(TokenLedger.cost_usd),
                    func.sum(TokenLedger.tokens_input),
                    func.sum(TokenLedger.tokens_output),
                    func.count(TokenLedger.id),
                )
                .join(AgentRun, AgentRun.id == TokenLedger.run_id)
                .join("sessions", "sessions.id == AgentRun.session_id")
                .where("sessions.user_id == :user_id")
                .where(func.date(TokenLedger.created_at) == today)
                .params(user_id=str(user_id))
            )
            row = result.first()
            return {
                "cost_usd": float(row[0] or 0),
                "tokens_input": int(row[1] or 0),
                "tokens_output": int(row[2] or 0),
                "run_count": int(row[3] or 0),
            }

    async def get_costs_by_model(
        self, days: int = 7
    ) -> list[dict[str, Any]]:
        """Get cost breakdown by model."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(
                    TokenLedger.model,
                    func.sum(TokenLedger.cost_usd).label("total_cost"),
                    func.sum(TokenLedger.tokens_input + TokenLedger.tokens_output).label("total_tokens"),
                    func.count(TokenLedger.id).label("calls"),
                )
                .where(TokenLedger.created_at >= func.now() - func.make_interval(0, 0, 0, days))
                .group_by(TokenLedger.model)
                .order_by(func.sum(TokenLedger.cost_usd).desc())
            )
            return [
                {
                    "model": row.model,
                    "total_cost": float(row.total_cost),
                    "total_tokens": int(row.total_tokens),
                    "calls": int(row.calls),
                }
                for row in result
            ]

    async def get_costs_by_day(
        self, days: int = 30
    ) -> list[dict[str, Any]]:
        """Get daily cost totals."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(
                    func.date(TokenLedger.created_at).label("day"),
                    func.sum(TokenLedger.cost_usd).label("total_cost"),
                    func.sum(TokenLedger.tokens_input + TokenLedger.tokens_output).label("total_tokens"),
                )
                .where(TokenLedger.created_at >= func.now() - func.make_interval(0, 0, 0, days))
                .group_by(func.date(TokenLedger.created_at))
                .order_by(func.date(TokenLedger.created_at).desc())
            )
            return [
                {
                    "day": str(row.day),
                    "total_cost": float(row.total_cost),
                    "total_tokens": int(row.total_tokens),
                }
                for row in result
            ]
