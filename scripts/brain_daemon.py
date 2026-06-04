"""Brain Daemon — Persistent background brain server.

Stays running in background, serves all IDEs via named pipe.
Zero cold start after first load.

Usage:
    python scripts/brain_daemon.py              # Start daemon
    python scripts/brain_daemon.py --query "test"  # Query daemon
"""
from __future__ import annotations

import json
import os
import sys
import time
import threading
from pathlib import Path

# Add src to path
SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

PIPE_NAME = r"\\.\pipe\graxia_brain"
GRAXIA_DIR = Path.home() / ".graxia"
PID_FILE = GRAXIA_DIR / "brain_daemon.pid"

# ── Brain Cache ────────────────────────────────────────────────────────

_cache = {}


def _warm_cache():
    """Warm all caches once."""
    if _cache:
        return

    start = time.time()

    # Skills
    from graxia_tool.mcp.fast_path import get_skill_cache, get_pool, fast_dispatch, _build_static_responses
    skill_cache = get_skill_cache()
    skills = skill_cache.load()
    _cache["skills"] = skills
    _cache["skill_cache"] = skill_cache

    # SQLite
    _cache["pool"] = get_pool()

    # Fast dispatch
    _cache["fast_dispatch"] = fast_dispatch
    _build_static_responses()

    # Tool registry
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    _cache["registry"] = reg

    elapsed = (time.time() - start) * 1000
    _cache["warm_ms"] = elapsed
    _cache["warm_time"] = time.time()

    print(f"Brain warm: {elapsed:.0f}ms, {len(skills)} skills, {len(reg.list_all())} tools")


# ── Request Handler ────────────────────────────────────────────────────

def handle_request(req: dict) -> dict:
    """Handle a brain request."""
    method = req.get("method", "")
    params = req.get("params", {}) or {}
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "graxia_brain", "version": "0.5.0"},
                "capabilities": {"tools": {"listChanged": False}},
            }
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        reg = _cache.get("registry")
        if reg:
            tools = [t.to_mcp_dict() for t in reg.list_all()]
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}

        # Fast dispatch
        fd = _cache.get("fast_dispatch")
        if fd:
            cached = fd(tool_name, arguments)
            if cached is not None:
                return {"jsonrpc": "2.0", "id": req_id, "result": cached}

        # Full dispatch
        reg = _cache.get("registry")
        if reg:
            tool = reg.get(tool_name)
            if tool:
                import asyncio
                try:
                    loop = asyncio.new_event_loop()
                    content = loop.run_until_complete(tool.handler(arguments))
                    loop.close()
                    return {"jsonrpc": "2.0", "id": req_id, "result": content}
                except Exception as e:
                    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": f"Tool error: {e}"}}

        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown tool: {tool_name}"}}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}


# ── Named Pipe Server ──────────────────────────────────────────────────

def run_pipe_server():
    """Run named pipe server for IPC."""
    import win32pipe
    import win32file

    print(f"Brain daemon listening on {PIPE_NAME}")

    while True:
        try:
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT,
                1, 65536, 65536,
                0, None
            )

            win32pipe.ConnectNamedPipe(pipe, None)
            print("Client connected")

            while True:
                try:
                    hr, data = win32file.ReadFile(pipe, 65536)
                    if hr != 0:
                        break

                    req = json.loads(data.decode("utf-8"))
                    resp = handle_request(req)
                    resp_bytes = json.dumps(resp).encode("utf-8")
                    win32file.WriteFile(pipe, resp_bytes)

                except Exception as e:
                    print(f"Request error: {e}")
                    break

            win32pipe.DisconnectNamedPipe(pipe)
            win32file.CloseHandle(pipe)
            print("Client disconnected")

        except Exception as e:
            print(f"Pipe error: {e}")
            time.sleep(1)


# ── Query Client ───────────────────────────────────────────────────────

def query_daemon(req: dict) -> dict:
    """Query the daemon via named pipe."""
    import win32pipe
    import win32file

    try:
        pipe = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0, None,
            win32file.OPEN_EXISTING, 0, None
        )

        req_bytes = json.dumps(req).encode("utf-8")
        win32file.WriteFile(pipe, req_bytes)

        hr, resp_bytes = win32file.ReadFile(pipe, 65536)
        win32file.CloseHandle(pipe)

        return json.loads(resp_bytes.decode("utf-8"))

    except Exception as e:
        return {"error": str(e)}


# ── Main ───────────────────────────────────────────────────────────────

def main():
    # Check if already running
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text().strip())
            os.kill(old_pid, 0)
            print(f"Daemon already running (PID {old_pid})")
            return
        except (ProcessLookupError, ValueError):
            pass

    # Write PID
    GRAXIA_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    # Warm cache
    _warm_cache()

    # Handle query mode
    if "--query" in sys.argv:
        idx = sys.argv.index("--query") + 1
        if idx < len(sys.argv):
            query = sys.argv[idx]
            req = {"method": "tools/call", "params": {"name": "skill_search", "arguments": {"query": query}}}
            resp = query_daemon(req)
            print(json.dumps(resp, indent=2))
        return

    # Handle --stop
    if "--stop" in sys.argv:
        try:
            os.kill(int(PID_FILE.read_text().strip()), 9)
            PID_FILE.unlink()
            print("Daemon stopped")
        except Exception as e:
            print(f"Stop error: {e}")
        return

    # Start daemon
    try:
        run_pipe_server()
    except KeyboardInterrupt:
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
