"""Markdown skill CRUD on disk.

Skills live in a per-space directory::

    {base_dir}/spaces/{space}/skills/{name}.md

Each `.md` file contains YAML frontmatter (see :mod:`schema`) followed
by the Markdown body. Writes are atomic (write to a temp file, then
``Path.replace``) so a crash mid-write cannot corrupt an existing skill.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Union

from .schema import Skill, SkillMetadata, parse_frontmatter, render_skill


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PathLike = Union[str, os.PathLike]


def default_base_dir() -> Path:
    """Default skill root: ``~/.graxia/acontext``."""
    return Path(os.path.expanduser("~")) / ".graxia" / "acontext"


def _safe_name(name: str) -> str:
    """Normalize a skill name to a safe filename stem.

    Lower-cased, hyphenated, ASCII-only. Replaces any other character
    with ``-`` and collapses repeats.
    """
    if not name:
        raise ValueError("skill name must not be empty")
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        raise ValueError(f"skill name {name!r} resolves to empty after normalization")
    return s


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class SkillStore:
    """Filesystem-backed skill store for a single space.

    Args:
        space: Logical name of the space (folder under ``spaces/``).
        base_dir: Root directory. Defaults to :func:`default_base_dir`.

    The store is process-safe enough for typical agent workloads (single
    writer per space, or multiple readers with rare writers). For more
    aggressive concurrency, wrap calls in a lock at the call site.
    """

    def __init__(self, space: str, base_dir: Optional[PathLike] = None) -> None:
        if not space or not space.strip():
            raise ValueError("space name must be non-empty")
        self.space = space.strip()
        self.base_dir = Path(base_dir) if base_dir is not None else default_base_dir()
        self.skills_dir = self.base_dir / "spaces" / self._safe_space(self.space) / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_space(space: str) -> str:
        s = space.strip().lower()
        s = re.sub(r"[^a-z0-9._-]+", "-", s)
        s = re.sub(r"-+", "-", s).strip("-")
        if not s:
            raise ValueError(f"space name {space!r} resolves to empty after normalization")
        return s

    # --- paths -----------------------------------------------------------

    def path_for(self, name: str) -> Path:
        return self.skills_dir / f"{_safe_name(name)}.md"

    # --- CRUD ------------------------------------------------------------

    def list_skills(self) -> List[Skill]:
        """List every skill in this space (sorted by name)."""
        items: List[Skill] = []
        for path in sorted(self.skills_dir.glob("*.md")):
            try:
                items.append(self._read_path(path))
            except Exception:
                # Skip corrupt / partial files; never blow up the list view
                continue
        return items

    def list_metadata(self) -> List[SkillMetadata]:
        """List just the metadata, no body — useful for `acontext_list_skills`."""
        return [s.meta for s in self.list_skills()]

    def get(self, name: str) -> Optional[Skill]:
        """Read a single skill. Returns ``None`` if it does not exist."""
        path = self.path_for(name)
        if not path.exists():
            return None
        return self._read_path(path)

    def exists(self, name: str) -> bool:
        return self.path_for(name).exists()

    def save(self, skill: Skill, *, bump_version: bool = True) -> Skill:
        """Create or update a skill.

        If a file with the same name exists, its body is replaced and
        ``updated_at``/``version`` are bumped. If ``bump_version`` is
        False and the file is new, the new skill is created at version 1.
        """
        if not skill.meta.name:
            raise ValueError("Skill.metadata.name is required")

        path = self.path_for(skill.meta.name)
        existed = path.exists()
        if existed and bump_version:
            # Preserve created_at; bump version and updated_at
            try:
                existing = self._read_path(path)
                skill.meta.created_at = existing.meta.created_at or skill.meta.created_at
            except Exception:
                pass
            skill.meta.touch()
        elif not existed:
            now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if not skill.meta.created_at:
                skill.meta.created_at = now
            skill.meta.updated_at = now
            if skill.meta.version < 1:
                skill.meta.version = 1

        rendered = render_skill(skill)
        self._atomic_write(path, rendered)
        return skill

    def upsert(self, name: str, description: str, body: str, *,
               tags: Optional[Iterable[str]] = None,
               source_session: str = "",
               bump_version: bool = True) -> Skill:
        """Convenience: create or update by name."""
        tags_list = [t.strip() for t in (tags or []) if t and t.strip()]
        existing = self.get(name)
        if existing is not None:
            meta = existing.meta
            meta.description = description or meta.description
            if tags_list:
                meta.tags = tags_list
            if source_session:
                meta.source_session = source_session
            skill = Skill(meta=meta, body=body)
        else:
            meta = SkillMetadata(
                name=name,
                description=description,
                tags=tags_list,
                source_session=source_session,
            )
            skill = Skill(meta=meta, body=body)
        return self.save(skill, bump_version=bump_version)

    def delete(self, name: str) -> bool:
        """Delete a skill. Returns True if it was present and removed."""
        path = self.path_for(name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def count(self) -> int:
        return sum(1 for _ in self.skills_dir.glob("*.md"))

    # --- internals -------------------------------------------------------

    def _read_path(self, path: Path) -> Skill:
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        if not meta.name:
            # Fall back to filename if frontmatter is missing
            meta.name = path.stem
        return Skill(meta=meta, body=body)

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass
