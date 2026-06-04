"""Brain Preload — Warms all caches on system startup.

Runs silently in background. No user interaction needed.
Creates warm caches so first MCP call is instant.

Usage:
    python scripts/brain_preload.py          # Run preload
    python scripts/brain_preload.py --check  # Check if caches are warm
"""
from __future__ import annotations

import json
import os
import pickle
import sqlite3
import sys
import time
from pathlib import Path

GRAXIA_DIR = Path.home() / ".graxia"
CACHE_DIR = GRAXIA_DIR / "cache"
WARM_MARKER = CACHE_DIR / "brain_warm.flag"


def preload_skills() -> int:
    """Preload skills index into pickle cache."""
    yaml_path = GRAXIA_DIR / "skills-index.yaml"
    pickle_path = CACHE_DIR / "skills-index.pkl"

    if not yaml_path.exists():
        return 0

    import yaml
    start = time.time()
    with open(yaml_path, encoding="utf-8") as f:
        skills = yaml.safe_load(f) or []

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(pickle_path, "wb") as f:
        pickle.dump(skills, f)

    elapsed = (time.time() - start) * 1000
    print(f"Skills: {len(skills)} loaded in {elapsed:.0f}ms")
    return len(skills)


def preload_sqlite() -> dict:
    """Warm SQLite connection pool."""
    db_path = GRAXIA_DIR / "session_memory.db"
    if not db_path.exists():
        return {}

    start = time.time()
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-8000")
    conn.execute("PRAGMA temp_store=MEMORY")

    stats = {}
    for table in ["tasks", "codebase", "preferences", "skill_metadata"]:
        try:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            stats[table] = count
        except Exception:
            stats[table] = 0

    conn.close()
    elapsed = (time.time() - start) * 1000
    print(f"SQLite: {sum(stats.values())} rows in {elapsed:.0f}ms")
    return stats


def preload_static_responses() -> None:
    """Pre-compute static MCP responses."""
    start = time.time()
    responses = {
        "system_status": {
            "content": [{"type": "text", "text": json.dumps({
                "status": "warm", "version": "0.5.0", "tools": 45, "skills": 403,
            })}]
        },
        "agent_list": {
            "content": [{"type": "text", "text": json.dumps({
                "agents": ["general", "coder", "researcher", "tester", "planner"],
            })}]
        },
        "context_cache_stats": {
            "content": [{"type": "text", "text": json.dumps({
                "hits": 0, "misses": 0, "entries": 0,
            })}]
        },
    }

    pickle_path = CACHE_DIR / "static_responses.pkl"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(pickle_path, "wb") as f:
        pickle.dump(responses, f)

    elapsed = (time.time() - start) * 1000
    print(f"Static: {len(responses)} responses in {elapsed:.0f}ms")


def preload_tool_registry() -> int:
    """Pre-import and cache tool registry."""
    start = time.time()
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    count = len(reg.list_all())

    # Save registry schema to pickle
    schemas = {}
    for tool in reg.list_all():
        schemas[tool.name] = {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    pickle_path = CACHE_DIR / "tool_schemas.pkl"
    with open(pickle_path, "wb") as f:
        pickle.dump(schemas, f)

    elapsed = (time.time() - start) * 1000
    print(f"Tools: {count} registered in {elapsed:.0f}ms")
    return count


def preload_all() -> dict:
    """Preload everything and write warm marker."""
    start = time.time()
    print("=== Brain Preload ===")

    stats = {}
    stats["skills"] = preload_skills()
    stats["sqlite"] = preload_sqlite()
    preload_static_responses()
    stats["tools"] = preload_tool_registry()

    # Write warm marker
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(WARM_MARKER, "w") as f:
        json.dump({
            "timestamp": time.time(),
            "stats": stats,
            "version": "0.5.0",
        }, f)

    elapsed = (time.time() - start) * 1000
    stats["total_ms"] = elapsed
    print(f"\n=== Brain Warm ({elapsed:.0f}ms) ===")
    return stats


def check_warm() -> bool:
    """Check if caches are warm."""
    if not WARM_MARKER.exists():
        print("Brain NOT warm (no marker)")
        return False

    with open(WARM_MARKER) as f:
        marker = json.load(f)

    age = time.time() - marker.get("timestamp", 0)
    if age > 3600:  # 1 hour
        print(f"Brain STALE ({age/3600:.1f} hours old)")
        return False

    print(f"Brain WARM (age: {age/60:.0f} min, version: {marker.get('version', '?')})")
    return True


def main():
    if "--check" in sys.argv:
        check_warm()
    elif "--silent" in sys.argv:
        # Silent mode for startup (no output)
        try:
            preload_all()
        except Exception:
            pass  # Silently fail on startup
    else:
        preload_all()


if __name__ == "__main__":
    main()
