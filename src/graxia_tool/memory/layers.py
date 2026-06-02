"""Enterprise Agent OS — Memory Layer Definitions."""
from __future__ import annotations
from enum import Enum


class MemoryLayer(str, Enum):
    """8 memory layers in the Memory OS."""
    WORKING = "working"        # Current turn context (ephemeral, Redis)
    SHORT_TERM = "short_term"  # Session-level (1-7 days, Redis/DB)
    LONG_TERM = "long_term"    # Cross-session facts (persistent, DB + Qdrant)
    EPISODIC = "episodic"      # Past events (1 year, DB)
    SEMANTIC = "semantic"      # Concepts/knowledge (persistent, Qdrant)
    PROCEDURAL = "procedural"  # How-to steps (persistent, DB)
    FAILURE = "failure"        # What went wrong (persistent, DB)
    PREFERENCE = "preference"  # User prefs (persistent, DB)


# Layer characteristics
LAYER_CONFIG: dict[MemoryLayer, dict] = {
    MemoryLayer.WORKING: {
        "ttl_seconds": 300,  # 5 min
        "storage": "redis",
        "max_items": 20,
        "description": "Current turn context - scratchpad",
    },
    MemoryLayer.SHORT_TERM: {
        "ttl_seconds": 86400 * 7,  # 7 days
        "storage": "redis+db",
        "max_items": 100,
        "description": "Session-level memory - recent context",
    },
    MemoryLayer.LONG_TERM: {
        "ttl_seconds": 0,  # never expire
        "storage": "db+qdrant",
        "max_items": 10000,
        "description": "Cross-session facts - user profile, key info",
    },
    MemoryLayer.EPISODIC: {
        "ttl_seconds": 86400 * 365,  # 1 year
        "storage": "db",
        "max_items": 50000,
        "description": "Past events and interactions",
    },
    MemoryLayer.SEMANTIC: {
        "ttl_seconds": 0,
        "storage": "qdrant",
        "max_items": 100000,
        "description": "Concepts, definitions, knowledge graph",
    },
    MemoryLayer.PROCEDURAL: {
        "ttl_seconds": 0,
        "storage": "db",
        "max_items": 5000,
        "description": "How-to steps, workflows, recipes",
    },
    MemoryLayer.FAILURE: {
        "ttl_seconds": 0,
        "storage": "db",
        "max_items": 10000,
        "description": "What went wrong and how to avoid",
    },
    MemoryLayer.PREFERENCE: {
        "ttl_seconds": 0,
        "storage": "db",
        "max_items": 1000,
        "description": "User preferences and settings",
    },
}
