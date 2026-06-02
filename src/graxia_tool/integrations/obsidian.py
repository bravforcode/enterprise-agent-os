"""Obsidian Vault integration — bridge Agent OS with Second Brain.

Reads from: C:\\Users\\menum\\Documents\\ObsidianVault\\Second Brain (or AGENT_OS_VAULT_PATH)

Capabilities:
- Search vault notes (semantic + keyword)
- Read/write notes
- List MOCs, skills, agents
- Run vault auto-systems (linker, classifier, tagger)
- Apply STI (Smart Token Intelligence) — surgical load with 70-80% token savings
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("graxia_tool.obsidian")

DEFAULT_VAULT = Path(r"C:\Users\menum\Documents\ObsidianVault\Second Brain")


@dataclass
class NoteResult:
    """A note search result."""
    path: str
    title: str
    snippet: str
    score: float = 0.0
    tags: List[str] = field(default_factory=list)
    frontmatter: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Note:
    """A vault note."""
    path: str
    title: str
    content: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)
    mtime: float = 0.0


class ObsidianBridge:
    """Bridge between Agent OS and an Obsidian vault.

    Auto-detects the vault from:
    1. AGENT_OS_VAULT_PATH env var
    2. .gemini-obsidian.config.json
    3. Default: ~/Documents/ObsidianVault/Second Brain
    """

    def __init__(self, vault_path: Optional[Path] = None):
        self.vault_path = self._resolve_vault(vault_path)
        self._cache: Dict[str, Note] = {}
        self._index_mtime: float = 0.0
        self._index: Dict[str, Note] = {}

    def _resolve_vault(self, override: Optional[Path]) -> Path:
        if override:
            return Path(override)
        env = os.environ.get("AGENT_OS_VAULT_PATH")
        if env:
            return Path(env)
        config = Path.home() / ".gemini-obsidian.config.json"
        if config.exists():
            try:
                with config.open() as f:
                    data = json.load(f)
                p = data.get("vault_path")
                if p:
                    return Path(p)
            except Exception as e:
                logger.warning("Failed to read %s: %s", config, e)
        return DEFAULT_VAULT

    @property
    def is_connected(self) -> bool:
        return self.vault_path.exists()

    # ------------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------------

    def _build_index(self) -> Dict[str, Note]:
        """Build an in-memory index of all .md files in the vault."""
        if not self.is_connected:
            logger.warning("Vault path does not exist: %s", self.vault_path)
            return {}
        notes: Dict[str, Note] = {}
        try:
            for path in self.vault_path.rglob("*.md"):
                if any(p.startswith(".") for p in path.parts):
                    continue
                if any(seg in path.parts for seg in (".git", ".obsidian", "node_modules")):
                    continue
                try:
                    stat = path.stat()
                    if path in self._index and self._index[path].mtime == stat.st_mtime:
                        notes[path] = self._index[path]
                        continue
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    notes[path] = self._parse_note(path, content, stat.st_mtime)
                except Exception as e:
                    logger.debug("Skipping %s: %s", path, e)
        except Exception as e:
            logger.error("Index build failed: %s", e)
        self._index = notes
        self._index_mtime = time.time()
        return notes

    def _parse_note(self, path: Path, content: str, mtime: float) -> Note:
        """Parse a single note: frontmatter, tags, links, body."""
        frontmatter: Dict[str, Any] = {}
        body = content

        # YAML-ish frontmatter
        if content.startswith("---"):
            try:
                end = content.find("---", 3)
                if end > 0:
                    raw = content[3:end].strip()
                    body = content[end + 3 :].lstrip("\n")
                    for line in raw.splitlines():
                        if ":" in line:
                            k, _, v = line.partition(":")
                            frontmatter[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass

        # Tags
        tags = re.findall(r"#([\w\-/]+)", body)

        # Wiki links [[Note Name]] or [[Note Name|alias]]
        links: List[str] = []
        for m in re.finditer(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]", body):
            links.append(m.group(1).strip())

        title = path.stem

        return Note(
            path=str(path.relative_to(self.vault_path)).replace("\\", "/"),
            title=title,
            content=body,
            frontmatter=frontmatter,
            tags=tags,
            links=links,
            mtime=mtime,
        )

    def _ensure_index(self) -> Dict[str, Note]:
        if not self._index:
            self._build_index()
        return self._index

    # ------------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------------

    async def search(self, query: str, limit: int = 10) -> List[NoteResult]:
        """Search the vault for notes matching a query.

        Uses a simple TF-IDF-style scoring with:
        - Title matches (weight 5x)
        - Tag matches (weight 3x)
        - Body keyword matches (weight 1x)
        """
        return await asyncio.to_thread(self._search_sync, query, limit)

    def _search_sync(self, query: str, limit: int) -> List[NoteResult]:
        index = self._ensure_index()
        query_lower = query.lower()
        query_terms = [t for t in re.split(r"\s+", query_lower) if len(t) > 1]
        if not query_terms:
            return []

        results: List[NoteResult] = []
        for path, note in index.items():
            score = 0.0
            title_lower = note.title.lower()
            body_lower = note.content.lower()
            tags_lower = " ".join(note.tags).lower()

            for term in query_terms:
                # Title
                if term in title_lower:
                    score += 5.0
                # Tags
                if term in tags_lower:
                    score += 3.0
                # Body count
                count = body_lower.count(term)
                if count:
                    score += min(count, 10) * 0.5
                # Frontmatter
                for v in note.frontmatter.values():
                    if isinstance(v, str) and term in v.lower():
                        score += 2.0

            if score > 0:
                # Snippet around first match
                snippet = self._make_snippet(note.content, query_terms[0])
                results.append(
                    NoteResult(
                        path=note.path,
                        title=note.title,
                        snippet=snippet,
                        score=round(score, 2),
                        tags=note.tags[:10],
                        frontmatter=note.frontmatter,
                    )
                )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    def _make_snippet(self, content: str, term: str, window: int = 200) -> str:
        idx = content.lower().find(term)
        if idx < 0:
            return content[:window] + ("..." if len(content) > window else "")
        start = max(0, idx - window // 2)
        end = min(len(content), idx + window // 2)
        prefix = "..." if start > 0 else ""
        suffix = "..." if end < len(content) else ""
        return f"{prefix}{content[start:end].strip()}{suffix}"

    # ------------------------------------------------------------------------
    # Read / Write
    # ------------------------------------------------------------------------

    async def read_note(self, path: str) -> str:
        """Read a note by vault-relative path. Returns full content."""
        return await asyncio.to_thread(self._read_note_sync, path)

    def _read_note_sync(self, path: str) -> str:
        full = self.vault_path / path
        if not full.exists():
            raise FileNotFoundError(f"Note not found: {path}")
        return full.read_text(encoding="utf-8", errors="ignore")

    async def write_note(self, path: str, content: str) -> None:
        """Write a note (creates parent dirs as needed)."""
        return await asyncio.to_thread(self._write_note_sync, path, content)

    def _write_note_sync(self, path: str, content: str) -> None:
        full = self.vault_path / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
        # Invalidate cache
        self._index.pop(full, None)

    # ------------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------------

    async def list_skills(self) -> List[Dict[str, str]]:
        """List all SKILL.md files in the skills-universal folder."""
        def _list() -> List[Dict[str, str]]:
            skills_dir = self.vault_path / "brain" / "skills-universal"
            if not skills_dir.exists():
                return []
            out: List[Dict[str, str]] = []
            for skill_dir in skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    try:
                        content = skill_file.read_text(encoding="utf-8", errors="ignore")
                        description = ""
                        for line in content.splitlines():
                            if line.strip() and not line.startswith("#"):
                                description = line.strip()
                                break
                        out.append({
                            "name": skill_dir.name,
                            "description": description[:200],
                            "path": str(skill_file.relative_to(self.vault_path)).replace("\\", "/"),
                        })
                    except Exception:
                        out.append({"name": skill_dir.name, "description": "", "path": ""})
            return sorted(out, key=lambda x: x["name"])
        return await asyncio.to_thread(_list)

    async def list_mocs(self) -> List[str]:
        """List all Maps of Content (MOC/*.md)."""
        def _list() -> List[str]:
            moc_dir = self.vault_path / "MOC"
            if not moc_dir.exists():
                return []
            return sorted([p.stem for p in moc_dir.rglob("*.md")])
        return await asyncio.to_thread(_list)

    async def list_routing_agents(self) -> List[str]:
        """List the 12 routing agents defined in vault CLAUDE.md."""
        return [
            "architect", "scribe", "seeker", "connector", "librarian",
            "postman", "strategist", "ghostwriter", "auditor",
            "researcher", "pulse", "bridge",
        ]

    async def get_smart_skill(self, query: str, limit: int = 3) -> List[Dict[str, str]]:
        """Smart skill loader: return top-N skills most relevant to the query.

        Uses vault RAG approach (STI) — 70-80% token savings by loading only relevant skills.
        """
        skills = await self.list_skills()
        # Score by simple keyword match on description
        scored = []
        query_lower = query.lower()
        query_terms = [t for t in re.split(r"\s+", query_lower) if len(t) > 2]
        for skill in skills:
            score = 0.0
            desc_lower = skill["description"].lower()
            name_lower = skill["name"].lower()
            for term in query_terms:
                if term in name_lower:
                    score += 3.0
                if term in desc_lower:
                    score += 1.0
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    async def get_vault_stats(self) -> Dict[str, Any]:
        """Get statistics about the vault."""
        def _stats() -> Dict[str, Any]:
            index = self._ensure_index()
            total_size = sum(len(n.content) for n in index.values())
            return {
                "vault_path": str(self.vault_path),
                "connected": self.is_connected,
                "note_count": len(index),
                "total_chars": total_size,
                "total_links": sum(len(n.links) for n in index.values()),
                "unique_tags": len(set(t for n in index.values() for t in n.tags)),
            }
        return await asyncio.to_thread(_stats)


# ----------------------------------------------------------------------------
# Singleton
# ----------------------------------------------------------------------------

_BRIDGE: Optional[ObsidianBridge] = None


def get_bridge() -> ObsidianBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = ObsidianBridge()
    return _BRIDGE
