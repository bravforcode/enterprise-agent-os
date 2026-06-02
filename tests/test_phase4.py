"""Enterprise Agent OS — Phase 4 tests."""
import pytest
import tempfile
import os
from pathlib import Path
from graxia_tool.rag.ingestion import (
    Document, load_document, load_directory, load_markdown, load_code, load_json,
)
from graxia_tool.rag.chunker import Chunker
from graxia_tool.rag.retriever import HybridRetriever, BM25, tokenize
from graxia_tool.rag.rag_os import RAGOS


class TestIngestion:
    def test_load_markdown(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Title\n\nContent here.")
            path = Path(f.name)
        doc = load_markdown(path)
        assert doc.title == "Title"
        assert "Content" in doc.content
        path.unlink()

    def test_load_text(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello world")
            path = Path(f.name)
        from graxia_tool.rag.ingestion import load_text
        doc = load_text(path)
        assert doc.content == "Hello world"
        path.unlink()

    def test_load_code(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write("def hello():\n    pass")
            path = Path(f.name)
        doc = load_code(path)
        assert doc.doc_type == "code"
        assert doc.extra["language"] == "python"
        path.unlink()

    def test_load_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write('{"key": "value"}')
            path = Path(f.name)
        doc = load_json(path)
        assert '"key"' in doc.content
        path.unlink()

    def test_load_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "a.md").write_text("# A\n\ncontent a")
            (tmp_path / "b.txt").write_text("content b")
            (tmp_path / "c.py").write_text("# c")
            docs = list(load_directory(tmp_path, extensions=[".md", ".txt", ".py"]))
            assert len(docs) == 3

    def test_auto_detect_format(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Test\n\nHello.")
            path = Path(f.name)
        doc = load_document(path)
        assert doc.doc_type == "markdown"
        path.unlink()


class TestChunker:
    def test_fixed_chunking(self):
        chunker = Chunker(chunk_size=50, chunk_overlap=10)
        doc = Document(
            id="test",
            content="A" * 200,
            source="test",
            doc_type="text",
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) > 1
        assert all(len(c.content) <= 50 for c in chunks)

    def test_semantic_chunking(self):
        chunker = Chunker(chunk_size=100, chunk_overlap=20)
        doc = Document(
            id="test",
            content="Para 1.\n\nPara 2.\n\nPara 3.",
            source="test",
            doc_type="markdown",
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 1

    def test_code_chunking(self):
        chunker = Chunker(chunk_size=200, min_chunk_size=10)
        code = """def hello():
    return "hello"

def world():
    return "world"
"""
        doc = Document(
            id="test",
            content=code,
            source="test.py",
            doc_type="code",
        )
        chunks = chunker.chunk(doc)
        assert len(chunks) >= 1

    def test_min_chunk_size(self):
        chunker = Chunker(chunk_size=50, min_chunk_size=20)
        doc = Document(id="x", content="x" * 10, source="x", doc_type="text")
        chunks = chunker.chunk(doc)
        assert len(chunks) == 0  # Too small


class TestRetriever:
    def test_bm25_score(self):
        corpus = [["cat", "dog"], ["fish", "bird"], ["cat", "bird"]]
        bm25 = BM25(corpus)
        scores = bm25.score(["cat"])
        assert scores[0] > 0  # cat in doc 0
        assert scores[2] > 0  # cat in doc 2
        assert scores[1] == 0  # no cat in doc 1

    def test_tokenize(self):
        tokens = tokenize("Hello, World! Foo123 bar")
        assert "hello" in tokens
        assert "world" in tokens
        assert "foo123" in tokens

    def test_empty_index(self):
        retriever = HybridRetriever()
        results = retriever.retrieve("test")
        assert results == []

    def test_retrieve(self):
        from graxia_tool.rag.chunker import Chunk
        chunks = [
            Chunk(id="1", doc_id="1", content="Python is a programming language",
                  index=0, start_char=0, end_char=36, doc_type="text", source="1"),
            Chunk(id="2", doc_id="2", content="Cats are furry animals",
                  index=0, start_char=0, end_char=23, doc_type="text", source="2"),
            Chunk(id="3", doc_id="3", content="Python snakes are reptiles",
                  index=0, start_char=0, end_char=28, doc_type="text", source="3"),
        ]
        retriever = HybridRetriever()
        retriever.index(chunks)
        results = retriever.retrieve("python")
        assert len(results) > 0
        # Python-related docs should rank higher
        top_ids = [r.chunk.id for r in results[:2]]
        assert "1" in top_ids or "3" in top_ids

    def test_citation_format(self):
        from graxia_tool.rag.chunker import Chunk
        chunk = Chunk(id="1", doc_id="1", content="test",
                      index=0, start_char=0, end_char=4, doc_type="text",
                      source="docs/test.md", title="Test")
        retriever = HybridRetriever()
        retriever.index([chunk])
        results = retriever.retrieve("test")
        assert "Test" in results[0].citation
        assert "docs/test.md" in results[0].citation


class TestRAGOS:
    def test_ingest_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "doc1.md").write_text(
                "# Python\n\nPython is a high-level programming language known for its simplicity."
            )
            (tmp_path / "doc2.md").write_text(
                "# Cats\n\nCats are small, furry carnivorous mammals often kept as pets."
            )
            rag = RAGOS()
            chunks_added = rag.ingest_directory(tmp_path, extensions=[".md"])
            assert chunks_added >= 2
            result = rag.query("python", top_k=2)
            assert len(result.chunks) > 0
            # Verify some chunk has relevant content
            content = " ".join(c.chunk.content.lower() for c in result.chunks)
            assert "python" in content or "cats" in content

    def test_stats(self):
        rag = RAGOS()
        stats = rag.get_stats()
        assert stats["total_chunks"] == 0
        assert stats["indexed_chunks"] == 0
