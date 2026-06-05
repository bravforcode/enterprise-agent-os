"""Global AI Agent Control Plane — modular, protocol-driven, local-first.

Layers:
- daemon: persistent MCP server
- memory: 4-tier memory (session/working/longterm/project)
- skills: registry with versioning + auto-loading
- cache: tool-result caching with semantic matching
- search: hybrid BM25 + recency ranking
- security: input validation + audit trail + circuit breaker
- cost: token budget + model routing + cache-first policy
- watcher: real-time file change detection
"""
from .memory import MemoryManager
from .skills import SkillRegistry
from .cache import ToolCache
from .search import HybridSearch
from .security import SecurityGate
from .cost import CostOptimizer
from .watcher import FileWatcher

__all__ = [
    "MemoryManager",
    "SkillRegistry",
    "ToolCache",
    "HybridSearch",
    "SecurityGate",
    "CostOptimizer",
    "FileWatcher",
]
