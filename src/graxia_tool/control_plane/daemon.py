"""Persistent MCP daemon with cross-session memory for Graxia Tool system.

Single long-running process handling MCP stdio requests with:
- SQLite + WAL mode persistence
- Four memory tiers (session, working, longterm, project)
- BM25 full-text search via FTS5
- Named pipe IPC for Windows
- Health check and auto-restart on failure
"""

import json
import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from .memory import MemoryManager, MemoryTier

MCP_PROTOCOL_VERSION = "2024-11-05"
DAEMON_NAME = "graxia-tool-daemon"
HEARTBEAT_INTERVAL = 30

DEFAULT_DB_PATH = str(
    Path.home() / ".graxia" / "tool" / "memory.db"
)

NAMED_PIPE_PATH = r"\\.\pipe\graxia-tool-daemon"


class MCPDaemon:
    """Persistent MCP daemon handling stdio protocol with memory persistence."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DEFAULT_DB_PATH
        self._running = False
        self._memory: Optional[MemoryManager] = None
        self._tools: dict[str, dict[str, Any]] = {}
        self._shutdown_event = threading.Event()
        self._request_id = 0

    def _ensure_db_dir(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def _init_memory(self) -> None:
        self._memory = MemoryManager(db_path=self.db_path)
        self._memory.store(
            content=json.dumps({"event": "daemon_start", "pid": os.getpid()}),
            tier=MemoryTier.LONGTERM,
            key="daemon_lifecycle",
        )

    def _register_tools(self) -> None:
        self._tools = {
            "memory_store": {
                "name": "memory_store",
                "description": "Store content in a memory tier",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "tier": {"type": "string", "enum": ["session", "working", "longterm", "project"]},
                        "key": {"type": "string"},
                        "project": {"type": "string"},
                        "ttl": {"type": "integer"},
                    },
                    "required": ["content"],
                },
            },
            "memory_recall": {
                "name": "memory_recall",
                "description": "Recall memories by id, key, tier, project, or search query",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "key": {"type": "string"},
                        "tier": {"type": "string", "enum": ["session", "working", "longterm", "project"]},
                        "project": {"type": "string"},
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "default": 10},
                    },
                },
            },
            "memory_delete": {
                "name": "memory_delete",
                "description": "Delete a memory by id",
                "inputSchema": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                    "required": ["id"],
                },
            },
            "memory_stats": {
                "name": "memory_stats",
                "description": "Get memory usage statistics",
                "inputSchema": {"type": "object", "properties": {}},
            },
            "memory_clear_expired": {
                "name": "memory_clear_expired",
                "description": "Clear expired working memory entries",
                "inputSchema": {"type": "object", "properties": {}},
            },
            "health_check": {
                "name": "health_check",
                "description": "Check daemon health and uptime",
                "inputSchema": {"type": "object", "properties": {}},
            },
        }

    def _handle_initialize(self, msg: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {
                    "tools": {},
                    "memory": {"tiers": ["session", "working", "longterm", "project"]},
                },
                "serverInfo": {
                    "name": DAEMON_NAME,
                    "version": "1.0.0",
                },
            },
        }

    def _handle_tools_list(self, msg: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "result": {"tools": list(self._tools.values())},
        }

    def _handle_tools_call(self, msg: dict[str, Any]) -> dict[str, Any]:
        params = msg.get("params", {})
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        try:
            result = self._call_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": msg.get("id"),
                "error": {"code": -1, "message": str(e)},
            }

    def _call_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        assert self._memory is not None

        if name == "health_check":
            return self._health_check()

        if name == "memory_store":
            tier = MemoryTier(args.get("tier", "working"))
            memory_id = self._memory.store(
                content=args["content"],
                tier=tier,
                project=args.get("project"),
                key=args.get("key"),
                ttl=args.get("ttl"),
            )
            return {"id": memory_id, "tier": tier.value, "stored": True}

        if name == "memory_recall":
            results = self._memory.recall(
                memory_id=args.get("id"),
                key=args.get("key"),
                tier=MemoryTier(args["tier"]) if args.get("tier") else None,
                project=args.get("project"),
                query=args.get("query"),
                limit=args.get("limit", 10),
            )
            return {"results": results, "count": len(results)}

        if name == "memory_delete":
            deleted = self._memory.delete(args["id"])
            return {"deleted": deleted}

        if name == "memory_stats":
            return self._memory.stats()

        if name == "memory_clear_expired":
            count = self._memory.clear_expired()
            return {"cleared": count}

        raise ValueError(f"Unknown tool: {name}")

    def _health_check(self) -> dict[str, Any]:
        assert self._memory is not None
        stats = self._memory.stats()
        return {
            "status": "healthy",
            "daemon": DAEMON_NAME,
            "uptime_running": self._running,
            "memory_stats": stats,
        }

    def _send_response(self, response: dict[str, Any]) -> None:
        line = json.dumps(response) + "\n"
        sys.stdout.write(line)
        sys.stdout.flush()

    def _read_message(self) -> Optional[dict[str, Any]]:
        line = sys.stdin.readline()
        if not line:
            return None
        try:
            return json.loads(line.strip())
        except json.JSONDecodeError:
            return None

    def _process_message(self, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
        method = msg.get("method", "")

        if method == "initialize":
            return self._handle_initialize(msg)
        if method == "tools/list":
            return self._handle_tools_list(msg)
        if method == "tools/call":
            return self._handle_tools_call(msg)
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg.get("id"), "result": {}}
        if method == "notifications/initialized":
            return None

        return {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self._running = False
        self._shutdown_event.set()

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._ensure_db_dir()
        self._init_memory()
        self._register_tools()
        self._running = True

        self._send_response({
            "jsonrpc": "2.0",
            "method": "notifications/daemon_started",
            "params": {"name": DAEMON_NAME, "db": self.db_path},
        })

        while self._running:
            msg = self._read_message()
            if msg is None:
                break
            response = self._process_message(msg)
            if response:
                self._send_response(response)

        if self._memory:
            self._memory.store(
                content=json.dumps({"event": "daemon_stop", "pid": os.getpid()}),
                tier=MemoryTier.LONGTERM,
                key="daemon_lifecycle",
            )
            self._memory.close()


def run_daemon(db_path: Optional[str] = None) -> None:
    daemon = MCPDaemon(db_path=db_path)
    daemon.run()


def restart_daemon(db_path: Optional[str] = None, max_retries: int = 5) -> None:
    retries = 0
    while retries < max_retries:
        try:
            run_daemon(db_path=db_path)
            break
        except Exception as e:
            retries += 1
            if retries >= max_retries:
                raise
            time.sleep(min(2 ** retries, 30))


if __name__ == "__main__":
    db = os.environ.get("GRAXIA_MEMORY_DB", DEFAULT_DB_PATH)
    restart_daemon(db_path=db)
