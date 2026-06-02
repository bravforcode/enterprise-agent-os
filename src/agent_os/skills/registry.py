"""Enterprise Agent OS — Skill Registry.

YAML-based skill definitions with hot-reload.
Maps skills to intents + domains.
"""
from __future__ import annotations
import os
import time
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Optional
from ..core.logging import get_logger

logger = get_logger("skill_registry")


@dataclass
class SkillDefinition:
    """A registered skill."""
    name: str
    description: str
    path: str
    tier: int = 2
    trust_score: float = 1.0
    triggers: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    tools_required: list[str] = field(default_factory=list)
    max_tokens: int = 3000
    timeout_seconds: int = 30
    metadata: dict[str, Any] = field(default_factory=dict)
    last_loaded: float = 0.0
    file_hash: str = ""


class SkillRegistry:
    """
    Registry of available skills.
    Loads from YAML files, supports hot-reload.
    """

    def __init__(self, skill_dirs: Optional[list[str]] = None):
        self.skills: dict[str, SkillDefinition] = {}
        self.skill_dirs = skill_dirs or []
        self._last_scan: float = 0
        self._scan_interval: float = 5.0  # seconds between scans

    def add_skill_dir(self, path: str) -> None:
        """Add a directory to scan for skill YAML files."""
        if path not in self.skill_dirs:
            self.skill_dirs.append(path)

    def load_all(self) -> int:
        """Load all skills from registered directories. Returns count."""
        count = 0
        for skill_dir in self.skill_dirs:
            dir_path = Path(skill_dir)
            if not dir_path.exists():
                continue
            # Scan for .yaml and .yml files
            for ext in ("*.yaml", "*.yml"):
                for yaml_file in dir_path.glob(ext):
                    try:
                        skill = self._load_skill(yaml_file)
                        if skill:
                            self.skills[skill.name] = skill
                            count += 1
                    except Exception as e:
                        logger.warning("skill_load_error", file=str(yaml_file), error=str(e))

        # Also scan for SKILL.md files (markdown format)
        for skill_dir in self.skill_dirs:
            dir_path = Path(skill_dir)
            if not dir_path.exists():
                continue
            for skill_md in dir_path.rglob("SKILL.md"):
                try:
                    skill = self._load_skill_md(skill_md)
                    if skill and skill.name not in self.skills:
                        self.skills[skill.name] = skill
                        count += 1
                except Exception as e:
                    logger.warning("skill_md_load_error", file=str(skill_md), error=str(e))

        self._last_scan = time.time()
        logger.info("skills_loaded", count=count, dirs=len(self.skill_dirs))
        return count

    def maybe_reload(self) -> int:
        """Hot-reload if enough time has passed since last scan."""
        if time.time() - self._last_scan < self._scan_interval:
            return 0
        return self.load_all()

    def _load_skill(self, yaml_path: Path) -> Optional[SkillDefinition]:
        """Load a skill from a YAML file."""
        import hashlib
        text = yaml_path.read_text(encoding="utf-8", errors="replace")
        file_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        # Skip if unchanged
        existing = self.skills.get(yaml_path.stem)
        if existing and existing.file_hash == file_hash:
            return existing

        data = yaml.safe_load(text)
        if not data or not isinstance(data, dict):
            return None

        return SkillDefinition(
            name=data.get("name", yaml_path.stem),
            description=data.get("description", ""),
            path=str(yaml_path),
            tier=data.get("tier", 2),
            trust_score=data.get("trust_score", 1.0),
            triggers=data.get("triggers", []),
            intents=data.get("intents", []),
            domains=data.get("domains", []),
            tools_required=data.get("tools_required", []),
            max_tokens=data.get("max_tokens", 3000),
            timeout_seconds=data.get("timeout_seconds", 30),
            metadata=data.get("metadata", {}),
            last_loaded=time.time(),
            file_hash=file_hash,
        )

    def _load_skill_md(self, md_path: Path) -> Optional[SkillDefinition]:
        """Load a skill from SKILL.md (parse frontmatter)."""
        import hashlib
        import re
        text = md_path.read_text(encoding="utf-8", errors="replace")
        file_hash = hashlib.md5(text.encode()).hexdigest()[:12]

        # Parse frontmatter
        name = md_path.parent.name
        desc = ""
        triggers = []

        m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
        if m:
            fm = m.group(1)
            name_m = re.search(r"^name:\s*(.+)$", fm, re.MULTILINE)
            if name_m:
                name = name_m.group(1).strip().strip("'\"")
            desc_m = re.search(r"^description:\s*(.*)$", fm, re.MULTILINE)
            if desc_m:
                desc = desc_m.group(1).strip().strip("'\"")

        # Extract triggers from backticks in description
        for mm in re.finditer(r"`([^`]+)`", desc):
            w = mm.group(1).strip().lower()
            if w and len(w) < 40 and not w.startswith("http"):
                triggers.append(w)

        return SkillDefinition(
            name=name,
            description=desc[:500],
            path=str(md_path.parent),
            tier=4 if "vault" in str(md_path) or "brain" in str(md_path) else 2,
            triggers=triggers,
            last_loaded=time.time(),
            file_hash=file_hash,
        )

    def match_intent(
        self, intent: str, domain: str, top_k: int = 3
    ) -> list[SkillDefinition]:
        """Find skills matching an intent + domain."""
        scored: list[tuple[float, SkillDefinition]] = []
        for skill in self.skills.values():
            score = 0.0
            # Intent match
            if intent in skill.intents:
                score += 0.5
            # Domain match
            if domain in skill.domains:
                score += 0.3
            # Trust score
            score += skill.trust_score * 0.2
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:top_k]]

    def get_skill(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill by name."""
        return self.skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """List all registered skills."""
        return list(self.skills.values())
