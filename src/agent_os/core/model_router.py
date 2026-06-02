"""Enterprise Agent OS — Model Router.

Routes queries to appropriate models based on:
- Complexity (Haiku for simple, GPT-4o for complex)
- Cost constraints
- Latency requirements
- Capability needs (vision, function calling, etc.)
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger("model_router")


class ModelTier(str, Enum):
    HAIKU = "haiku"  # Cheapest, fastest
    MINI = "mini"    # Mid-tier
    MAIN = "main"    # Most capable
    SPECIALIZED = "specialized"  # Vision, embedding, etc.


@dataclass
class ModelSpec:
    """Model specification."""
    name: str
    tier: ModelTier
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_tokens: int
    latency_ms: int  # typical
    capabilities: list[str]  # ["text", "vision", "function_calling", "json_mode"]


# Default model catalog
MODEL_CATALOG: dict[ModelTier, ModelSpec] = {
    ModelTier.HAIKU: ModelSpec(
        name="claude-3-haiku-20240307",
        tier=ModelTier.HAIKU,
        cost_per_1k_input=0.00025,
        cost_per_1k_output=0.00125,
        max_tokens=4096,
        latency_ms=300,
        capabilities=["text", "function_calling"],
    ),
    ModelTier.MINI: ModelSpec(
        name="gpt-4o-mini",
        tier=ModelTier.MINI,
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        max_tokens=16384,
        latency_ms=500,
        capabilities=["text", "function_calling", "json_mode"],
    ),
    ModelTier.MAIN: ModelSpec(
        name="gpt-4o",
        tier=ModelTier.MAIN,
        cost_per_1k_input=0.005,
        cost_per_1k_output=0.015,
        max_tokens=128000,
        latency_ms=1500,
        capabilities=["text", "vision", "function_calling", "json_mode"],
    ),
    ModelTier.SPECIALIZED: ModelSpec(
        name="text-embedding-3-small",
        tier=ModelTier.SPECIALIZED,
        cost_per_1k_input=0.00002,
        cost_per_1k_output=0,
        max_tokens=8191,
        latency_ms=100,
        capabilities=["embedding"],
    ),
}


# --- Complexity detection ---
SIMPLE_PATTERNS = [
    r"^(yes|no|ok|thanks|got it|sure|please|hello|hi)\b",
    r"^(what|when|where|who|how much|how many)\b.{1,50}\?$",
    r"^(show|list|display|get)\b.{1,50}$",
]

MEDIUM_PATTERNS = [
    r"\b(write|create|implement|build|add|modify|update|change)\b",
    r"\b(explain|describe|tell me about)\b",
    r"\b(fix|debug|error|bug)\b",
    r"\b(test|pytest)\b",
]

COMPLEX_PATTERNS = [
    r"\b(architect|design|plan|strategy|approach)\b",
    r"\b(analyze|evaluate|compare|assess)\b",
    r"\b(refactor|optimize|redesign)\b",
    r"\b(multi-step|complex|comprehensive)\b",
]


def detect_complexity(query: str) -> ModelTier:
    """Detect query complexity to pick model tier."""
    q_lower = query.lower()

    # Check complex patterns first
    for pattern in COMPLEX_PATTERNS:
        if re.search(pattern, q_lower):
            return ModelTier.MAIN

    # Then medium
    for pattern in MEDIUM_PATTERNS:
        if re.search(pattern, q_lower):
            return ModelTier.MINI

    # Then simple
    for pattern in SIMPLE_PATTERNS:
        if re.search(pattern, q_lower):
            return ModelTier.HAIKU

    # Default: haiku for short queries, mini for longer
    if len(query) < 50:
        return ModelTier.HAIKU
    return ModelTier.MINI


class ModelRouter:
    """
    Routes queries to appropriate models.
    Considers: complexity, cost, latency, capabilities.
    """

    def __init__(self, default_tier: ModelTier = ModelTier.MINI):
        self.default_tier = default_tier
        self._usage: dict[str, int] = {}  # tier -> count

    def route(
        self,
        query: str,
        required_capabilities: Optional[list[str]] = None,
        max_cost: Optional[float] = None,
        max_latency_ms: Optional[int] = None,
    ) -> ModelSpec:
        """
        Route a query to the best model.

        Args:
            query: The user query
            required_capabilities: Required model capabilities
            max_cost: Maximum cost per request
            max_latency_ms: Maximum acceptable latency

        Returns:
            ModelSpec for the chosen model
        """
        # Detect complexity
        tier = detect_complexity(query)

        # Capability filter
        candidates = []
        for t, spec in MODEL_CATALOG.items():
            if required_capabilities:
                if not all(c in spec.capabilities for c in required_capabilities):
                    continue
            if max_cost and spec.cost_per_1k_input > max_cost:
                continue
            if max_latency_ms and spec.latency_ms > max_latency_ms:
                continue
            candidates.append((t, spec))

        if not candidates:
            # Fallback to default
            spec = MODEL_CATALOG[self.default_tier]
        else:
            # Pick the tier matching detected complexity
            matching = [(t, s) for t, s in candidates if t == tier]
            if matching:
                spec = matching[0][1]
            else:
                # Pick cheapest available
                spec = min(candidates, key=lambda x: x[1].cost_per_1k_input)[1]

        # Track usage
        self._usage[spec.tier.value] = self._usage.get(spec.tier.value, 0) + 1
        logger.info(
            "model_routed",
            tier=spec.tier.value,
            model=spec.name,
            cost_in=spec.cost_per_1k_input,
        )
        return spec

    def estimate_cost(self, model: ModelSpec, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost for a request."""
        return (
            (tokens_in / 1000) * model.cost_per_1k_input
            + (tokens_out / 1000) * model.cost_per_1k_output
        )

    def get_usage(self) -> dict[str, int]:
        """Get tier usage stats."""
        return dict(self._usage)
