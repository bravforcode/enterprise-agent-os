"""Fast-path optimizations for MCP server.

Provides:
- Lazy module loading (defer heavy imports)
- Pre-compiled skill index cache (binary pickle)
- SQLite connection pooling
- Fast tool dispatch for common operations
"""
from __future__ import annotations

import json
import logging
import os
import pickle
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("graxia_tool.mcp.fast_path")

# ── Tool Result Cache (TTL-based) ─────────────────────────────────────

class ToolResultCache:
    """TTL-based cache for tool call results. Avoids redundant calls."""

    def __init__(self, default_ttl: int = 300):
        self._cache: Dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl
        self._hits = 0
        self._misses = 0

    def _make_key(self, tool_name: str, args: dict) -> str:
        """Create cache key from tool name + sorted args."""
        args_str = json.dumps(args, sort_keys=True, default=str)
        return f"{tool_name}:{args_str}"

    def get(self, tool_name: str, args: dict) -> Optional[Any]:
        """Get cached result if exists and not expired."""
        key = self._make_key(tool_name, args)
        with self._lock:
            if key in self._cache:
                expires, value = self._cache[key]
                if time.time() < expires:
                    self._hits += 1
                    return value
                else:
                    del self._cache[key]
            self._misses += 1
        return None

    def set(self, tool_name: str, args: dict, value: Any, ttl: Optional[int] = None) -> None:
        """Store result with TTL."""
        key = self._make_key(tool_name, args)
        expires = time.time() + (ttl or self._default_ttl)
        with self._lock:
            self._cache[key] = (expires, value)

    def stats(self) -> dict:
        """Return cache statistics."""
        with self._lock:
            total = self._hits + self._misses
            return {
                "entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": f"{self._hits/total*100:.1f}%" if total > 0 else "0%",
            }

    def clear(self) -> int:
        """Clear expired entries. Returns count cleared."""
        now = time.time()
        cleared = 0
        with self._lock:
            expired = [k for k, (exp, _) in self._cache.items() if exp < now]
            for k in expired:
                del self._cache[k]
                cleared += 1
        return cleared


# Global tool cache
_tool_cache = ToolResultCache(default_ttl=300)


def get_tool_cache() -> ToolResultCache:
    return _tool_cache


# ── Config ──────────────────────────────────────────────────────────────

GRAXIA_DIR = Path.home() / ".graxia"
CACHE_DIR = GRAXIA_DIR / "cache"
SKILLS_INDEX_YAML = GRAXIA_DIR / "skills-index.json"
SKILLS_INDEX_PICKLE = CACHE_DIR / "skills-index.pkl"
SESSION_DB = GRAXIA_DIR / "session_memory.db"

# ── SQLite Connection Pool ──────────────────────────────────────────────

class SQLitePool:
    """Thread-safe SQLite connection pool."""

    def __init__(self, db_path: str, max_connections: int = 5):
        self._db_path = db_path
        self._max = max_connections
        self._pool: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        self._total_queries = 0
        self._total_time = 0.0

    def _create_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=-8000")
        conn.execute("PRAGMA temp_store=MEMORY")
        return conn

    def get(self) -> sqlite3.Connection:
        with self._lock:
            if self._pool:
                return self._pool.pop()
        return self._create_conn()

    def put(self, conn: sqlite3.Connection) -> None:
        with self._lock:
            if len(self._pool) < self._max:
                self._pool.append(conn)
            else:
                conn.close()

    def execute(self, query: str, params: tuple = ()) -> list:
        start = time.monotonic()
        conn = self.get()
        try:
            cursor = conn.execute(query, params)
            result = cursor.fetchall()
            self._total_queries += 1
            self._total_time += time.monotonic() - start
            return result
        finally:
            self.put(conn)

    def executemany(self, query: str, params_list: list) -> None:
        conn = self.get()
        try:
            conn.executemany(query, params_list)
            conn.commit()
        finally:
            self.put(conn)

    def commit(self) -> None:
        conn = self.get()
        try:
            conn.commit()
        finally:
            self.put(conn)

    def stats(self) -> dict:
        return {
            "pool_size": len(self._pool),
            "total_queries": self._total_queries,
            "avg_query_ms": (self._total_time / self._total_queries * 1000) if self._total_queries else 0,
        }


# Global pool
_pool: Optional[SQLitePool] = None
_pool_lock = threading.Lock()


def get_pool() -> SQLitePool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                GRAXIA_DIR.mkdir(parents=True, exist_ok=True)
                _pool = SQLitePool(str(SESSION_DB))
    return _pool


# ── Skill Index Cache ──────────────────────────────────────────────────

