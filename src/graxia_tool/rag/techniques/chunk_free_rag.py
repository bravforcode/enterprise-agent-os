"""Enterprise Agent OS — Chunk-Free RAG (M-RAG style) Technique.

Extracts structured meta-markers (key-value pairs) from documents,
retrieves by matching against lightweight keys instead of chunks,
and decouples retrieval representation from generation content.

Based on M-RAG and Meta-RAG patterns from 2025 research.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from ..chunker import Chunk


@dataclass
class MetaMarker:
    """A structured key-value meta-marker extracted from text."""
    key: str
    value: str
    confidence: float
    chunk_id: str = ""
    source: str = ""


@dataclass
class AtomicFact:
    """An atomic fact extracted from text."""
    subject: str
    predicate: str
    obj: str  # "object" is a reserved word
    full_text: str
    chunk_id: str = ""


@dataclass
class ChunkFreeResult:
    """Result from chunk-free retrieval."""
    chunks: List[Chunk]
    scores: List[float]
    meta_markers: List[MetaMarker]
    atomic_facts: List[AtomicFact]


# ---------------------------------------------------------------------------
# Meta-Marker Extraction
# ---------------------------------------------------------------------------

# Patterns for extracting structured key-value pairs
_KEY_VALUE_PATTERNS = [
    # "Key: Value" or "Key: value"
    (r"^([A-Z][A-Za-z\s]{2,30}):\s*(.+)$", 0.9),
    # "- Key: Value" (bullet points)
    (r"^[-•*]\s*([A-Z][A-Za-z\s]{2,30}):\s*(.+)$", 0.85),
    # "**Key**: Value" (markdown bold)
    (r"^\*\*([^*]+)\*\*:\s*(.+)$", 0.95),
    # "Key = Value" (assignment style)
    (r"^([A-Za-z_]\w{2,30})\s*=\s*(.+)$", 0.8),
    # "[Key] Value" (tagged style)
    (r"^\[([A-Za-z]{2,30})\]\s*(.+)$", 0.75),
    # Section headers: "## Key\nValue"
    (r"^#{1,3}\s+(.+)\n(.+)$", 0.7),
]

# Common meta-marker keys
_COMMON_KEYS = {
    "title", "author", "date", "version", "status", "type", "category",
    "summary", "description", "purpose", "scope", "requirements",
    "definition", "overview", "conclusion", "result", "method",
    "approach", "architecture", "format", "language", "protocol",
    "specification", "reference", "source", "url", "id", "name",
}


def extract_meta_markers(text: str, chunk_id: str = "") -> List[MetaMarker]:
    """Extract structured key-value meta-markers from text.

    Finds patterns like "Key: Value", "- Key: Value", "**Key**: Value"
    and extracts them as lightweight retrieval keys.

    Args:
        text: Source text.
        chunk_id: ID of the chunk.

    Returns:
        List of MetaMarker objects.
    """
    markers = []
    lines = text.split("\n")

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        for pattern, confidence in _KEY_VALUE_PATTERNS:
            match = re.match(pattern, line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip() if match.lastindex >= 2 else ""

                # Validate key
                if len(key) < 2 or len(key) > 50:
                    continue
                # Skip if value is too long (probably not a meta-marker)
                if len(value) > 200:
                    continue

                markers.append(MetaMarker(
                    key=key,
                    value=value,
                    confidence=confidence,
                    chunk_id=chunk_id,
                ))
                break  # One marker per line

    return markers


def extract_meta_markers_from_chunks(chunks: List[Chunk]) -> Dict[str, List[MetaMarker]]:
    """Extract meta-markers from all chunks.

    Args:
        chunks: List of document chunks.

    Returns:
        Dict mapping chunk_id to list of meta-markers.
    """
    all_markers: Dict[str, List[MetaMarker]] = {}
    for chunk in chunks:
        markers = extract_meta_markers(chunk.content, chunk.id)
        if markers:
            all_markers[chunk.id] = markers
    return all_markers


# ---------------------------------------------------------------------------
# Atomic Fact Extraction
# ---------------------------------------------------------------------------

# Patterns for extracting atomic facts (Subject-Predicate-Object)
_ATOMIC_PATTERNS = [
    # "X is a Y"
    (r"^(.+?)\s+(?:is|are|was|were)\s+(?:a|an|the)?\s*(.+?)\.?$", "is_a"),
    # "X has Y"
    (r"^(.+?)\s+(?:has|have|had)\s+(.+?)\.?$", "has"),
    # "X uses Y"
    (r"^(.+?)\s+(?:uses?|use|using|utilizes?)\s+(.+?)\.?$", "uses"),
    # "X provides Y"
    (r"^(.+?)\s+(?:provides?|provide|offering)\s+(.+?)\.?$", "provides"),
    # "X enables Y"
    (r"^(.+?)\s+(?:enables?|enable|allows?|allow)\s+(.+?)\.?$", "enables"),
    # "X contains Y"
    (r"^(.+?)\s+(?:contains?|contain|includes?|include)\s+(.+?)\.?$", "contains"),
    # "X creates Y"
    (r"^(.+?)\s+(?:creates?|create|generates?|generate|produces?|produce)\s+(.+?)\.?$", "creates"),
    # "X requires Y"
    (r"^(.+?)\s+(?:requires?|require|needs?|need)\s+(.+?)\.?$", "requires"),
]


def extract_atomic_facts(text: str, chunk_id: str = "") -> List[AtomicFact]:
    """Extract atomic facts (Subject-Predicate-Object) from text.

    Splits text into sentences and applies pattern matching to extract
    structured triples.

    Args:
        text: Source text.
        chunk_id: ID of the chunk.

    Returns:
        List of AtomicFact objects.
    """
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    facts = []

    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 15 or len(sent) > 200:
            continue

        for pattern, predicate in _ATOMIC_PATTERNS:
            match = re.match(pattern, sent, re.IGNORECASE)
            if match:
                subject = match.group(1).strip()
                obj = match.group(2).strip()

                # Clean up subject/object
                subject = re.sub(r"^(The|A|An|This|These|Those)\s+", "", subject)
                obj = re.sub(r"^(the|a|an|their|its)\s+", "", obj)

                if len(subject) > 3 and len(obj) > 3:
                    facts.append(AtomicFact(
                        subject=subject,
                        predicate=predicate,
                        obj=obj,
                        full_text=sent,
                        chunk_id=chunk_id,
                    ))
                break  # One fact per sentence

    return facts


def extract_atomic_facts_from_chunks(chunks: List[Chunk]) -> Dict[str, List[AtomicFact]]:
    """Extract atomic facts from all chunks.

    Args:
        chunks: List of document chunks.

    Returns:
        Dict mapping chunk_id to list of atomic facts.
    """
    all_facts: Dict[str, List[AtomicFact]] = {}
    for chunk in chunks:
        facts = extract_atomic_facts(chunk.content, chunk.id)
        if facts:
            all_facts[chunk.id] = facts
    return all_facts


# ---------------------------------------------------------------------------
# Chunk-Free Retrieval
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    """Tokenize text into lowercase alphanumeric tokens."""
    return [t for t in re.findall(r"[a-z0-9\u0E00-\u0E7F]+", text.lower()) if len(t) > 1]


def chunk_free_retrieve(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
    meta_weight: float = 0.4,
    fact_weight: float = 0.3,
    content_weight: float = 0.3,
) -> List[Tuple[Chunk, float, Dict[str, Any]]]:
    """Retrieve using chunk-free meta-marker and atomic fact matching.

    Instead of matching against full chunk content, matches against
    lightweight meta-markers and atomic facts for faster, more precise retrieval.

    Args:
        query: Search query.
        chunks: Document chunks.
        top_k: Number of results.
        meta_weight: Weight for meta-marker matching.
        fact_weight: Weight for atomic fact matching.
        content_weight: Weight for direct content matching.

    Returns:
        List of (chunk, score, metadata) tuples.
    """
    if not chunks:
        return []

    # Extract meta-markers and facts
    meta_map = extract_meta_markers_from_chunks(chunks)
    facts_map = extract_atomic_facts_from_chunks(chunks)

    q_tokens = set(_tokenize(query))
    q_lower = query.lower()

    scored = []
    for chunk in chunks:
        # Score 1: Meta-marker matching
        meta_score = 0.0
        markers = meta_map.get(chunk.id, [])
        for marker in markers:
            key_tokens = set(_tokenize(marker.key))
            value_tokens = set(_tokenize(marker.value))
            key_overlap = len(q_tokens & key_tokens) / max(len(q_tokens), 1)
            value_overlap = len(q_tokens & value_tokens) / max(len(q_tokens), 1)
            # Key matching is more important
            marker_score = 0.7 * key_overlap + 0.3 * value_overlap
            meta_score = max(meta_score, marker_score * marker.confidence)

        # Score 2: Atomic fact matching
        fact_score = 0.0
        facts = facts_map.get(chunk.id, [])
        for fact in facts:
            fact_text = f"{fact.subject} {fact.predicate} {fact.obj}".lower()
            fact_tokens = set(_tokenize(fact_text))
            overlap = len(q_tokens & fact_tokens) / max(len(q_tokens), 1)
            # Check if subject matches query intent
            subject_match = any(
                st in q_lower for st in _tokenize(fact.subject)
            )
            if subject_match:
                overlap = min(overlap * 1.5, 1.0)
            fact_score = max(fact_score, overlap)

        # Score 3: Direct content matching (lighter weight)
        c_tokens = set(_tokenize(chunk.content))
        content_overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)

        # Combined score
        combined = (
            meta_weight * meta_score +
            fact_weight * fact_score +
            content_weight * content_overlap
        )

        metadata = {
            "meta_markers": len(markers),
            "atomic_facts": len(facts),
            "meta_score": round(meta_score, 4),
            "fact_score": round(fact_score, 4),
            "content_score": round(content_overlap, 4),
        }
        scored.append((chunk, combined, metadata))

    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def chunk_free_retrieve_simple(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Simplified chunk-free retrieval returning (chunk, score) tuples.

    Args:
        query: Search query.
        chunks: Document chunks.
        top_k: Number of results.

    Returns:
        List of (chunk, score) tuples.
    """
    results = chunk_free_retrieve(query, chunks, top_k)
    return [(chunk, score) for chunk, score, _ in results]


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def chunk_free_pipeline(
    query: str,
    chunks: List[Chunk],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Full chunk-free RAG pipeline.

    Extracts meta-markers and atomic facts, performs lightweight retrieval,
    and returns enriched results.

    Args:
        query: Search query.
        chunks: Document chunks.
        top_k: Number of results.

    Returns:
        Dict with results, extraction stats, and metadata.
    """
    # Extract all meta information
    meta_map = extract_meta_markers_from_chunks(chunks)
    facts_map = extract_atomic_facts_from_chunks(chunks)

    total_markers = sum(len(m) for m in meta_map.values())
    total_facts = sum(len(f) for f in facts_map.values())

    # Retrieve
    results = chunk_free_retrieve(query, chunks, top_k)

    return {
        "query": query,
        "results": [
            {
                "content": c.content[:300],
                "score": round(s, 4),
                "source": c.source,
                "metadata": m,
            }
            for c, s, m in results
        ],
        "extraction_stats": {
            "total_chunks": len(chunks),
            "chunks_with_markers": len(meta_map),
            "total_meta_markers": total_markers,
            "chunks_with_facts": len(facts_map),
            "total_atomic_facts": total_facts,
        },
    }
