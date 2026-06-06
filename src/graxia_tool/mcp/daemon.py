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
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("graxia_tool.mcp.daemon")

# Pre-import everything at module level (one-time cost)
logger.info("daemon_importing_modules")
_start = time.time()

from . import MCPServer, Tool, build_default_registry, make_result, make_error
from .fast_path import fast_dispatch, get_skill_cache, get_pool

_import_time = time.time() - _start
logger.info("daemon_modules_imported import_ms=%d", int(_import_time * 1000))


class DaemonMCPServer(MCPServer):
    """MCP server optimized for persistent running."""

    def __init__(self):
        super().__init__()
        self._memory = None
        self._file_watcher = None
        self._warm_caches()
        self._init_memory()
        self._start_file_watcher()
        self._register_memory_tools()

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

    def _init_memory(self):
        """Initialize cross-session memory manager."""
        from ..control_plane.memory import MemoryManager

        db_dir = Path.home() / ".graxia" / "tool"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(db_dir / "memory.db")

        self._memory = MemoryManager(db_path=db_path)
        logger.info("daemon_memory_initialized db=%s", db_path)

        # Start auto-persist (every 5 min)
        self._memory.auto_persist(interval=300)
        logger.info("daemon_auto_persist_started interval=300s")

    def _start_file_watcher(self):
        """Start file watcher for vault, code, config."""
        from ..control_plane.watcher import FileWatcher

        vault_path = os.environ.get("AGENT_OS_VAULT_PATH")
        code_path = str(Path(__file__).parent.parent)
        config_paths = []

        # Find config files
        claude_dir = Path.home() / ".claude"
        if claude_dir.exists():
            for name in [".mcp.json", "CLAUDE.md"]:
                p = claude_dir / name
                if p.exists():
                    config_paths.append(str(p))

        rules_path = Path(__file__).parent.parent.parent / "AGENT_RULES.md"
        if rules_path.exists():
            config_paths.append(str(rules_path))

        self._file_watcher = FileWatcher(
            vault_path=vault_path,
            code_path=code_path,
            config_paths=config_paths,
            on_vault_change=self._on_vault_change,
            on_code_change=self._on_code_change,
            on_config_change=self._on_config_change,
        )
        self._file_watcher.start()
        logger.info("daemon_file_watcher_started vault=%s code=%s configs=%d",
                     vault_path, code_path, len(config_paths))

    def _on_vault_change(self, paths: list):
        """Handle vault file changes — store event in memory."""
        if self._memory:
            self._memory.store(
                content=f"vault_changed: {len(paths)} files",
                tier="longterm",
                key=f"vault_sync_{int(time.time())}",
            )

    def _on_code_change(self, paths: list):
        """Handle code file changes — invalidate cache."""
        logger.info("code_changed count=%d", len(paths))

    def _on_config_change(self, paths: list):
        """Handle config file changes — log event."""
        logger.info("config_changed paths=%s", paths)

    def _register_memory_tools(self):
        """Register memory tools in the tool registry so they appear in tools/list."""
        self.registry.register(Tool(
            name="memory_store",
            description="Store a memory in the cross-session memory manager.",
            input_schema={
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to store"},
                    "tier": {"type": "string", "enum": ["session", "working", "longterm", "project"], "default": "working"},
                    "key": {"type": "string", "description": "Optional key for retrieval"},
                },
                "required": ["content"],
            },
            handler=lambda args: self._handle_memory_store(None, args),
            category="memory",
        ))
        self.registry.register(Tool(
            name="memory_recall",
            description="Recall memories from the cross-session memory manager.",
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "key": {"type": "string", "description": "Exact key match"},
                    "tier": {"type": "string", "enum": ["session", "working", "longterm", "project"]},
                    "limit": {"type": "integer", "default": 10},
                },
            },
            handler=lambda args: self._handle_memory_recall(None, args),
            category="memory",
        ))

    def close(self):
        """Shut down daemon resources."""
        if self._memory:
            self._memory.stop_persist()
        if self._file_watcher:
            self._file_watcher.stop()
        logger.info("daemon_closed")

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

            # Memory tools — use shared MemoryManager
            if tool_name == "memory_store" and self._memory:
                return self._handle_memory_store(req_id, arguments)
            if tool_name == "memory_recall" and self._memory:
                return self._handle_memory_recall(req_id, arguments)

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

    def _handle_memory_store(self, req_id, args):
        try:
            tier = args.get("tier", "working")
            content = args.get("content", "")
            key = args.get("key")
            memory_id = self._memory.store(content, tier=tier, key=key)
            return make_result(req_id, {"id": memory_id, "tier": tier, "stored": True})
        except Exception as e:
            return make_error(req_id, -32603, f"memory_store error: {e}")

    def _handle_memory_recall(self, req_id, args):
        try:
            from ..control_plane.memory import MemoryTier

            query = args.get("query")
            key = args.get("key")
            tier = MemoryTier(args["tier"]) if args.get("tier") else None
            limit = args.get("limit", 10)
            results = self._memory.recall(query=query, key=key, tier=tier, limit=limit)
            return make_result(req_id, {"results": results, "count": len(results)})
        except Exception as e:
            return make_error(req_id, -32603, f"memory_recall error: {e}")


def _cleanup_stale_processes() -> None:
    """Kill stale graxia_tool.mcp processes (except current PID)."""
    try:
        import psutil
        current_pid = os.getpid()
        killed = 0
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                if p.pid == current_pid:
                    continue
                cmd = " ".join(p.info["cmdline"] or [])
                if "graxia_tool.mcp" in cmd:
                    p.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if killed:
            logger.info("cleanup_killed=%d stale processes", killed)
    except ImportError:
        pass


def main():
    """Run persistent daemon."""
    import argparse

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # Auto-cleanup stale daemon processes
    _cleanup_stale_processes()

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
