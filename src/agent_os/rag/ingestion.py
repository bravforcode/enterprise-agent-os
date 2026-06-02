"""Enterprise Agent OS — Document Ingestion.

Loads documents from various formats: PDF, MD, HTML, TXT, JSON, code.
"""
from __future__ import annotations
import re
from pathlib import Path
from dataclasses import dataclass
from typing import Iterator, Optional
from ..core.logging import get_logger

logger = get_logger("ingestion")


@dataclass
class Document:
    """A loaded document."""
    id: str
    content: str
    source: str
    doc_type: str  # "pdf", "markdown", "html", "text", "code", "json"
    title: Optional[str] = None
    extra: Optional[dict] = None


def load_markdown(path: Path) -> Document:
    """Load a markdown file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Extract title from first heading
    title_m = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    title = title_m.group(1) if title_m else path.stem
    return Document(
        id=str(path),
        content=text,
        source=str(path),
        doc_type="markdown",
        title=title,
    )


def load_text(path: Path) -> Document:
    """Load a plain text file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return Document(
        id=str(path),
        content=text,
        source=str(path),
        doc_type="text",
        title=path.stem,
    )


def load_html(path: Path) -> Document:
    """Load an HTML file (strip tags)."""
    try:
        from bs4 import BeautifulSoup
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        # Get text
        text = soup.get_text(separator="\n", strip=True)
        # Get title
        title_tag = soup.find("title")
        title = title_tag.string if title_tag else path.stem
    except ImportError:
        text = path.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r"<[^>]+>", "", text)
        title = path.stem
    return Document(
        id=str(path),
        content=text,
        source=str(path),
        doc_type="html",
        title=title,
    )


def load_pdf(path: Path) -> Document:
    """Load a PDF file."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() for page in reader.pages)
        title = path.stem
    except ImportError:
        text = f"[PDF file: {path}]"
        title = path.stem
    return Document(
        id=str(path),
        content=text,
        source=str(path),
        doc_type="pdf",
        title=title,
    )


def load_code(path: Path) -> Document:
    """Load a code file (with syntax-aware metadata)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    # Detect language from extension
    ext = path.suffix.lstrip(".")
    lang_map = {
        "py": "python", "js": "javascript", "ts": "typescript",
        "rs": "rust", "go": "go", "java": "java", "rb": "ruby",
        "cpp": "cpp", "c": "c", "cs": "csharp", "php": "php",
    }
    language = lang_map.get(ext, ext)
    return Document(
        id=str(path),
        content=text,
        source=str(path),
        doc_type="code",
        title=path.name,
        extra={"language": language, "extension": ext},
    )


def load_json(path: Path) -> Document:
    """Load a JSON file."""
    import json
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return Document(
        id=str(path),
        content=json.dumps(data, indent=2, ensure_ascii=False),
        source=str(path),
        doc_type="json",
        title=path.stem,
    )


def load_document(path: Path) -> Optional[Document]:
    """Auto-detect format and load."""
    suffix = path.suffix.lower()
    if suffix in (".md", ".markdown"):
        return load_markdown(path)
    elif suffix == ".html" or suffix == ".htm":
        return load_html(path)
    elif suffix == ".pdf":
        return load_pdf(path)
    elif suffix in (".py", ".js", ".ts", ".rs", ".go", ".java", ".rb", ".cpp", ".c", ".cs", ".php", ".sh"):
        return load_code(path)
    elif suffix == ".json":
        return load_json(path)
    elif suffix in (".txt", ".log", ""):
        return load_text(path)
    else:
        # Try as text
        return load_text(path)


def load_directory(
    dir_path: Path,
    recursive: bool = True,
    extensions: Optional[list[str]] = None,
) -> Iterator[Document]:
    """Load all documents in a directory."""
    extensions = extensions or [".md", ".txt", ".py", ".json", ".html"]
    if not dir_path.exists():
        return
    if recursive:
        files = dir_path.rglob("*")
    else:
        files = dir_path.iterdir()

    for f in files:
        if not f.is_file():
            continue
        if extensions and f.suffix.lower() not in extensions:
            continue
        try:
            doc = load_document(f)
            if doc:
                yield doc
        except Exception as e:
            logger.warning("doc_load_error", file=str(f), error=str(e))
