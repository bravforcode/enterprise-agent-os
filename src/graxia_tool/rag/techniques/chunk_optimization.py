"""Enterprise Agent OS — Chunk Optimization Techniques.

Provides advanced chunking strategies:
1. Contextual chunk headers - Add document titles/section headers to each chunk
2. Context window enrichment - Expand chunks with surrounding context
3. Semantic splitting - Split at natural paragraph/section boundaries
4. Proposition chunking - Break into atomic factual statements

Based on techniques from rag-techniques (contextual_chunk_headers,
context_enrichment_window, semantic_chunking, proposition_chunking).
"""
from __future__ import annotations
import re
from typing import List, Optional

from ..chunker import Chunk
from ..ingestion import Document


def add_contextual_headers(
    chunks: List[Chunk],
    doc_title: Optional[str] = None,
) -> List[Chunk]:
    """Add contextual headers to each chunk for better retrieval.

    Prepends the document title and chunk index to each chunk's content,
    which helps the retriever understand where each chunk comes from.

    Based on: contextual_chunk_headers technique.

    Args:
        chunks: List of chunks to enhance.
        doc_title: Optional document title to prepend.

    Returns:
        List of chunks with enhanced content including headers.
    """
    enhanced = []
    title = doc_title or chunks[0].title if chunks else "Document"

    for i, chunk in enumerate(chunks):
        header = f"[Source: {title} | Section {i + 1}/{len(chunks)}]\n"
        enhanced_content = header + chunk.content
        enhanced_chunk = Chunk(
            id=chunk.id,
            doc_id=chunk.doc_id,
            content=enhanced_content,
            index=chunk.index,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            doc_type=chunk.doc_type,
            source=chunk.source,
            title=chunk.title,
            extra={**(chunk.extra or {}), "has_header": True},
        )
        enhanced.append(enhanced_chunk)

    return enhanced


def enrich_with_context_window(
    chunks: List[Chunk],
    window_size: int = 1,
) -> List[Chunk]:
    """Enrich each chunk with surrounding context from neighboring chunks.

    Adds content from `window_size` chunks before and after each chunk,
    preserving context that may be split across chunk boundaries.

    Based on: context_enrichment_window_around_chunk technique.

    Args:
        chunks: List of ordered chunks.
        window_size: Number of neighboring chunks to include on each side.

    Returns:
        List of enriched chunks with context windows.
    """
    if not chunks or window_size <= 0:
        return chunks

    enriched = []
    for i, chunk in enumerate(chunks):
        # Collect context from neighbors
        context_before = ""
        context_after = ""

        for j in range(max(0, i - window_size), i):
            context_before += chunks[j].content + "\n\n"

        for j in range(i + 1, min(len(chunks), i + window_size + 1)):
            context_after += "\n\n" + chunks[j].content

        # Build enriched content
        enriched_content = ""
        if context_before.strip():
            enriched_content += "[Previous context]\n" + context_before.strip() + "\n\n"
        enriched_content += "[Current chunk]\n" + chunk.content
        if context_after.strip():
            enriched_content += "\n\n[Following context]\n" + context_after.strip()

        enriched_chunk = Chunk(
            id=chunk.id,
            doc_id=chunk.doc_id,
            content=enriched_content,
            index=chunk.index,
            start_char=chunk.start_char,
            end_char=chunk.end_char,
            doc_type=chunk.doc_type,
            source=chunk.source,
            title=chunk.title,
            extra={**(chunk.extra or {}), "enriched": True, "window_size": window_size},
        )
        enriched.append(enriched_chunk)

    return enriched


def split_by_semantic_boundaries(
    text: str,
    max_chunk_size: int = 500,
    min_chunk_size: int = 50,
) -> List[str]:
    """Split text at natural semantic boundaries (paragraphs, sections).

    Tries to split at double newlines (paragraphs), then at sentence
    boundaries if paragraphs are too large.

    Based on: semantic_chunking technique.

    Args:
        text: Full text to split.
        max_chunk_size: Maximum characters per chunk.
        min_chunk_size: Minimum characters to keep in a chunk.

    Returns:
        List of text chunks split at semantic boundaries.
    """
    if not text.strip():
        return []

    # Step 1: Split into paragraphs
    paragraphs = re.split(r"\n\s*\n", text)

    chunks = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding paragraph exceeds max, save current and start new
        if len(current) + len(para) > max_chunk_size and current:
            if len(current) >= min_chunk_size:
                chunks.append(current.strip())
            # Start new chunk; carry over last sentence as overlap
            sentences = re.split(r"(?<=[.!?])\s+", current)
            overlap = sentences[-1] if sentences and len(sentences[-1]) < min_chunk_size else ""
            current = overlap + "\n\n" + para if overlap else para
        else:
            current = current + "\n\n" + para if current else para

        # If single paragraph exceeds max, split by sentences
        while len(current) > max_chunk_size:
            sentences = re.split(r"(?<=[.!?])\s+", current)
            if len(sentences) <= 1:
                # Hard split as last resort
                if len(current) >= min_chunk_size:
                    chunks.append(current[:max_chunk_size].strip())
                current = current[max_chunk_size:]
            else:
                # Find a good split point
                half = len(sentences) // 2
                part1 = " ".join(sentences[:half])
                part2 = " ".join(sentences[half:])
                if len(part1) >= min_chunk_size:
                    chunks.append(part1.strip())
                current = part2

    if current.strip() and len(current.strip()) >= min_chunk_size:
        chunks.append(current.strip())

    return chunks


def proposition_chunk(
    chunk: Chunk,
    max_propositions: int = 10,
) -> List[Chunk]:
    """Break a chunk into atomic, self-contained propositions.

    Splits by sentence and groups related sentences into standalone
    propositions that can be retrieved independently.

    Based on: proposition_chunking technique.

    Args:
        chunk: The chunk to decompose.
        max_propositions: Maximum number of propositions to create.

    Returns:
        List of proposition-sized chunks.
    """
    # Split into sentences
    sentences = re.split(r"(?<=[.!?])\s+", chunk.content)
    sentences = [s.strip() for s in sentences if s.strip()]

    if len(sentences) <= 2:
        # Already small enough, return as-is
        return [chunk]

    propositions = []
    current_prop = ""
    prop_idx = 0

    for sent in sentences:
        if len(current_prop) + len(sent) > 200 and current_prop:
            # Save current proposition
            propositions.append(Chunk(
                id=f"{chunk.id}p{prop_idx}",
                doc_id=chunk.doc_id,
                content=current_prop.strip(),
                index=chunk.index,
                start_char=chunk.start_char,
                end_char=chunk.start_char + len(current_prop),
                doc_type=chunk.doc_type,
                source=chunk.source,
                title=chunk.title,
                extra={**(chunk.extra or {}), "proposition": True, "proposition_idx": prop_idx},
            ))
            prop_idx += 1
            if prop_idx >= max_propositions:
                break
            current_prop = sent
        else:
            current_prop = current_prop + " " + sent if current_prop else sent

    # Last proposition
    if current_prop.strip() and prop_idx < max_propositions:
        propositions.append(Chunk(
            id=f"{chunk.id}p{prop_idx}",
            doc_id=chunk.doc_id,
            content=current_prop.strip(),
            index=chunk.index,
            start_char=chunk.start_char,
            end_char=chunk.start_char + len(current_prop),
            doc_type=chunk.doc_type,
            source=chunk.source,
            title=chunk.title,
            extra={**(chunk.extra or {}), "proposition": True, "proposition_idx": prop_idx},
        ))

    return propositions if propositions else [chunk]
