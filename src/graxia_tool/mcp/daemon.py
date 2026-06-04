"""Persistent MCP daemon — stays running, handles multiple requests.

Usage:
    python -m graxia_tool.mcp.daemon
    
Instead of spawning a new process per request, this daemon:
1. Starts once (1.2s cold start)
2. Handles unlimited requests via stdio
3. Keeps all modules loaded (no re-import overhead)
4. Pre-computes static responses

Expected: 0ms per tool call after initial startup.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("graxia_tool.mcp.daemon")

# Pre-import everything at module level (one-time cost)
logger.info("daemon_importing_modules")
_start = time.time()

from . import MCPServer, build_default_registry
from .fast_path import fast_dispatch, get_skill_cache, get_pool

_import_time = time.time() - _start
logger.info("daemon_modules_imported import_ms=%d", int(_import_time * 1000))


class DaemonMCPServer(MCPServer):
    """MCP server optimized for persistent running."""

    def __init__(self):
        super().__init__()
        # Pre-warm caches
        self._warm_caches()

    def _warm_caches(self):
        """Pre-load all caches at startup."""
        start = time.time()

        # Pre-load skill index
        cache = get_skill_cache()
        skills = cache.load()
        logger.info("daemon_skills_loaded count=%d", len(skills))

        # Pre-compute static responses
        from .fast_path import _build_static_responses
        _build_static_responses()

        # Initialize SQLite pool
        pool = get_pool()
        logger.info("daemon_sqlite_pool_ready")

        # Pre-load governance policies
        try:
            from .governance import _BUILTIN_POLICIES
            logger.info("daemon_governance_loaded policies=%d", len(_BUILTIN_POLICIES))
        except Exception:
            pass

        warm_time = time.time() - start
        logger.info("daemon_caches_warmed warm_ms=%d", int(warm_time * 1000))

    async def handle_request(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle request with fast-path optimization."""
        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params", {}) or {}
        is_notification = "id" not in req or req_id is None

        # Fast path for common methods
        if method == "initialize":
            result = {
                "protocolVersion": self.PROTOCOL_VERSION,
                "serverInfo": {"name": self.SERVER_NAME, "version": self.SERVER_VERSION},
                "capabilities": {"tools": {"listChanged": False}},
            }
            self._initialized = True
            return make_result(req_id, result) if not is_notification else None

        if method == "notifications/initialized":
            self._initialized = True
            return None

        if method == "ping":
            return make_result(req_id, {}) if not is_notification else None

        if method == "tools/list":
            tools = [t.to_mcp_dict() for t in self.registry.list_all()]
            return make_result(req_id, {"tools": tools}) if not is_notification else None

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {}) or {}

            # Fast path: try cached dispatch
            cached = fast_dispatch(tool_name, arguments)
            if cached is not None:
                return make_result(req_id, cached) if not is_notification else None

            # Full dispatch
            tool = self.registry.get(tool_name)
            if not tool:
                return make_error(req_id, -32602, f"Unknown tool: {tool_name}")
            try:
                content = await tool.handler(arguments)
                return make_result(req_id, content) if not is_notification else None
            except Exception as e:
                logger.exception("Tool %s raised", tool_name)
                return make_error(req_id, -32603, f"Tool error: {e}")

        return make_error(req_id, -32601, f"Method not found: {method}")


def main():
    """Run persistent daemon."""
    import argparse

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    parser = argparse.ArgumentParser(description="Graxia MCP Daemon (persistent)")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("daemon_starting")

    server = DaemonMCPServer()

    logger.info("daemon_ready import_ms=%d tools=%d",
                int(_import_time * 1000), len(server.registry.list_all()))

    asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
