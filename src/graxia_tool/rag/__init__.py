"""Enterprise Agent OS — RAG (Retrieval-Augmented Generation).

Provides a complete RAG pipeline with:
- Document parsing (PDF, DOCX, PPTX, XLSX, CSV, TXT, MD)
- Adaptive chunking with context enrichment
- Hybrid search (keyword + semantic via TF-IDF)
- Reranking (cross-encoder approximation, keyword overlap, LLM-based)
- Multimodal support (text, tables, images)
- Hypothetical questions for better retrieval
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from .ingestion import Document, load_document, load_directory
from .chunker import Chunker, Chunk
from .retriever import HybridRetriever, RetrievalResult, BM25, tokenize
from .rag_os import RAGOS, RAGResult
from .document_parser import parse_document, ParsedDocument
from .multimodal import (
    MultimodalContent,
    MultimodalIndexer,
    Modality,
    TableExtractor,
    ImageExtractor,
    ExtractedImage,
    ExtractedTable,
)
from .techniques import get_registry, register_technique, TechniqueRegistry
from .techniques.hybrid_search import hybrid_search, TFIDFIndex, reciprocal_rank_fusion
from .techniques.reranking import (
    keyword_rerank,
    semantic_rerank,
    cross_encoder_rerank,
    keyword_overlap_score,
)
from .techniques.chunk_optimization import (
    add_contextual_headers,
    enrich_with_context_window,
    split_by_semantic_boundaries,
    proposition_chunk,
)
from .techniques.hypothetical_questions import (
    generate_questions,
    index_with_questions,
    retrieve_with_questions,
)


class RAGEngine:
    """Main RAG engine — high-level entry point for all RAG operations.

    Supports:
    - Ingesting documents from files and directories
    - Indexing with adaptive chunking and optional embeddings
    - Querying with hybrid search (keyword + semantic)
    - Reranking results
    - Generating hypothetical questions for better retrieval
    - Extracting and indexing tables and images

    Usage:
        engine = RAGEngine()
        engine.ingest_file("report.pdf")
        engine.ingest_directory("./docs")
        results = engine.query("What is the revenue forecast?")
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoder_func=None,
        use_headers: bool = True,
        use_context_window: bool = False,
        window_size: int = 1,
        use_hypothetical_questions: bool = True,
    ):
        """Initialize the RAG engine.

        Args:
            chunk_size: Maximum characters per chunk.
            chunk_overlap: Overlap between consecutive chunks.
            encoder_func: Optional function that takes list of texts and returns embeddings.
            use_headers: Add contextual headers to chunks.
            use_context_window: Enrich chunks with surrounding context.
            window_size: Number of neighboring chunks for context window.
            use_hypothetical_questions: Generate questions for better retrieval.
        """
        self.chunker = Chunker(chunk_size, chunk_overlap)
        self.retriever = HybridRetriever()
        self.encoder_func = encoder_func
        self.use_headers = use_headers
        self.use_context_window = use_context_window
        self.window_size = window_size
        self.use_hypothetical_questions = use_hypothetical_questions
        self._all_chunks: List[Chunk] = []
        self._multimodal_indexer = MultimodalIndexer()
        self._question_index: Dict[str, List[str]] = {}
        self._embeddings: List[List[float]] = []

    def ingest_file(self, path: str) -> int:
        """Ingest a single file into the RAG index.

        Supports PDF, DOCX, PPTX, XLSX, CSV, TXT, MD, and code files.

        Args:
            path: Path to the file to ingest.

        Returns:
            Number of chunks added.
        """
        from pathlib import Path
        file_path = Path(path)
        if not file_path.exists():
            return 0

        # Parse the document
        parsed = parse_document(file_path)

        # Create Document from parsed content
        doc = Document(
            id=str(file_path),
            content=parsed.content,
            source=str(file_path),
            doc_type=parsed.doc_type,
            title=file_path.stem,
            extra=parsed.metadata,
        )

        # Index tables
        for table_data in parsed.tables:
            table = ExtractedTable(
                id=table_data.get("id", f"table_{file_path.name}"),
                headers=table_data.get("headers", []),
                rows=table_data.get("rows", []),
                caption=table_data.get("caption", ""),
                source=str(file_path),
            )
            self._multimodal_indexer.add_table(table)

        return self.ingest_document(doc)

    def ingest_document(self, doc: Document) -> int:
        """Ingest a Document object into the RAG index.

        Args:
            doc: Document to ingest.

        Returns:
            Number of chunks added.
        """
        chunks = self.chunker.chunk(doc)

        # Apply chunk optimization techniques
        if self.use_headers:
            chunks = add_contextual_headers(chunks, doc.title)

        # Generate hypothetical questions
        if self.use_hypothetical_questions:
            questions = index_with_questions(chunks, num_questions=2)
            self._question_index.update(questions)

        # Encode if encoder available
        embeddings = None
        if self.encoder_func and chunks:
            try:
                texts = [c.content for c in chunks]
                embeddings = self.encoder_func(texts)
                self._embeddings.extend(embeddings)
            except Exception:
                embeddings = None

        # Index in retriever
        self.retriever.index(chunks, embeddings)
        self._all_chunks.extend(chunks)

        return len(chunks)

    def ingest_directory(
        self,
        dir_path: str,
        recursive: bool = True,
        extensions: Optional[List[str]] = None,
    ) -> int:
        """Ingest all supported files in a directory.

        Args:
            dir_path: Path to the directory.
            recursive: Whether to recurse into subdirectories.
            extensions: Optional list of file extensions to include.

        Returns:
            Total chunks added.
        """
        from pathlib import Path
        path = Path(dir_path)
        if not path.exists():
            return 0

        default_ext = [
            ".pdf", ".docx", ".pptx", ".xlsx", ".csv",
            ".md", ".txt", ".py", ".js", ".ts", ".json",
        ]
        exts = extensions or default_ext

        count = 0
        files = path.rglob("*") if recursive else path.iterdir()
        for f in files:
            if f.is_file() and f.suffix.lower() in exts:
                count += self.ingest_file(str(f))

        return count

    def query(
        self,
        query: str,
        top_k: int = 5,
        rerank: bool = True,
        use_questions: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Query the RAG system.

        Args:
            query: Search query string.
            top_k: Number of results to return.
            rerank: Whether to apply reranking.
            use_questions: Whether to use hypothetical questions (overrides init setting).

        Returns:
            Dict with 'results', 'context', 'citations', 'estimated_tokens'.
        """
        from .techniques.hybrid_search import hybrid_search as _hybrid_search

        # Hybrid search
        use_q = use_questions if use_questions is not None else self.use_hypothetical_questions

        if use_q and self._question_index:
            # Use question-enhanced retrieval
            results = retrieve_with_questions(
                query, self._all_chunks, self._question_index, top_k=top_k * 2
            )
        else:
            # Standard hybrid search
            results = _hybrid_search(
                query,
                self._all_chunks,
                embeddings=self._embeddings if self._embeddings else None,
                top_k=top_k * 2,
                alpha=0.5,
            )

        # Rerank
        if rerank and results:
            results = cross_encoder_rerank(query, results, top_k=top_k)

        # Build output
        context_parts = []
        citations = []
        for chunk, score in results[:top_k]:
            context_parts.append(chunk.content)
            citation = f"{chunk.source}#{chunk.index}"
            if chunk.title:
                citation = f"{chunk.title} — {citation}"
            citations.append(citation)

        context = "\n\n---\n\n".join(context_parts)
        est_tokens = len(context) // 4

        return {
            "query": query,
            "results": [
                {
                    "content": chunk.content,
                    "score": round(score, 4),
                    "source": chunk.source,
                    "citation": f"{chunk.title or 'Document'} — {chunk.source}#{chunk.index}",
                    "chunk_id": chunk.id,
                }
                for chunk, score in results[:top_k]
            ],
            "context": context,
            "citations": citations,
            "estimated_tokens": est_tokens,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get RAG engine statistics.

        Returns:
            Dict with index stats including multimodal content counts.
        """
        stats = {
            "total_chunks": len(self._all_chunks),
            "indexed_chunks": len(self.retriever.chunks),
            "has_embeddings": len(self._embeddings) > 0,
            "questions_indexed": len(self._question_index),
        }
        stats.update(self._multimodal_indexer.get_stats())
        return stats

    def get_techniques(self) -> List[str]:
        """List available RAG techniques.

        Returns:
            List of registered technique names.
        """
        return get_registry().list_all()


# Register built-in techniques
register_technique("hybrid_search", hybrid_search)
register_technique("cross_encoder_rerank", cross_encoder_rerank)
register_technique("keyword_rerank", keyword_rerank)
register_technique("contextual_headers", add_contextual_headers)
register_technique("context_window", enrich_with_context_window)
register_technique("hypothetical_questions", generate_questions)


__all__ = [
    # Core classes
    "RAGEngine",
    "RAGOS",
    "RAGResult",
    # Document handling
    "Document",
    "ParsedDocument",
    "load_document",
    "load_directory",
    "parse_document",
    # Chunking
    "Chunker",
    "Chunk",
    # Retrieval
    "HybridRetriever",
    "RetrievalResult",
    "BM25",
    "tokenize",
    # Techniques
    "hybrid_search",
    "cross_encoder_rerank",
    "keyword_rerank",
    "add_contextual_headers",
    "enrich_with_context_window",
    "split_by_semantic_boundaries",
    "proposition_chunk",
    "generate_questions",
    "index_with_questions",
    "retrieve_with_questions",
    # Multimodal
    "MultimodalContent",
    "MultimodalIndexer",
    "Modality",
    "TableExtractor",
    "ImageExtractor",
    "ExtractedImage",
    "ExtractedTable",
    # Registry
    "get_registry",
    "register_technique",
    "TechniqueRegistry",
]
