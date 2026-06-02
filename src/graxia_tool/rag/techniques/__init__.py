"""Enterprise Agent OS — RAG Techniques Registry.

Provides a registry of RAG enhancement techniques that can be composed
into retrieval pipelines.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from ..chunker import Chunk
from ..retriever import RetrievalResult


@dataclass
class TechniqueResult:
    """Result of applying a RAG technique."""
    chunks: List[Chunk]
    scores: List[float]
    metadata: Dict[str, Any] = field(default_factory=dict)


class TechniqueRegistry:
    """Registry of available RAG techniques."""

    def __init__(self):
        self._techniques: Dict[str, Callable] = {}

    def register(self, name: str, func: Callable) -> None:
        """Register a technique by name."""
        self._techniques[name] = func

    def get(self, name: str) -> Optional[Callable]:
        """Get a registered technique."""
        return self._techniques.get(name)

    def list_all(self) -> List[str]:
        """List all registered technique names."""
        return list(self._techniques.keys())

    def apply(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Apply a registered technique."""
        func = self._techniques.get(name)
        if not func:
            raise ValueError(f"Unknown technique: {name}. Available: {self.list_all()}")
        return func(*args, **kwargs)


# Global registry instance
_registry = TechniqueRegistry()


def get_registry() -> TechniqueRegistry:
    """Get the global technique registry."""
    return _registry


def register_technique(name: str, func: Callable) -> None:
    """Register a technique in the global registry."""
    _registry.register(name, func)
