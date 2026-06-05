"""
Fast-path optimization — lazy imports, SQLite pool, pickle cache.
Re-exports from mcp.fast_path.
"""
from ..mcp.fast_path import fast_dispatch, get_skill_cache, get_pool

__all__ = ["fast_dispatch", "get_skill_cache", "get_pool"]
