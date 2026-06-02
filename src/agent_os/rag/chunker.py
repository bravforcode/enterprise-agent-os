"""Enterprise Agent OS — Document Chunking.

Strategies:
- Fixed: split by character/token count
- Sentence: split by sentence boundary
- Semantic: split by paragraph/section
- Adaptive: choose strategy based on doc type
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from .ingestion import Document
from ..core.logging import get_logger

logger = get_logger("chunker")


@dataclass
class Chunk:
    """A chunk of a document."""
    id: str
    doc_id: str
    content: str
    index: int
    start_char: int
    end_char: int
    doc_type: str
    source: str
    title: Optional[str] = None
    extra: Optional[dict] = None


class Chunker:
    """
    Chunks documents into smaller pieces for embedding.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        min_chunk_size: int = 50,
    ):
        self.chunk_size = chunk_size  # in chars
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    def chunk(self, doc: Document) -> list[Chunk]:
        """Chunk a document using adaptive strategy."""
        if doc.doc_type == "code":
            return self._chunk_code(doc)
        elif doc.doc_type in ("markdown", "html"):
            return self._chunk_semantic(doc)
        else:
            return self._chunk_fixed(doc)

    def _chunk_fixed(self, doc: Document) -> list[Chunk]:
        """Fixed-size chunking by character count."""
        chunks = []
        text = doc.content
        start = 0
        idx = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]
            if len(chunk_text) >= self.min_chunk_size:
                chunks.append(Chunk(
                    id=f"{doc.id}#{idx}",
                    doc_id=doc.id,
                    content=chunk_text.strip(),
                    index=idx,
                    start_char=start,
                    end_char=end,
                    doc_type=doc.doc_type,
                    source=doc.source,
                    title=doc.title,
                    extra=doc.extra,
                ))
                idx += 1
            # Advance: ensure forward progress
            if end >= len(text):
                break
            start = end - self.chunk_overlap
            # Safety: ensure progress
            if start < idx * self.chunk_size // 2:
                start = idx * self.chunk_size // 2
        return chunks

    def _chunk_semantic(self, doc: Document) -> list[Chunk]:
        """Chunk by paragraph/section for structured docs."""
        # Split by double newline (paragraphs)
        paragraphs = re.split(r"\n\s*\n", doc.content)
        chunks = []
        current_chunk = ""
        current_start = 0
        idx = 0
        char_pos = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                char_pos += 1
                continue
            # If adding this paragraph exceeds chunk_size, save current
            if len(current_chunk) + len(para) > self.chunk_size and current_chunk:
                chunks.append(Chunk(
                    id=f"{doc.id}#{idx}",
                    doc_id=doc.id,
                    content=current_chunk.strip(),
                    index=idx,
                    start_char=current_start,
                    end_char=char_pos,
                    doc_type=doc.doc_type,
                    source=doc.source,
                    title=doc.title,
                    extra=doc.extra,
                ))
                idx += 1
                # Start new chunk with overlap
                overlap = current_chunk[-self.chunk_overlap:] if len(current_chunk) > self.chunk_overlap else ""
                current_chunk = overlap + "\n\n" + para
                current_start = char_pos - len(overlap)
            else:
                if current_chunk:
                    current_chunk += "\n\n" + para
                else:
                    current_chunk = para
                    current_start = char_pos
            char_pos += len(para) + 2  # +2 for \n\n

        # Don't forget last chunk
        if current_chunk.strip():
            chunks.append(Chunk(
                id=f"{doc.id}#{idx}",
                doc_id=doc.id,
                content=current_chunk.strip(),
                index=idx,
                start_char=current_start,
                end_char=char_pos,
                doc_type=doc.doc_type,
                source=doc.source,
                title=doc.title,
                extra=doc.extra,
            ))
        return chunks

    def _chunk_code(self, doc: Document) -> list[Chunk]:
        """Chunk by function/class for code files."""
        # Split by lines, group into blocks
        lines = doc.content.split("\n")
        chunks = []
        current_block = []
        idx = 0
        char_pos = 0
        in_function = False
        brace_depth = 0

        for line in lines:
            current_block.append(line)
            char_pos += len(line) + 1
            brace_depth += line.count("{") - line.count("}")
            # Function/class boundary
            if (re.match(r"^(def |class |function |async |pub |fn )", line)
                or (in_function and brace_depth == 0 and len(current_block) > 1)):
                # Save previous block if any
                if len("\n".join(current_block)) >= self.min_chunk_size:
                    chunks.append(Chunk(
                        id=f"{doc.id}#{idx}",
                        doc_id=doc.id,
                        content="\n".join(current_block).strip(),
                        index=idx,
                        start_char=char_pos - sum(len(l) + 1 for l in current_block),
                        end_char=char_pos,
                        doc_type=doc.doc_type,
                        source=doc.source,
                        title=doc.title,
                        extra=doc.extra,
                    ))
                    idx += 1
                current_block = []
                in_function = brace_depth > 0
            if brace_depth > 0:
                in_function = True

        # Last block
        if current_block and len("\n".join(current_block)) >= self.min_chunk_size:
            chunks.append(Chunk(
                id=f"{doc.id}#{idx}",
                doc_id=doc.id,
                content="\n".join(current_block).strip(),
                index=idx,
                start_char=char_pos - sum(len(l) + 1 for l in current_block),
                end_char=char_pos,
                doc_type=doc.doc_type,
                source=doc.source,
                title=doc.title,
                extra=doc.extra,
            ))
        return chunks
