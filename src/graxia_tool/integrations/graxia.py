"""Agent OS — Peer service integration with Graxia OS.

Graxia OS runs at http://127.0.0.1:8000 (backend FastAPI).
Agent OS exposes its features as a peer service that Graxia can call.

This module:
- Authenticates with Graxia (JWT)
- Registers Agent OS endpoints
- Bridges Graxia's existing 4 agents (scoring, drafting, learning, sync)
  with Agent OS's 15 sub-agents
- Shares cost / cache / events between systems
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

logger = logging.getLogger("graxia_tool.graxia")


@dataclass
class GraxiaConfig:
    """Configuration for connecting to Graxia OS."""
    base_url: str = "http://127.0.0.1:8000"
    api_prefix: str = "/api/v1"
    jwt_token: Optional[str] = None
    timeout_seconds: float = 30.0
    enabled: bool = True

    @classmethod
    def from_env(cls) -> "GraxiaConfig":
        return cls(
            base_url=os.environ.get("GRAXIA_BASE_URL", "http://127.0.0.1:8000"),
            api_prefix=os.environ.get("GRAXIA_API_PREFIX", "/api/v1"),
            jwt_token=os.environ.get("GRAXIA_JWT_TOKEN"),
            timeout_seconds=float(os.environ.get("GRAXIA_TIMEOUT", "30")),
            enabled=os.environ.get("GRAXIA_ENABLED", "true").lower() in ("1", "true", "yes"),
        )


# Mapping: Graxia agent → Agent OS sub-agent
GRAXIA_TO_AGENT_OS = {
    "scoring": "data_engineer",
    "drafting": "documenter",
    "learning": "researcher",
    "sync": "sysadmin",
}


class GraxiaBridge:
    """Bridge Agent OS to Graxia OS backend.

    Use this when you want to:
    - Forward Graxia agent invocations to Agent OS
    - Share auth/session with Graxia
    - Subscribe to Graxia's event bus
    """

    def __init__(self, config: Optional[GraxiaConfig] = None):
        self.config = config or GraxiaConfig.from_env()
        self._session: Optional[Any] = None

    @property
    def is_enabled(self) -> bool:
        return self.config.enabled

    async def _ensure_session(self) -> Any:
        """Lazy-init aiohttp ClientSession."""
        if self._session is None:
            try:
                import aiohttp  # type: ignore
            except ImportError:
                raise RuntimeError("aiohttp is required for Graxia integration. pip install aiohttp")
            headers = {}
            if self.config.jwt_token:
                headers["Authorization"] = f"Bearer {self.config.jwt_token}"
            timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
            self._session = aiohttp.ClientSession(headers=headers, timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def health_check(self) -> bool:
        """Check if Graxia is reachable."""
        if not self.is_enabled:
            return False
        try:
            session = await self._ensure_session()
            url = f"{self.config.base_url}/health"
            async with session.get(url) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug("Graxia health check failed: %s", e)
            return False

    async def forward_agent(self, graxia_agent: str, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Forward a Graxia agent call to Agent OS.

        Maps: scoring → data_engineer, drafting → documenter, etc.
        """
        from ..agents import AGENT_REGISTRY

        agent_name = GRAXIA_TO_AGENT_OS.get(graxia_agent, "general")
        if agent_name not in AGENT_REGISTRY:
            return {"success": False, "error": f"Unknown Graxia agent: {graxia_agent}"}

        cls = AGENT_REGISTRY[agent_name]
        instance = cls()
        result = await instance.run(query, context=context or {})
        return {
            "success": result.success,
            "output": result.output,
            "tokens_used": result.tokens_used,
            "cost_usd": result.cost_usd,
            "graxia_agent": graxia_agent,
            "agent_os_agent": agent_name,
        }

    async def share_cost_report(self) -> Dict[str, Any]:
        """Share Agent OS cost report with Graxia dashboard."""
        from ..cost_engine.engine import CostEngine
        engine = CostEngine()
        report = await engine.report(period="day")
        return report

    def get_route_map(self) -> Dict[str, str]:
        """Get the Graxia → Agent OS agent mapping (for docs/debug)."""
        return dict(GRAXIA_TO_AGENT_OS)
