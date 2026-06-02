"""Audit logging with Postgres persistence.

Provides:
- AuditLogger with in-memory and Postgres backends
- Audit events for security, access, cost, errors
- Query interface for audit logs
- Integration with metrics
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

from .metrics import record_audit


@dataclass
class AuditEvent:
    """Single audit log entry."""
    timestamp: float
    event_type: str  # login, agent_run, secret_detected, cost_alert, etc.
    user_id: Optional[str] = None
    tenant_id: Optional[str] = None
    resource: Optional[str] = None
    action: Optional[str] = None
    result: str = "success"  # success, failure, blocked
    ip_address: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class AuditLogger:
    """Audit logger with optional Postgres persistence.

    Backends:
    - "memory": in-memory list (default for tests)
    - "postgres": persistent storage via asyncpg
    """

    def __init__(
        self,
        backend: str = "memory",
        max_memory: int = 10000,
        db_url: Optional[str] = None,
    ):
        self.backend = backend
        self.max_memory = max_memory
        self._events: list[AuditEvent] = []
        self._db_pool = None
        self.db_url = db_url

    def log(
        self,
        event_type: str,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        resource: Optional[str] = None,
        action: Optional[str] = None,
        result: str = "success",
        ip_address: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AuditEvent:
        """Log an audit event."""
        event = AuditEvent(
            timestamp=time.time(),
            event_type=event_type,
            user_id=user_id,
            tenant_id=tenant_id,
            resource=resource,
            action=action,
            result=result,
            ip_address=ip_address,
            metadata=metadata or {},
        )

        # Always store in memory
        self._events.append(event)
        if len(self._events) > self.max_memory:
            self._events = self._events[-self.max_memory:]

        # Record metric
        record_audit(event_type, result)

        # Persist to DB if configured
        if self.backend == "postgres" and self._db_pool is not None:
            self._persist_to_db(event)

        return event

    def query(
        self,
        event_type: Optional[str] = None,
        user_id: Optional[str] = None,
        limit: int = 100,
        since_timestamp: Optional[float] = None,
    ) -> list[AuditEvent]:
        """Query audit events."""
        events = self._events
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        if since_timestamp is not None:
            events = [e for e in events if e.timestamp >= since_timestamp]
        return events[-limit:]

    def get_stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        if not self._events:
            return {"total": 0, "by_type": {}, "by_result": {}}

        by_type: dict[str, int] = {}
        by_result: dict[str, int] = {}
        for event in self._events:
            by_type[event.event_type] = by_type.get(event.event_type, 0) + 1
            by_result[event.result] = by_result.get(event.result, 0) + 1

        return {
            "total": len(self._events),
            "by_type": by_type,
            "by_result": by_result,
            "oldest": self._events[0].timestamp,
            "newest": self._events[-1].timestamp,
        }

    async def connect_db(self, db_url: Optional[str] = None):
        """Connect to Postgres for persistence."""
        try:
            import asyncpg
        except ImportError:
            raise RuntimeError("asyncpg not installed, run: pip install asyncpg")

        self.db_url = db_url or self.db_url
        if not self.db_url:
            raise ValueError("db_url required for postgres backend")

        self._db_pool = await asyncpg.create_pool(self.db_url, min_size=1, max_size=5)

        # Ensure table exists
        async with self._db_pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id BIGSERIAL PRIMARY KEY,
                    timestamp DOUBLE PRECISION NOT NULL,
                    event_type TEXT NOT NULL,
                    user_id TEXT,
                    tenant_id TEXT,
                    resource TEXT,
                    action TEXT,
                    result TEXT,
                    ip_address TEXT,
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_type
                    ON audit_log(event_type)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_user
                    ON audit_log(user_id)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                    ON audit_log(timestamp)
            """)

    def _persist_to_db(self, event: AuditEvent) -> None:
        """Persist event to DB (sync wrapper around async)."""
        if self._db_pool is None:
            return
        # For simplicity, use sync insert
        # In production, this would be batched/async
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule for later
                asyncio.create_task(self._async_persist(event))
            else:
                loop.run_until_complete(self._async_persist(event))
        except Exception:
            pass  # Don't fail audit on DB error

    async def _async_persist(self, event: AuditEvent) -> None:
        """Async persist to DB."""
        if self._db_pool is None:
            return
        try:
            async with self._db_pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO audit_log
                    (timestamp, event_type, user_id, tenant_id, resource, action, result, ip_address, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    event.timestamp,
                    event.event_type,
                    event.user_id,
                    event.tenant_id,
                    event.resource,
                    event.action,
                    event.result,
                    event.ip_address,
                    json.dumps(event.metadata),
                )
        except Exception:
            pass  # Log error but don't fail

    async def close_db(self):
        """Close DB connection."""
        if self._db_pool is not None:
            await self._db_pool.close()
            self._db_pool = None

    def clear(self):
        """Clear in-memory events (for testing)."""
        self._events = []


# Singleton
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    """Get global audit logger."""
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
