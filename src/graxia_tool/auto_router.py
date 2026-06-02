"""Enterprise Agent OS — Auto Router.

Unified auto-router that analyzes a prompt and automatically selects:
- Skills to load
- RAG technique to use
- MCP tools to invoke
- Subagent to spawn
- Model tier for the task

No LLM needed for routing decisions — uses fast keyword pattern matching.
"""
from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .core.intent_router import Intent, Domain, _keyword_classify
from .core.logging import get_logger
from .core.model_router import ModelTier, detect_complexity

logger = get_logger("auto_router")


# ─────────────────────────────────────────────────────────────────────────────
# Routing decision
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RoutingDecision:
    """Complete routing decision for a user prompt."""

    skills: list[str] = field(default_factory=list)
    rag_technique: str = "hybrid_search"
    rag_query: str = ""
    agent_type: str = "general"
    model_tier: str = "mini"
    mcp_tools: list[str] = field(default_factory=list)
    intent: str = "unknown"
    confidence: float = 0.0
    context_notes: str = ""
    cache_key: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict."""
        return {
            "skills": self.skills,
            "rag_technique": self.rag_technique,
            "rag_query": self.rag_query,
            "agent_type": self.agent_type,
            "model_tier": self.model_tier,
            "mcp_tools": self.mcp_tools,
            "intent": self.intent,
            "confidence": self.confidence,
            "context_notes": self.context_notes,
            "cache_key": self.cache_key,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Skill selection mapping: intent+keywords → skill names
# ─────────────────────────────────────────────────────────────────────────────

SKILL_INTENT_MAP: dict[Intent, list[str]] = {
    Intent.CODE: ["rtk-tdd", "test-driven-development", "code-simplification"],
    Intent.DEBUG: ["systematic-debugging", "doubt-driven-development"],
    Intent.TEST: ["rtk-tdd", "test-driven-development"],
    Intent.REVIEW: ["caveman-review", "requesting-code-review", "receiving-code-review"],
    Intent.DEPLOY: ["finishing-a-development-branch"],
    Intent.DOCUMENT: ["docx", "writing-plans"],
    Intent.RESEARCH: ["web-search", "openai-docs"],
    Intent.DATA: ["xlsx"],
    Intent.SYSTEM: ["mcp-builder", "plugin-creator"],
    Intent.CONVERSATION: [],
    Intent.UNKNOWN: [],
}

SKILL_KEYWORD_OVERRIDES: dict[str, list[str]] = {
    "pptx": ["pptx", "presentation", "slide", "deck", "powerpoint"],
    "pdf": ["pdf", "acrobat", "document"],
    "imagegen": ["image", "photo", "illustration", "picture", "generate image"],
    "caveman": ["caveman", "compress", "short", "brief"],
    "pordee": ["pordee", "thai", "pattaka"],
    "xlsx": ["spreadsheet", "excel", "csv", "table", "xlsx"],
    "docx": ["word", "docx", "document", "report"],
    "web-search": ["search", "lookup", "find online", "google"],
    "mcp-builder": ["mcp server", "mcp tool", "mcp"],
    "plugin-creator": ["plugin", "extension", "add-on"],
    "lean-ctx": ["context", "token", "compress"],
    "design-patterns": ["pattern", "design", "architecture", "newtype", "builder"],
}


# ─────────────────────────────────────────────────────────────────────────────
# RAG technique selection: query characteristics → technique
# ─────────────────────────────────────────────────────────────────────────────

RAG_TECHNIQUE_PATTERNS: list[tuple[str, str, str]] = [
    # (pattern, technique, description)
    (r"\b(how|why|explain|reason|cause)\b.{0,30}\b(because|since|due to)\b", "self_rag", "self-verification needed"),
    (r"\b(multi.?hop|step.?by.?step|chain|connect|relate)\b", "agentic_rag", "multi-hop reasoning"),
    (r"\b(compare|contrast|difference|versus|vs\.?|both|either)\b", "diversity_rag", "diverse perspectives"),
    (r"\b(error|mistake|wrong|incorrect|fix|correct|validate)\b", "corrective_rag", "error correction"),
    (r"\b(code|function|class|def |import |struct |fn |func)\b", "chunk_free_rag", "code-specific"),
    (r"\b(graph|relationship|entity|connected|network|depend)\b", "graph_rag", "graph relationships"),
    (r"\b(summarize|overview|tldr|brief|executive)\b", "hybrid_search", "simple factual"),
]

DEFAULT_RAG_TECHNIQUE = "hybrid_search"


# ─────────────────────────────────────────────────────────────────────────────
# Agent selection: intent → agent type
# ─────────────────────────────────────────────────────────────────────────────

INTENT_AGENT_MAP: dict[Intent, str] = {
    Intent.CODE: "coder",
    Intent.DEBUG: "debugger",
    Intent.TEST: "tester",
    Intent.REVIEW: "reviewer",
    Intent.DEPLOY: "deployer",
    Intent.DOCUMENT: "documenter",
    Intent.RESEARCH: "researcher",
    Intent.DATA: "data_engineer",
    Intent.SYSTEM: "sysadmin",
    Intent.CONVERSATION: "conversational",
    Intent.UNKNOWN: "general",
}


# ─────────────────────────────────────────────────────────────────────────────
# MCP tool selection: intent+keywords → MCP tools
# ─────────────────────────────────────────────────────────────────────────────

INTENT_MCP_TOOLS: dict[Intent, list[str]] = {
    Intent.CODE: ["agent_list", "skills_list"],
    Intent.DEBUG: ["agent_list", "skills_list"],
    Intent.TEST: ["agent_list", "skills_list"],
    Intent.REVIEW: ["agent_list", "skills_list"],
    Intent.DEPLOY: ["pipeline_run", "governance_check"],
    Intent.DOCUMENT: ["skills_list"],
    Intent.RESEARCH: ["rag_query", "vault_search"],
    Intent.DATA: ["skills_list"],
    Intent.SYSTEM: ["system_status", "governance_check"],
    Intent.CONVERSATION: [],
    Intent.UNKNOWN: ["system_status"],
}

# Additional tools based on keyword signals
KEYWORD_MCP_TOOLS: list[tuple[str, list[str]]] = [
    (r"\b(memory|remember|recall|forgot)\b", ["memory_search"]),
    (r"\b(rag|document|retrieve|knowledge)\b", ["rag_query"]),
    (r"\b(status|health|uptime|monitor)\b", ["system_status"]),
    (r"\b(cost|budget|spend|token)\b", ["cost_report"]),
    (r"\b(vault|obsidian|note)\b", ["vault_search"]),
    (r"\b(govern|policy|allowed|approve)\b", ["governance_check"]),
    (r"\b(guard|safe|sanitize|block)\b", ["guard_check"]),
    (r"\b(cache|cached|cached?)\b", ["cache_get"]),
]


# ─────────────────────────────────────────────────────────────────────────────
# Auto Router
# ─────────────────────────────────────────────────────────────────────────────

class AutoRouter:
    """Analyzes user prompt and auto-selects skills, RAG, MCP tools, subagents.

    Usage:
        router = AutoRouter()
        decision = router.route("Fix the bug in auth.py that causes 500 errors")
        print(decision.agent_type)     # "debugger"
        print(decision.skills)         # ["systematic-debugging", "doubt-driven-development"]
        print(decision.rag_technique)  # "corrective_rag"
    """

    def __init__(self) -> None:
        self._route_count: int = 0
        self._route_times_ms: list[float] = []

    def route(
        self,
        prompt: str,
        context: Optional[dict[str, Any]] = None,
    ) -> RoutingDecision:
        """Main entry point. Returns complete routing decision.

        Args:
            prompt: User's natural language prompt.
            context: Optional context dict (session_memory, user_id, etc.).

        Returns:
            RoutingDecision with all routing choices.
        """
        start = time.monotonic()
        context = context or {}

        # 1. Intent classification (fast, keyword-based)
        classified = _keyword_classify(prompt)
        intent = classified.intent
        domain = classified.domain

        # 2. Skill selection
        skills = self._select_skills(intent, prompt)

        # 3. RAG technique selection
        rag_technique, rag_query = self._select_rag(prompt, intent)

        # 4. Agent selection
        agent_type = INTENT_AGENT_MAP.get(intent, "general")

        # 5. Model tier selection
        model_tier = detect_complexity(prompt).value

        # 6. MCP tool selection
        mcp_tools = self._select_mcp_tools(intent, prompt)

        # 7. Confidence scoring
        confidence = self._compute_confidence(classified.confidence, intent, prompt)

        # 8. Cache key
        cache_key = self._make_cache_key(prompt)

        # 9. Context notes
        context_notes = self._build_context_notes(intent, domain, skills, rag_technique)

        elapsed_ms = (time.monotonic() - start) * 1000
        self._route_count += 1
        self._route_times_ms.append(elapsed_ms)

        decision = RoutingDecision(
            skills=skills,
            rag_technique=rag_technique,
            rag_query=rag_query or prompt,
            agent_type=agent_type,
            model_tier=model_tier,
            mcp_tools=mcp_tools,
            intent=intent.value,
            confidence=confidence,
            context_notes=context_notes,
            cache_key=cache_key,
        )

        logger.info(
            "auto_routed",
            intent=intent.value,
            agent=agent_type,
            rag=rag_technique,
            skills=len(skills),
            mcp_tools=len(mcp_tools),
            confidence=round(confidence, 2),
            elapsed_ms=round(elapsed_ms, 2),
        )
        return decision

    # ── Skill selection ──────────────────────────────────────────────────

    def _select_skills(self, intent: Intent, prompt: str) -> list[str]:
        """Select skills based on intent and keyword matches."""
        p_lower = prompt.lower()
        selected: set[str] = set()

        # Base skills from intent
        for skill in SKILL_INTENT_MAP.get(intent, []):
            selected.add(skill)

        # Keyword overrides (word-boundary matching to avoid false positives)
        for skill_name, keywords in SKILL_KEYWORD_OVERRIDES.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', p_lower):
                    selected.add(skill_name)
                    break

        return sorted(selected)

    # ── RAG technique selection ──────────────────────────────────────────

    def _select_rag(self, prompt: str, intent: Intent) -> tuple[str, str]:
        """Select RAG technique and build optimized query."""
        p_lower = prompt.lower()

        # Check each pattern
        for pattern, technique, _desc in RAG_TECHNIQUE_PATTERNS:
            if re.search(pattern, p_lower):
                return technique, prompt

        # Intent-based defaults
        intent_rag: dict[Intent, str] = {
            Intent.RESEARCH: "hybrid_search",
            Intent.DATA: "chunk_free_rag",
            Intent.CODE: "chunk_free_rag",
            Intent.DEBUG: "corrective_rag",
            Intent.DOCUMENT: "hybrid_search",
            Intent.REVIEW: "diversity_rag",
        }

        technique = intent_rag.get(intent, DEFAULT_RAG_TECHNIQUE)

        # Build optimized RAG query
        rag_query = self._optimize_rag_query(prompt, intent)

        return technique, rag_query

    def _optimize_rag_query(self, prompt: str, intent: Intent) -> str:
        """Build an optimized query for RAG retrieval."""
        # Strip conversational filler for better retrieval
        removals = [
            r"^(please|can you|could you|would you|i need you to|help me)\s*",
            r"\b(thanks|thank you|please|kindly)\b",
        ]
        optimized = prompt
        for pattern in removals:
            optimized = re.sub(pattern, "", optimized, flags=re.IGNORECASE)

        optimized = optimized.strip()
        if len(optimized) < 5:
            optimized = prompt  # fallback to original

        return optimized

    # ── MCP tool selection ───────────────────────────────────────────────

    def _select_mcp_tools(self, intent: Intent, prompt: str) -> list[str]:
        """Select MCP tools based on intent and keyword signals."""
        p_lower = prompt.lower()
        tools: set[str] = set()

        # Base tools from intent
        for tool in INTENT_MCP_TOOLS.get(intent, []):
            tools.add(tool)

        # Keyword-triggered tools
        for pattern, tool_list in KEYWORD_MCP_TOOLS:
            if re.search(pattern, p_lower):
                for t in tool_list:
                    tools.add(t)

        return sorted(tools)

    # ── Confidence scoring ───────────────────────────────────────────────

    def _compute_confidence(
        self,
        keyword_confidence: float,
        intent: Intent,
        prompt: str,
    ) -> float:
        """Compute routing confidence score (0.0 to 1.0).

        Factors:
        - Keyword classification confidence
        - Prompt length (very short = lower confidence)
        - Intent specificity (unknown = low confidence)
        """
        score = keyword_confidence

        # Boost for longer, more specific prompts
        words = len(prompt.split())
        if words > 20:
            score = min(score + 0.1, 1.0)
        elif words < 3:
            score = max(score - 0.15, 0.1)

        # Penalize unknown/conversation intents
        if intent in (Intent.UNKNOWN, Intent.CONVERSATION):
            score = min(score, 0.4)

        # Boost for intents with strong keyword matches
        if intent in (Intent.CODE, Intent.DEBUG, Intent.TEST, Intent.DEPLOY):
            score = min(score + 0.05, 1.0)

        return round(min(max(score, 0.0), 1.0), 2)

    # ── Cache key ────────────────────────────────────────────────────────

    def _make_cache_key(self, prompt: str) -> str:
        """Generate a deterministic cache key for this prompt."""
        normalized = re.sub(r"\s+", " ", prompt.strip().lower())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # ── Context notes ────────────────────────────────────────────────────

    def _build_context_notes(
        self,
        intent: Intent,
        domain: Domain,
        skills: list[str],
        rag_technique: str,
    ) -> str:
        """Build human-readable context notes for the selected agent."""
        parts = [
            f"Intent: {intent.value}",
            f"Domain: {domain.value}",
            f"RAG: {rag_technique}",
        ]
        if skills:
            parts.append(f"Skills: {', '.join(skills)}")
        return " | ".join(parts)

    # ── Stats ────────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get routing statistics."""
        avg_ms = (
            sum(self._route_times_ms) / len(self._route_times_ms)
            if self._route_times_ms
            else 0.0
        )
        return {
            "route_count": self._route_count,
            "avg_route_ms": round(avg_ms, 2),
        }
