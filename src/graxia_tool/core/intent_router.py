"""Enterprise Agent OS — Intent Router (classification + risk scoring).

Classifies user queries into intent + domain + risk level.
Uses lightweight LLM (Haiku/GPT-4o-mini) for classification.
Falls back to keyword matching when LLM unavailable.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional
from ..core.models import RiskLevel


class Intent(str, Enum):
    CODE = "code"
    DEBUG = "debug"
    TEST = "test"
    REVIEW = "review"
    DEPLOY = "deploy"
    DOCUMENT = "document"
    RESEARCH = "research"
    DATA = "data"
    SYSTEM = "system"
    CONVERSATION = "conversation"
    UNKNOWN = "unknown"


class Domain(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    RUST = "rust"
    GO = "go"
    SQL = "sql"
    DEVOPS = "devops"
    FRONTEND = "frontend"
    BACKEND = "backend"
    INFRA = "infra"
    SECURITY = "security"
    DATA = "data"
    GENERAL = "general"


@dataclass
class ClassifiedIntent:
    intent: Intent
    domain: Domain
    confidence: float
    risk_level: RiskLevel
    entities: dict[str, str]  # extracted entities (file names, URLs, etc.)
    raw_classification: str  # LLM response or keyword match info


# --- Keyword-based classification (fallback) ---
INTENT_KEYWORDS: dict[Intent, list[str]] = {
    Intent.CODE: ["write", "create", "implement", "build", "add", "new", "function", "class", "module"],
    Intent.DEBUG: ["debug", "fix", "bug", "error", "issue", "broken", "fail", "crash", "exception"],
    Intent.TEST: ["test", "pytest", "unittest", "spec", "assert", "mock", "coverage", "tdd"],
    Intent.REVIEW: ["review", "pr", "pull request", "code review", "feedback", "improve"],
    Intent.DEPLOY: ["deploy", "release", "ship", "production", "live", "ci", "cd", "pipeline"],
    Intent.DOCUMENT: ["document", "docs", "readme", "comment", "explain", "describe"],
    Intent.RESEARCH: ["research", "find", "search", "lookup", "investigate", "explore", "analyze"],
    Intent.DATA: ["data", "csv", "json", "database", "query", "sql", "parse", "extract"],
    Intent.SYSTEM: ["system", "config", "setup", "install", "env", "path", "shell"],
}

DOMAIN_KEYWORDS: dict[Domain, list[str]] = {
    Domain.PYTHON: ["python", "py", "pip", "pytest", "django", "flask", "fastapi", "uvicorn"],
    Domain.TYPESCRIPT: ["typescript", "ts", "tsx", "npm", "node", "react", "next", "vite"],
    Domain.RUST: ["rust", "cargo", "rustc", "clippy", "wasm"],
    Domain.GO: ["go", "golang", "goroutine", "channel"],
    Domain.SQL: ["sql", "postgres", "mysql", "sqlite", "query", "select", "join"],
    Domain.DEVOPS: ["docker", "kubernetes", "k8s", "ci", "cd", "github actions", "jenkins"],
    Domain.FRONTEND: ["frontend", "ui", "css", "html", "react", "vue", "svelte"],
    Domain.BACKEND: ["backend", "api", "rest", "graphql", "server", "endpoint"],
    Domain.INFRA: ["infra", "aws", "gcp", "azure", "terraform", "ansible"],
    Domain.SECURITY: ["security", "auth", "jwt", "oauth", "encryption", "vulnerability"],
}

RISK_KEYWORDS: dict[RiskLevel, list[str]] = {
    RiskLevel.CRITICAL: ["production", "prod", "live", "deploy to prod", "rm -rf", "drop table", "delete all"],
    RiskLevel.HIGH: ["database", "db", "migrate", "schema", "auth", "secret", "key", "token", "password"],
    RiskLevel.MEDIUM: ["config", "settings", "env", "file", "write", "create", "modify", "update"],
    RiskLevel.LOW: ["read", "view", "show", "list", "search", "find", "explain", "help"],
}


def _keyword_classify(query: str) -> ClassifiedIntent:
    """Fast keyword-based classification (no LLM needed)."""
    q_lower = query.lower()

    # Intent (word-boundary matching to avoid false positives like "test" in "latest")
    intent_scores: dict[Intent, float] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', q_lower))
        if score > 0:
            intent_scores[intent] = score
    intent = max(intent_scores, key=intent_scores.get) if intent_scores else Intent.CONVERSATION
    confidence = min(intent_scores.get(intent, 0) / 3, 1.0)

    # Domain
    domain_scores: dict[Domain, float] = {}
    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', q_lower))
        if score > 0:
            domain_scores[domain] = score
    domain = max(domain_scores, key=domain_scores.get) if domain_scores else Domain.GENERAL

    # Risk
    risk_scores: dict[RiskLevel, float] = {}
    for level, keywords in RISK_KEYWORDS.items():
        score = sum(1 for kw in keywords if re.search(r'\b' + re.escape(kw) + r'\b', q_lower))
        if score > 0:
            risk_scores[level] = score
    risk = max(risk_scores, key=risk_scores.get) if risk_scores else RiskLevel.LOW

    # Extract entities
    entities = {}
    # File paths
    file_match = re.search(r'[\w/\\.-]+\.\w{1,5}', query)
    if file_match:
        entities["file"] = file_match.group(0)
    # URLs
    url_match = re.search(r'https?://\S+', query)
    if url_match:
        entities["url"] = url_match.group(0)

    return ClassifiedIntent(
        intent=intent,
        domain=domain,
        confidence=confidence,
        risk_level=risk,
        entities=entities,
        raw_classification="keyword",
    )


async def classify_intent(query: str, llm_func=None) -> ClassifiedIntent:
    """
    Classify user query into intent + domain + risk.

    Args:
        query: User's natural language query
        llm_func: Optional async function(prompt) -> str for LLM classification

    Returns:
        ClassifiedIntent with intent, domain, confidence, risk_level, entities
    """
    # Try LLM classification first
    if llm_func:
        try:
            prompt = f"""Classify this user query. Return JSON only.

Query: {query}

Return exactly:
{{"intent": "code|debug|test|review|deploy|document|research|data|system|conversation",
  "domain": "python|typescript|rust|go|sql|devops|frontend|backend|infra|security|data|general",
  "confidence": 0.0-1.0,
  "risk": "low|medium|high|critical",
  "entities": {{"key": "value"}}}}"""

            response = await llm_func(prompt)
            import json
            # Extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return ClassifiedIntent(
                    intent=Intent(data.get("intent", "unknown")),
                    domain=Domain(data.get("domain", "general")),
                    confidence=float(data.get("confidence", 0.8)),
                    risk_level=RiskLevel(data.get("risk", "low")),
                    entities=data.get("entities", {}),
                    raw_classification="llm",
                )
        except Exception:
            pass  # Fall through to keyword classification

    # Fallback: keyword classification
    return _keyword_classify(query)
