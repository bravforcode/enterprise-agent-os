"""Enterprise Agent OS — Run Logger.

Logs every agent run to DB + structured logs.
Tracks tokens, cost, duration, success/failure.
"""
from __future__ import annotations
import uuid
import time
from datetime import datetime
from typing import Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from ..core.models import AgentRun, RunStatus, TokenLedger, Session
from ..core.database import async_session_factory
from ..core.logging import get_logger

logger = get_logger("run_logger")


class RunLogger:
    """
    Logs agent runs to database and structured logs.
    Provides analytics on runs, tokens, cost.
    """

    async def start_run(
        self,
        session_id: uuid.UUID,
        agent_type: str,
        user_query: str,
        classified_intent: str = "",
        classified_domain: str = "",
        risk_level: str = "low",
        parent_run_id: Optional[uuid.UUID] = None,
    ) -> AgentRun:
        """Create and log a new agent run."""
        run = AgentRun(
            id=uuid.uuid4(),
            session_id=session_id,
            parent_run_id=parent_run_id,
            agent_type=agent_type,
            status=RunStatus.RUNNING,
            risk_level=risk_level,
            user_query=user_query,
            classified_intent=classified_intent,
            classified_domain=classified_domain,
            started_at=datetime.utcnow(),
        )

        async with async_session_factory() as db:
            db.add(run)
            await db.commit()

        logger.info(
            "run_started",
            run_id=str(run.id),
            agent=agent_type,
            intent=classified_intent,
            risk=risk_level,
        )
        return run

    async def complete_run(
        self,
        run_id: uuid.UUID,
        status: RunStatus,
        result: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cost_usd: float = 0.0,
        model_used: str = "",
    ) -> None:
        """Update run with completion data."""
        async with async_session_factory() as db:
            result_obj = await db.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            run = result_obj.scalar_one_or_none()
            if not run:
                return

            run.status = status
            run.result = result
            run.error = error
            run.tokens_input = tokens_input
            run.tokens_output = tokens_output
            run.cost_usd = cost_usd
            run.model_used = model_used
            run.completed_at = datetime.utcnow()
            if run.started_at:
                run.duration_ms = int(
                    (run.completed_at - run.started_at).total_seconds() * 1000
                )

            # Log to token ledger
            if tokens_input > 0 or tokens_output > 0:
                ledger = TokenLedger(
                    run_id=run_id,
                    model=model_used,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    cost_usd=cost_usd,
                )
                db.add(ledger)

            await db.commit()

        logger.info(
            "run_completed",
            run_id=str(run_id),
            status=status.value,
            tokens_in=tokens_input,
            tokens_out=tokens_output,
            cost=cost_usd,
            ms=run.duration_ms,
        )

    async def log_step(
        self,
        run_id: uuid.UUID,
        step_id: str,
        action: str,
        status: str,
        result: Optional[dict[str, Any]] = None,
        duration_ms: int = 0,
    ) -> None:
        """Log a step within a run."""
        logger.info(
            "step_completed",
            run_id=str(run_id),
            step_id=step_id,
            action=action,
            status=status,
            ms=duration_ms,
        )

    async def get_run(self, run_id: uuid.UUID) -> Optional[AgentRun]:
        """Get a run by ID."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(AgentRun).where(AgentRun.id == run_id)
            )
            return result.scalar_one_or_none()

    async def get_runs(
        self,
        session_id: Optional[uuid.UUID] = None,
        status: Optional[RunStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentRun]:
        """Get runs with optional filters."""
        async with async_session_factory() as db:
            query = select(AgentRun)
            if session_id:
                query = query.where(AgentRun.session_id == session_id)
            if status:
                query = query.where(AgentRun.status == status)
            query = query.order_by(AgentRun.created_at.desc()).offset(offset).limit(limit)
            result = await db.execute(query)
            return list(result.scalars().all())

    async def get_stats(self, days: int = 7) -> dict[str, Any]:
        """Get run statistics for the last N days."""
        async with async_session_factory() as db:
            # Total runs
            total = await db.execute(select(func.count(AgentRun.id)))

            # By status
            status_counts = await db.execute(
                select(AgentRun.status, func.count(AgentRun.id))
                .group_by(AgentRun.status)
            )

            # Token usage
            token_stats = await db.execute(
                select(
                    func.sum(TokenLedger.tokens_input),
                    func.sum(TokenLedger.tokens_output),
                    func.sum(TokenLedger.cost_usd),
                )
            )

            # Average duration
            avg_duration = await db.execute(
                select(func.avg(AgentRun.duration_ms))
            )

            return {
                "total_runs": total.scalar() or 0,
                "by_status": {str(row[0]): row[1] for row in status_counts},
                "total_tokens_input": token_stats.scalar() or 0,
                "total_cost_usd": token_stats.scalar() or 0,
                "avg_duration_ms": avg_duration.scalar() or 0,
            }
