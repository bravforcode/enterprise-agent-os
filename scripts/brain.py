"""Brain CLI — Fast terminal access to sync brain system.

Usage:
    python scripts/brain.py search "python async"
    python scripts/brain.py skill "debug"
    python scripts/brain.py recall "project status"
    python scripts/brain.py status
    python scripts/brain.py bench

Preloads everything on first call, cached for subsequent calls.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add src to path
SRC = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(SRC))

# ── Preload cache (singleton) ──────────────────────────────────────────

_cache = {}


def _preload():
    """Preload all components once."""
    if _cache:
        return _cache

    start = time.time()

    # 1. Skill index (pickle)
    from graxia_tool.mcp.fast_path import get_skill_cache
    skill_cache = get_skill_cache()
    skills = skill_cache.load()
    _cache["skills"] = skills
    _cache["skill_cache"] = skill_cache

    # 2. Memory pool
    from graxia_tool.mcp.fast_path import get_pool
    _cache["pool"] = get_pool()

    # 3. Tool registry (lazy)
    from graxia_tool.mcp.fast_path import fast_dispatch, STATIC_RESPONSES
    _cache["fast_dispatch"] = fast_dispatch
    _cache["static"] = STATIC_RESPONSES

    elapsed = time.time() - start
    _cache["load_time"] = elapsed

    return _cache


# ── Commands ───────────────────────────────────────────────────────────

def cmd_search(query: str, top_k: int = 5):
    """Search skills."""
    c = _preload()
    cache = c["skill_cache"]
    start = time.time()
    results = cache.search(query, top_k)
    elapsed = (time.time() - start) * 1000

    print(f"Search: \"{query}\" ({elapsed:.1f}ms)")
    print(f"Results: {len(results)}")
    for i, s in enumerate(results):
        print(f"  {i+1}. {s.get('name', '?')}")
        print(f"     {s.get('description', '?')[:100]}")
        print(f"     Category: {s.get('category', '?')} | Trust: {s.get('trust_level', '?')}")


def cmd_recall(query: str, limit: int = 5):
    """Recall memories."""
    c = _preload()
    pool = c["pool"]
    start = time.time()

    try:
        rows = pool.execute(
            "SELECT summary, file_type, path FROM codebase WHERE summary LIKE ? OR path LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", limit)
        )
        elapsed = (time.time() - start) * 1000
        print(f"Recall: \"{query}\" ({elapsed:.1f}ms)")
        print(f"Results: {len(rows)}")
        for i, (summary, ftype, path) in enumerate(rows):
            print(f"  {i+1}. [{ftype}] {path or '?'}")
            print(f"     {(summary or '?')[:120]}")
    except Exception as e:
        print(f"Recall error: {e}")


def cmd_status():
    """Show brain status."""
    c = _preload()

    print("=== Sync Brain Status ===")
    print(f"Load time: {c['load_time']*1000:.0f}ms")
    print(f"Skills loaded: {len(c['skills'])}")

    # SQLite stats
    pool = c["pool"]
    try:
        for table in ["tasks", "codebase", "preferences", "skill_metadata"]:
            count = pool.execute(f"SELECT COUNT(*) FROM {table}")[0][0]
            print(f"  {table}: {count} rows")
    except Exception:
        pass

    # Fast dispatch test
    fd = c["fast_dispatch"]
    start = time.time()
    for _ in range(100):
        fd("system_status", {})
    avg = (time.time() - start) / 100 * 1000
    print(f"Fast dispatch: {avg:.2f}ms avg (100x)")


def cmd_bench():
    """Benchmark all components."""
    print("=== Brain Benchmark ===\n")

    # 1. Skill search
    c = _preload()
    cache = c["skill_cache"]
    start = time.time()
    for _ in range(1000):
        cache.search("debug python error", top_k=5)
    elapsed = (time.time() - start) / 1000 * 1000
    print(f"1. Skill search:   {elapsed:.2f}ms avg (1000x)")

    # 2. Fast dispatch
    fd = c["fast_dispatch"]
    start = time.time()
    for _ in range(1000):
        fd("system_status", {})
    elapsed = (time.time() - start) / 1000 * 1000
    print(f"2. Fast dispatch:  {elapsed:.2f}ms avg (1000x)")

    # 3. SQLite query
    pool = c["pool"]
    start = time.time()
    for _ in range(1000):
        pool.execute("SELECT COUNT(*) FROM skill_metadata")
    elapsed = (time.time() - start) / 1000 * 1000
    print(f"3. SQLite query:   {elapsed:.2f}ms avg (1000x)")

    # 4. Full MCP call (via subprocess)
    import subprocess
    PYTHON = sys.executable
    init = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2024-11-05", "clientInfo": {"name": "bench"}}})
    start = time.time()
    proc = subprocess.Popen(
        [PYTHON, "-m", "graxia_tool.mcp"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(1)
    proc.stdin.write((init + "\n").encode())
    proc.stdin.flush()
    time.sleep(0.5)
    call = json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                       "params": {"name": "system_status", "arguments": {}}})
    proc.stdin.write((call + "\n").encode())
    proc.stdin.flush()
    time.sleep(0.5)
    proc.stdin.close()
    proc.stdout.read()
    proc.stderr.read()
    proc.terminate()
    elapsed = (time.time() - start) * 1000
    print(f"4. Full MCP call:  {elapsed:.0f}ms (cold start + tool)")

    print(f"\nPreload time: {c['load_time']*1000:.0f}ms")


def cmd_help():
    """Show help."""
    print("""Brain CLI — Fast sync brain access

Commands:
  search <query> [top_k]    Search skills (fast, from cache)
  recall <query> [limit]    Recall memories (SQLite)
  status                    Show brain status
  bench                     Run benchmark
  help                      Show this help

Examples:
  python scripts/brain.py search "debug python"
  python scripts/brain.py recall "project status"
  python scripts/brain.py bench
""")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        cmd_help()
        return

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "search":
        query = args[0] if args else "test"
        top_k = int(args[1]) if len(args) > 1 else 5
        cmd_search(query, top_k)
    elif cmd == "recall":
        query = args[0] if args else "test"
        limit = int(args[1]) if len(args) > 1 else 5
        cmd_recall(query, limit)
    elif cmd == "status":
        cmd_status()
    elif cmd == "bench":
        cmd_bench()
    else:
        cmd_help()


if __name__ == "__main__":
    main()
