"""Qwen Memory — Use qwen3.5:4b as the brain for context memory and caching.

Provides:
- Session summarization (compress conversations into compact memories)
- Memory re-ranking (improve BM25 results with semantic re-ranking)
- Auto-categorization (classify memories automatically)
- Context compression (reduce context size before storage)
- Cache key generation (create deterministic cache keys)
- Memory decay (score relevance based on age)
- Memory merging (combine duplicate memories)
- Urgency classification (prioritize important memories)
- Recall query generation (create better search queries)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import httpx


# ── Config ──────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"


# ── Ollama Client ───────────────────────────────────────────────────────

class QwenClient:
    """Thin wrapper around Ollama API for qwen3.5 memory tasks."""

    def __init__(self, model: str = DEFAULT_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model = model
        self.base_url = base_url

    def _generate(self, prompt: str, max_tokens: int = 200) -> str:
        """Call Ollama API with think=false."""
        try:
            r = httpx.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "think": False,
                    "options": {"num_predict": max_tokens},
                },
                timeout=60,
            )
            return r.json().get("response", "").strip()
        except Exception:
            return ""

    def is_available(self) -> bool:
        """Check if Ollama + model is running."""
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            models = [m["name"] for m in r.json().get("models", [])]
            return any(self.model in m for m in models)
        except Exception:
            return False


# ── Memory Tasks ────────────────────────────────────────────────────────

@dataclass
class MemoryTask:
    """Result of a qwen memory task."""
    task: str
    input_text: str
    output: str
    latency_s: float
    success: bool


class QwenMemory:
    """Use qwen3.5 as the brain for memory operations."""

    def __init__(self, client: Optional[QwenClient] = None):
        self.client = client or QwenClient()

    def summarize_session(self, messages: list[dict], max_tokens: int = 150) -> MemoryTask:
        """Summarize a conversation into a compact memory entry."""
        conv = "\n".join(f"{m['role']}: {m['content']}" for m in messages[-10:])
        prompt = (
            f"Summarize this conversation in 2-3 sentences, capturing key facts, "
            f"decisions, and outcomes:\n\n{conv}\n\n"
            "Return ONLY the summary, no explanation."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("summarize", conv[:200], output, time.time() - start, bool(output))

    def rerank(self, query: str, candidates: list[str], max_tokens: int = 50) -> MemoryTask:
        """Re-rank search results by semantic relevance."""
        numbered = "\n".join(f"({i+1}) {c}" for i, c in enumerate(candidates[:5]))
        prompt = (
            f"Rank these search results by relevance to the query:\n"
            f"Query: {query}\n{numbered}\n\n"
            f"Return ONLY the rank as numbers (1=best), comma-separated. "
            f"Example: 3,1,2"
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("rerank", query, output, time.time() - start, bool(output))

    def categorize(self, content: str, max_tokens: int = 20) -> MemoryTask:
        """Categorize a memory into task/codebase/preference/learning."""
        prompt = (
            f"Category (task/codebase/preference/learning): {content}\n"
            "Return ONLY the category name."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("categorize", content[:100], output, time.time() - start, bool(output))

    def extract_facts(self, content: str, max_tokens: int = 150) -> MemoryTask:
        """Extract key facts from content."""
        prompt = (
            f"Extract 3-5 key facts from this:\n{content}\n\n"
            "Return as numbered list."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("extract", content[:200], output, time.time() - start, bool(output))

    def compress(self, content: str, max_tokens: int = 100) -> MemoryTask:
        """Compress content to 1 sentence."""
        prompt = (
            f"Compress to 1 sentence:\n{content}\n\n"
            "Return ONLY the compressed sentence."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("compress", content[:200], output, time.time() - start, bool(output))

    def generate_cache_key(self, prompt: str, max_tokens: int = 30) -> MemoryTask:
        """Generate a short cache key."""
        p = (
            f"Short cache key for: {prompt}\n"
            "Return only the key, no explanation."
        )
        start = time.time()
        output = self.client._generate(p, max_tokens)
        return MemoryTask("cache_key", prompt[:100], output, time.time() - start, bool(output))

    def score_decay(self, memory_age_days: int, query_relevance: str, max_tokens: int = 10) -> MemoryTask:
        """Score relevance based on age and query match."""
        prompt = (
            f"Score 0-1: memory about '{query_relevance}' stored {memory_age_days} days ago. "
            "Return only the number."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("decay", f"age={memory_age_days}d", output, time.time() - start, bool(output))

    def merge_memories(self, memories: list[str], max_tokens: int = 100) -> MemoryTask:
        """Merge duplicate memories into one."""
        numbered = "\n".join(f"({i+1}) {m}" for i, m in enumerate(memories))
        prompt = (
            f"Merge these memories into 1 concise memory:\n{numbered}\n\n"
            "Return ONLY the merged memory."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("merge", str(memories)[:200], output, time.time() - start, bool(output))

    def classify_urgency(self, content: str, max_tokens: int = 10) -> MemoryTask:
        """Classify urgency as low/medium/high."""
        prompt = (
            f"Urgency low/medium/high: {content}\n"
            "Return only the level."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("urgency", content[:100], output, time.time() - start, bool(output))

    def generate_recall_query(self, context: str, max_tokens: int = 30) -> MemoryTask:
        """Generate a search query to find relevant memories."""
        prompt = (
            f"Generate a search query to find memories about:\n{context}\n\n"
            "Return only the query."
        )
        start = time.time()
        output = self.client._generate(prompt, max_tokens)
        return MemoryTask("recall_query", context[:100], output, time.time() - start, bool(output))


# ── Enhanced SessionMemory ──────────────────────────────────────────────

class QwenSessionMemory:
    """SessionMemory enhanced with qwen3.5 brain.

    Wraps the existing SessionMemory and adds qwen-powered:
    - Auto-categorization on store
    - Semantic re-ranking on recall
    - Session summarization on session end
    """

    def __init__(self, db_path: Optional[str] = None):
        from ..session_memory import SessionMemory
        self._memory = SessionMemory(db_path=db_path)
        self._qwen = QwenMemory()
        self._qwen_available = self._qwen.client.is_available()

    @property
    def qwen_available(self) -> bool:
        return self._qwen_available

    def store_with_category(self, memory_type: str, content: str, **kwargs) -> str:
        """Store memory with automatic categorization by qwen."""
        if self._qwen_available and memory_type == "auto":
            result = self._qwen.categorize(content)
            memory_type = result.output if result.success else "preference"

        if memory_type == "task":
            from ..session_memory import TaskRecord
            record = TaskRecord(
                prompt=content,
                outcome=kwargs.get("outcome", ""),
                success=kwargs.get("success", True),
                duration_ms=kwargs.get("duration_ms", 0),
                agent_type=kwargs.get("agent_type", ""),
                intent=kwargs.get("intent", ""),
            )
            return self._memory.remember_task(record)
        elif memory_type == "codebase":
            from ..session_memory import CodebaseKnowledge
            kb = CodebaseKnowledge(
                path=kwargs.get("path", ""),
                summary=content,
                patterns=kwargs.get("patterns", []),
                architecture_notes=kwargs.get("architecture_notes", ""),
            )
            return self._memory.remember_codebase(kb)
        else:
            key = kwargs.get("key", "general")
            self._memory.remember_preference(key, content)
            return key

    def recall_with_rerank(self, query: str, limit: int = 5, memory_type: Optional[str] = None) -> list:
        """Recall memories with qwen re-ranking."""
        # Get more candidates than needed for re-ranking
        candidates = self._memory.recall(query, limit=limit * 3, memory_type=memory_type)

        if not self._qwen_available or len(candidates) <= 1:
            return candidates[:limit]

        # Re-rank with qwen
        candidate_texts = [c.content for c in candidates]
        result = self._qwen.rerank(query, candidate_texts)

        if not result.success:
            return candidates[:limit]

        # Parse ranking
        try:
            ranks = [int(x.strip()) - 1 for x in result.output.split(",")]
            reranked = [candidates[i] for i in ranks if 0 <= i < len(candidates)]
            return reranked[:limit]
        except (ValueError, IndexError):
            return candidates[:limit]

    def summarize_and_store(self, messages: list[dict]) -> Optional[str]:
        """Summarize a session and store as memory."""
        if not self._qwen_available:
            return None

        result = self._qwen.summarize_session(messages)
        if result.success:
            return self._memory.remember_preference(
                "session_summary",
                result.output,
            )
        return None