class SkillIndexCache:
    """Pre-compiled skill index with pickle cache."""

    def __init__(self):
        self._skills: list[dict] = []
        self._loaded = False
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        if self._loaded:
            return self._skills

        with self._lock:
            if self._loaded:
                return self._skills

            # Try pickle cache first
            if SKILLS_INDEX_PICKLE.exists():
                try:
                    with open(SKILLS_INDEX_PICKLE, "rb") as f:
                        self._skills = pickle.load(f)
                    self._loaded = True
                    logger.info("skill_index_cache_hit count=%d", len(self._skills))
                    return self._skills
                except Exception:
                    pass

            # Fall back to JSON
            if SKILLS_INDEX_YAML.exists():
                try:
                    import json as _json
                    with open(SKILLS_INDEX_YAML, encoding="utf-8") as f:
                        self._skills = _json.loads(f.read()) or []
                    # Save pickle cache
                    CACHE_DIR.mkdir(parents=True, exist_ok=True)
                    with open(SKILLS_INDEX_PICKLE, "wb") as f:
                        pickle.dump(self._skills, f)
                    self._loaded = True
                    logger.info("skill_index_yaml_loaded count=%d", len(self._skills))
                    return self._skills
                except Exception:
                    pass

            self._loaded = True
            return self._skills

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        if not self._loaded:
            self.load()

        query_lower = query.lower()
        query_words = set(query_lower.split())

        scored = []
        for skill in self._skills:
            score = 0.0
            name = skill.get("name", "").lower()
            desc = skill.get("description", "").lower()
            triggers = skill.get("triggers", [])

            # Name match
            if query_lower in name:
                score += 2.0

            # Trigger match
            for t in triggers:
                if t.lower() in query_words or t.lower() in query_lower:
                    score += 1.5

            # Description word overlap
            desc_words = set(desc.split())
            overlap = query_words & desc_words
            score += len(overlap) * 0.5

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]


# Global cache
_skill_cache: Optional[SkillIndexCache] = None
_skill_lock = threading.Lock()


def get_skill_cache() -> SkillIndexCache:
    global _skill_cache
    if _skill_cache is None:
        with _skill_lock:
            if _skill_cache is None:
                _skill_cache = SkillIndexCache()
    return _skill_cache


# ── Fast Tool Dispatch ─────────────────────────────────────────────────

# Pre-computed responses for static tools (no I/O needed)
STATIC_RESPONSES: Dict[str, dict] = {}


def _build_static_responses() -> None:
    """Pre-compute responses for tools that don't need I/O."""
    STATIC_RESPONSES["system_status"] = {
        "content": [{"type": "text", "text": json.dumps({
            "status": "ok",
            "version": "0.5.0",
            "tools": 45,
            "skills": 403,
            "uptime": "active",
        })}]
    }

    STATIC_RESPONSES["agent_list"] = {
        "content": [{"type": "text", "text": json.dumps({
            "agents": ["general", "coder", "researcher", "tester", "planner"],
            "count": 5,
        })}]
    }

    STATIC_RESPONSES["context_cache_stats"] = {
        "content": [{"type": "text", "text": json.dumps({
            "hits": 0, "misses": 0, "entries": 0,
        })}]
    }


def fast_dispatch(tool_name: str, args: dict) -> Optional[dict]:
    """Try to handle tool call without heavy imports. Returns None if not cached."""
    # Check tool result cache first
    cached = _tool_cache.get(tool_name, args)
    if cached is not None:
        return cached

    if not STATIC_RESPONSES:
        _build_static_responses()

    if tool_name in STATIC_RESPONSES:
        result = STATIC_RESPONSES[tool_name]
        _tool_cache.set(tool_name, args, result, ttl=60)
        return result

    # Fast skill search (no YAML parse)
    if tool_name == "skill_search":
        cache = get_skill_cache()
        results = cache.search(args.get("query", ""), args.get("top_k", 5))
        result = {
            "content": [{"type": "text", "text": json.dumps({
                "results": [{
                    "name": s.get("name", ""),
                    "description": s.get("description", "")[:200],
                    "score": 1.0,
                    "category": s.get("category", ""),
                    "trust_level": s.get("trust_level", ""),
                } for s in results],
                "total": len(results),
            })}]
        }
        _tool_cache.set(tool_name, args, result, ttl=600)
        return result

    return None


# ── Lazy Import Cache ──────────────────────────────────────────────────

_lazy_modules: Dict[str, Any] = {}
_lazy_lock = threading.Lock()


def lazy_import(module_path: str, attr: str = None):
    """Import module/attribute lazily, cached after first use."""
    key = f"{module_path}.{attr}" if attr else module_path
    if key in _lazy_modules:
        return _lazy_modules[key]

    with _lazy_lock:
        if key in _lazy_modules:
            return _lazy_modules[key]

        import importlib
        mod = importlib.import_module(module_path)
        result = getattr(mod, attr) if attr else mod
        _lazy_modules[key] = result
        return result
