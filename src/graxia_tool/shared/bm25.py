"""Shared BM25 scoring — single implementation used by SessionMemory, ContextCache, AutoRouter."""
from __future__ import annotations
import re
from typing import List


def bm25_score(query_words: List[str], text: str, k1: float = 1.5) -> float:
    """BM25-inspired keyword scoring with TF saturation and length normalization."""
    if not query_words or not text:
        return 0.0
    text_lower = text.lower()
    text_len = max(len(text_lower.split()), 1)
    score = 0.0
    for w in query_words:
        tf = text_lower.count(w)
        if tf > 0:
            saturated = tf / (tf + k1)
            length_penalty = 1.0 / (1.0 + 0.5 * (text_len / 100))
            score += saturated * length_penalty
    return score / max(len(query_words), 1)


def bm25_overlap(kw1: List[str], kw2: List[str]) -> float:
    """BM25-inspired overlap between two keyword lists."""
    if not kw1 or not kw2:
        return 0.0
    set2 = set(kw2)
    return sum(1 for w in kw1 if w in set2) / max(len(kw1), 1)


_STOP_WORDS = frozenset([
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "about", "this",
    "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "she", "they", "them", "and", "or", "but", "not",
    "if", "then", "else", "when", "up", "out", "so", "no", "just",
])


def extract_keywords(text: str) -> List[str]:
    """Extract meaningful keywords, filtering stop words."""
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return [w for w in words if w not in _STOP_WORDS and len(w) > 2]
