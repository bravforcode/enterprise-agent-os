"""Enterprise Agent OS — RAG OS (Retrieval-Augmented Generation).

Pipeline:
1. Ingest documents (PDF, MD, HTML, code, JSON)
2. Chunk (adaptive strategy)
3. Embed (ONNX MiniLM)
4. Index (BM25 + Qdrant)
5. Retrieve (hybrid BM25 + dense + rerank)
6. Generate (with citations)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from .ingestion import Document, load_document, load_directory
from .chunker import Chunker, Chunk
from .retriever import HybridRetriever, RetrievalResult
from ..core.logging import get_logger

logger = get_logger("rag_os")


@dataclass
class RAGResult:
    """Result of a RAG query."""
    query: str
    chunks: list[RetrievalResult]
    context: str  # concatenated chunks
    citations: list[str]
    estimated_tokens: int


class RAGOS:
    """
    RAG OS — the main entry point for RAG operations.
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoder_func=None,
    ):
        self.chunker = Chunker(chunk_size, chunk_overlap)
        self.retriever = HybridRetriever()
        self.encoder_func = encoder_func  # optional: func(texts) -> embeddings
        self._all_chunks: list[Chunk] = []

    def ingest_file(self, path: str) -> int:
        """Ingest a single file. Returns chunks added."""
        from pathlib import Path
        doc = load_document(Path(path))
        if not doc:
            return 0
        return self.ingest_document(doc)

    def ingest_document(self, doc: Document) -> int:
        """Ingest a Document. Returns chunks added."""
        chunks = self.chunker.chunk(doc)
        # Encode if encoder available
        if self.encoder_func and chunks:
            try:
                texts = [c.content for c in chunks]
                embeddings = self.encoder_func(texts)
                for c, e in zip(chunks, embeddings):
                    c.extra = c.extra or {}
                    c.extra["has_embedding"] = True
                self.retriever.index(chunks, embeddings)
            except Exception as e:
                logger.warning("encoding_failed", error=str(e))
                self.retriever.index(chunks)
        else:
            self.retriever.index(chunks)
        self._all_chunks.extend(chunks)
        logger.info("ingested", source=doc.source, chunks=len(chunks))
        return len(chunks)

    def ingest_directory(
        self,
        dir_path: str,
        recursive: bool = True,
        extensions: Optional[list[str]] = None,
    ) -> int:
        """Ingest all files in a directory. Returns total chunks added."""
        from pathlib import Path
        count = 0
        for doc in load_directory(Path(dir_path), recursive, extensions):
            count += self.ingest_document(doc)
        logger.info("ingested_dir", path=dir_path, chunks=count)
        return count

    def query(
        self,
        query: str,
        top_k: int = 5,
        rerank: bool = True,
        query_embedding: Optional[list[float]] = None,
    ) -> RAGResult:
        """
        Query the RAG system.

        Returns:
            RAGResult with chunks, context, citations
        """
        results = self.retriever.retrieve(
            query=query,
            top_k=top_k,
            query_embedding=query_embedding,
            rerank=rerank,
        )

        # Build context from top chunks
        context_parts = []
        citations = []
        for r in results:
            context_parts.append(r.chunk.content)
            citations.append(r.citation)
        context = "\n\n---\n\n".join(context_parts)
        est_tokens = len(context) // 4

        return RAGResult(
            query=query,
            chunks=results,
            context=context,
            citations=citations,
            estimated_tokens=est_tokens,
        )

    def get_stats(self) -> dict[str, int]:
        """Get RAG stats."""
        return {
            "total_chunks": len(self._all_chunks),
            "indexed_chunks": len(self.retriever.chunks),
            "has_embeddings": len(self.retriever.embeddings) > 0,
        }
