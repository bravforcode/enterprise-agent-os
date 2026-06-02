"""Enterprise Agent OS — Multimodal RAG Processing.

Handles extraction and indexing of images and tables from documents,
enabling retrieval across text, visual, and tabular content.

Based on RAG-Anything's multimodal processing patterns.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class Modality(str, Enum):
    """Content modality types."""
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    CODE = "code"
    EQUATION = "equation"


@dataclass
class MultimodalContent:
    """A piece of content with its modality."""
    id: str
    content: str
    modality: Modality
    source: str
    page: Optional[int] = None
    caption: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractedImage:
    """An extracted image with context."""
    id: str
    path: Optional[str] = None
    base64: Optional[str] = None
    description: str = ""
    context_before: str = ""
    context_after: str = ""
    page: Optional[int] = None
    source: str = ""


@dataclass
class ExtractedTable:
    """An extracted table with structured data."""
    id: str
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: str = ""
    source: str = ""
    page: Optional[int] = None

    def to_text(self) -> str:
        """Convert table to readable text format."""
        if not self.headers and not self.rows:
            return self.caption or "[Empty table]"

        lines = []
        if self.caption:
            lines.append(f"Table: {self.caption}")
        if self.headers:
            lines.append(" | ".join(self.headers))
            lines.append("-" * (len(" | ".join(self.headers))))
        for row in self.rows:
            lines.append(" | ".join(str(cell) for cell in row))
        return "\n".join(lines)

    def to_markdown(self) -> str:
        """Convert table to Markdown format."""
        if not self.headers and not self.rows:
            return self.caption or "*Empty table*"

        lines = []
        if self.caption:
            lines.append(f"**{self.caption}**\n")
        if self.headers:
            lines.append("| " + " | ".join(self.headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(self.headers)) + " |")
        for row in self.rows:
            lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
        return "\n".join(lines)


class TableExtractor:
    """Extract tables from text content using pattern matching."""

    @staticmethod
    def extract_from_text(text: str, source: str = "", page: Optional[int] = None) -> List[ExtractedTable]:
        """Extract tables from text using pipe-delimited patterns.

        Recognizes:
        - Pipe-delimited tables (| col1 | col2 |)
        - Tab-delimited tables
        - Indented list-style tables

        Args:
            text: Text content to scan for tables.
            source: Source document identifier.
            page: Page number if applicable.

        Returns:
            List of extracted tables.
        """
        tables = []
        lines = text.split("\n")

        # Pattern 1: Pipe-delimited tables
        pipe_table = TableExtractor._extract_pipe_table(lines, source, page)
        if pipe_table:
            tables.extend(pipe_table)

        # Pattern 2: Tab-delimited tables
        tab_table = TableExtractor._extract_tab_table(lines, source, page)
        if tab_table:
            tables.extend(tab_table)

        return tables

    @staticmethod
    def _extract_pipe_table(
        lines: List[str], source: str, page: Optional[int]
    ) -> List[ExtractedTable]:
        """Extract pipe-delimited tables."""
        tables = []
        current_table_lines = []
        in_table = False
        table_idx = 0

        for line in lines:
            stripped = line.strip()
            if re.match(r"^\|[\s\-|]+\|$", stripped):
                # Separator line (| --- | --- |)
                in_table = True
                current_table_lines.append(stripped)
            elif stripped.startswith("|") and stripped.endswith("|"):
                if not in_table and current_table_lines:
                    # First data line
                    in_table = True
                if in_table:
                    current_table_lines.append(stripped)
            else:
                if in_table and current_table_lines:
                    # End of table
                    table = TableExtractor._parse_pipe_lines(
                        current_table_lines, source, page, table_idx
                    )
                    if table:
                        tables.append(table)
                        table_idx += 1
                    current_table_lines = []
                    in_table = False

        # Handle table at end of text
        if in_table and current_table_lines:
            table = TableExtractor._parse_pipe_lines(
                current_table_lines, source, page, table_idx
            )
            if table:
                tables.append(table)

        return tables

    @staticmethod
    def _parse_pipe_lines(
        lines: List[str], source: str, page: Optional[int], idx: int
    ) -> Optional[ExtractedTable]:
        """Parse pipe-delimited table lines into an ExtractedTable."""
        if len(lines) < 2:
            return None

        rows = []
        headers = []

        for line in lines:
            stripped = line.strip()
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                continue  # Skip separator
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not headers:
                headers = cells
            else:
                rows.append(cells)

        if not headers:
            return None

        return ExtractedTable(
            id=f"table_{source}_{page or 0}_{idx}",
            headers=headers,
            rows=rows,
            source=source,
            page=page,
        )

    @staticmethod
    def _extract_tab_table(
        lines: List[str], source: str, page: Optional[int]
    ) -> List[ExtractedTable]:
        """Extract tab-delimited tables."""
        tables = []
        current_lines = []
        in_table = False
        table_idx = 0

        for line in lines:
            if "\t" in line and len(line.split("\t")) >= 2:
                if not in_table:
                    in_table = True
                    current_lines = []
                current_lines.append(line)
            else:
                if in_table and current_lines:
                    table = TableExtractor._parse_tab_lines(
                        current_lines, source, page, table_idx
                    )
                    if table:
                        tables.append(table)
                        table_idx += 1
                    current_lines = []
                    in_table = False

        if in_table and current_lines:
            table = TableExtractor._parse_tab_lines(
                current_lines, source, page, table_idx
            )
            if table:
                tables.append(table)

        return tables

    @staticmethod
    def _parse_tab_lines(
        lines: List[str], source: str, page: Optional[int], idx: int
    ) -> Optional[ExtractedTable]:
        """Parse tab-delimited lines into an ExtractedTable."""
        if len(lines) < 2:
            return None

        rows = []
        headers = []

        for line in lines:
            cells = [c.strip() for c in line.split("\t")]
            if not headers:
                headers = cells
            else:
                rows.append(cells)

        return ExtractedTable(
            id=f"table_{source}_{page or 0}_{idx}",
            headers=headers,
            rows=rows,
            source=source,
            page=page,
        )


class ImageExtractor:
    """Extract and describe images from document content."""

    @staticmethod
    def extract_image_references(text: str) -> List[Dict[str, str]]:
        """Extract image references from text (markdown, HTML, or plain text).

        Args:
            text: Document text content.

        Returns:
            List of image reference dicts with 'type', 'path', 'alt'.
        """
        refs = []

        # Markdown: ![alt](path)
        for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
            refs.append({
                "type": "markdown",
                "path": match.group(2),
                "alt": match.group(1),
                "position": match.start(),
            })

        # HTML: <img src="..." alt="...">
        for match in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', text):
            alt_match = re.search(r'alt=["\']([^"\']*)["\']', match.group(0))
            refs.append({
                "type": "html",
                "path": match.group(1),
                "alt": alt_match.group(1) if alt_match else "",
                "position": match.start(),
            })

        return refs

    @staticmethod
    def generate_image_description(
        image_ref: Dict[str, str],
        surrounding_text: str = "",
    ) -> str:
        """Generate a text description for an image based on context.

        Uses surrounding text and alt text to create a searchable description.

        Args:
            image_ref: Image reference dict from extract_image_references.
            surrounding_text: Text around the image for context.

        Returns:
            Text description of the image.
        """
        parts = []
        alt = image_ref.get("alt", "")
        if alt:
            parts.append(f"Image: {alt}")

        path = image_ref.get("path", "")
        if path:
            # Extract filename for context
            filename = path.split("/")[-1].split("\\")[-1]
            parts.append(f"File: {filename}")

        if surrounding_text:
            # Take nearby text as context
            context = surrounding_text[:200].strip()
            if context:
                parts.append(f"Context: {context}")

        return " | ".join(parts) if parts else "[Image]"


class MultimodalIndexer:
    """Index multimodal content for unified retrieval."""

    def __init__(self):
        self.text_chunks: List[MultimodalContent] = []
        self.images: List[ExtractedImage] = []
        self.tables: List[ExtractedTable] = []

    def add_text(self, content: MultimodalContent) -> None:
        """Add text content to the index."""
        self.text_chunks.append(content)

    def add_image(self, image: ExtractedImage) -> None:
        """Add an image to the index."""
        self.images.append(image)

    def add_table(self, table: ExtractedTable) -> None:
        """Add a table to the index."""
        self.tables.append(table)

    def get_all_content(self) -> List[MultimodalContent]:
        """Get all indexed content as MultimodalContent list."""
        all_content = list(self.text_chunks)

        # Convert images to searchable text
        for img in self.images:
            desc = img.description or f"[Image from {img.source}]"
            all_content.append(MultimodalContent(
                id=img.id,
                content=desc,
                modality=Modality.IMAGE,
                source=img.source,
                page=img.page,
                caption=img.description,
            ))

        # Convert tables to searchable text
        for table in self.tables:
            all_content.append(MultimodalContent(
                id=table.id,
                content=table.to_text(),
                modality=Modality.TABLE,
                source=table.source,
                page=table.page,
                caption=table.caption,
            ))

        return all_content

    def search_by_modality(
        self, modality: Modality
    ) -> List[MultimodalContent]:
        """Filter content by modality type."""
        return [c for c in self.get_all_content() if c.modality == modality]

    def get_stats(self) -> Dict[str, int]:
        """Get indexing statistics."""
        return {
            "text_chunks": len(self.text_chunks),
            "images": len(self.images),
            "tables": len(self.tables),
            "total": len(self.text_chunks) + len(self.images) + len(self.tables),
        }
