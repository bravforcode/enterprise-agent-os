"""BM25 + optional LLM re-rank over skill files.

The Acontext design choice: no embeddings, just lexical search. BM25
gives us ranking without an embedding model. We then optionally ask
the LLM to re-rank the top-K candidates using its world knowledge.

This module ships its own BM25 implementation (Robust01 variant) to
avoid adding a runtime dependency on ``rank_bm25``. It is short,
correct for short documents, and easy to audit.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .schema import Skill
from .skill_store import SkillStore


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Lower-case word tokens. No stemming, no stop-words: short doc
    corpora (skill files) don't benefit much and we want predictable
    behavior across languages.
    """
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


# ---------------------------------------------------------------------------
# Tiny BM25
# ---------------------------------------------------------------------------

@dataclass
class _DocStats:
    length: int
    tf: Counter


class BM25:
    """A tiny BM25Okapi implementation.

    Args:
        k1: Term-frequency saturation. Classic value 1.5.
        b:  Document-length normalization. Classic value 0.75.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: List[_DocStats] = []
        self._doc_tokens: List[List[str]] = []
        self._df: Counter = Counter()
        self._avgdl: float = 0.0
        self._built = False

    def index(self, docs: Sequence[str]) -> None:
        """Index a list of documents (one per skill body+description)."""
        self._docs = []
        self._doc_tokens = []
        self._df = Counter()
        total_len = 0
        for text in docs:
            tokens = _tokenize(text)
            self._doc_tokens.append(tokens)
            tf = Counter(tokens)
            self._docs.append(_DocStats(length=len(tokens), tf=tf))
            total_len += len(tokens)
            for term in set(tokens):
                self._df[term] += 1
        n = max(1, len(self._docs))
        self._avgdl = total_len / n
        self._built = True

    def __len__(self) -> int:
        return len(self._docs)

    def score(self, query: str) -> List[float]:
        """Return a score for every indexed document (in index order)."""
        if not self._built or not self._docs:
            return []
        q_tokens = _tokenize(query)
        if not q_tokens:
            return [0.0] * len(self._docs)
        n = len(self._docs)
        scores = [0.0] * n
        for term in q_tokens:
            df = self._df.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            for i, doc in enumerate(self._docs):
                f = doc.tf.get(term, 0)
                if f == 0:
                    continue
                num = f * (self.k1 + 1)
                den = f + self.k1 * (1 - self.b + self.b * (doc.length / max(1.0, self._avgdl)))
                scores[i] += idf * (num / den)
        return scores


# ---------------------------------------------------------------------------
# Recall API
# ---------------------------------------------------------------------------

@dataclass
class RecallHit:
    skill: Skill
    score: float
    bm25_rank: int
    rerank_score: Optional[float] = None


def _skill_to_text(skill: Skill) -> str:
    """Concatenate description, tags, and body for indexing."""
    parts: List[str] = [skill.meta.name, skill.meta.description]
    if skill.meta.tags:
        parts.append(" ".join(skill.meta.tags))
    parts.append(skill.body)
    return "\n".join(parts)


def recall_skills(
    store: SkillStore,
    query: str,
    limit: int = 5,
    *,
    rerank: bool = False,
    llm_client: Optional[Any] = None,
    rerank_pool: int = 20,
    min_score: float = 0.0,
) -> List[RecallHit]:
    """Recall skills for a query.

    Args:
        store: The :class:`SkillStore` to search.
        query: Free-text query.
        limit: Maximum number of hits to return.
        rerank: If True, ask the LLM to re-rank the top ``rerank_pool``.
        llm_client: An LLM client with ``.complete(prompt, system)`` —
                    only used when ``rerank`` is True.
        rerank_pool: How many BM25 candidates to send to the LLM.
        min_score: Drop hits below this BM25 score (default 0.0 = keep all).

    Returns:
        A list of :class:`RecallHit` sorted by descending score.
    """
    if limit <= 0:
        return []

    skills = store.list_skills()
    if not skills:
        return []

    texts = [_skill_to_text(s) for s in skills]
    bm25 = BM25()
    bm25.index(texts)
    scores = bm25.score(query)

    # Build ranked list, but keep the original index → skill mapping
    ranked: List[Tuple[int, float]] = sorted(
        enumerate(scores), key=lambda x: x[1], reverse=True
    )
    # Filter very low scores
    ranked = [(i, sc) for i, sc in ranked if sc > min_score]

    pool_n = min(max(limit * 2, rerank_pool), len(ranked)) if rerank else min(limit, len(ranked))
    pool = ranked[:pool_n]

    hits: List[RecallHit] = [
        RecallHit(skill=skills[i], score=sc, bm25_rank=rank + 1)
        for rank, (i, sc) in enumerate(pool)
    ]

    if rerank and llm_client is not None and hits:
        hits = _llm_rerank(query, hits, llm_client)
    elif rerank and llm_client is None:
        # No LLM available; fall back to BM25 order, but mark as unranked
        for h in hits:
            h.rerank_score = None

    return hits[:limit]


def _llm_rerank(query: str, hits: List[RecallHit], llm_client: Any) -> List[RecallHit]:
    """Ask the LLM to re-rank the BM25 candidates. Falls back gracefully
    on parse failure or LLM error.
    """
    if not hits:
        return hits

    candidates_block = "\n".join(
        f"[{i}] {h.skill.meta.name} — {h.skill.meta.description}\n"
        f"     body: {(h.skill.body or '')[:300].replace(chr(10), ' ')}"
        for i, h in enumerate(hits)
    )
    system = (
        "You are a search re-ranker. Score each candidate 0.0-1.0 for how "
        "well it answers the user's query. Return STRICT JSON: "
        '{"scores": [<float>, <float>, ...]}. No prose, no code fences.'
    )
    user = f"Query: {query}\n\nCandidates:\n{candidates_block}\n\nReturn JSON only."
    try:
        import asyncio
        import json
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Caller is in async context; cannot use run_until_complete.
                # Defer to a sync best-effort: skip re-rank.
                return sorted(hits, key=lambda h: h.score, reverse=True)
        except RuntimeError:
            pass
        resp = asyncio.run(
            llm_client.complete(prompt=user, system=system, max_tokens=200, temperature=0.0)
        )
        content = getattr(resp, "content", "") or ""
        # Extract the JSON object
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"no JSON in re-rank response: {content[:200]}")
        parsed = json.loads(content[start:end + 1])
        raw_scores = parsed.get("scores", [])
        if not isinstance(raw_scores, list):
            raise ValueError("scores field is not a list")
        for i, h in enumerate(hits):
            if i < len(raw_scores):
                try:
                    h.rerank_score = float(raw_scores[i])
                except (TypeError, ValueError):
                    h.rerank_score = None
        # Sort by rerank score (None treated as 0)
        hits.sort(key=lambda h: (h.rerank_score if h.rerank_score is not None else 0.0), reverse=True)
    except Exception:
        # On any failure, return BM25-ordered list unchanged
        hits.sort(key=lambda h: h.score, reverse=True)
    return hits
