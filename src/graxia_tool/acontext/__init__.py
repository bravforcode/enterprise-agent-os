"""Acontext-style Skill Memory for Graxia Tool.

Port of the core Acontext (https://github.com/memodb-io/Acontext) idea:
  Skill = Memory = Markdown file.

Skills are plain Markdown files on disk with YAML frontmatter. No
embeddings, no vector DB, no vendor lock-in. The agent reads them on
demand (progressive disclosure) and the LLM distills new ones after a
session completes.

Storage layout::

    ~/.graxia/acontext/spaces/{space}/skills/{name}.md

A "space" is a logical grouping (one per project / topic). Skills in
the same space are surfaced together when recalling memory.
"""
from __future__ import annotations

from .schema import Skill, SkillMetadata, parse_frontmatter, render_skill
from .skill_store import SkillStore, default_base_dir
from .recall import BM25, recall_skills
from .distiller import Distiller

__all__ = [
    "Skill",
    "SkillMetadata",
    "SkillStore",
    "Distiller",
    "BM25",
    "recall_skills",
    "parse_frontmatter",
    "render_skill",
    "default_base_dir",
]
