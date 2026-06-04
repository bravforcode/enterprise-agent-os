"""Graxia Tool — Progressive Skill Loader.

Metadata-first skill loading system that avoids loading all 60+ skills (~300k tokens)
at startup. Uses SQLite for metadata storage and YAML for skill index.

Features:
    - SkillIndex: Metadata-only loading with lazy full content loading
    - Trust validation: Prompt injection detection, size limits, role hijacking
    - Auto-detection: Project toolchain scanning for relevant skill suggestions
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from ..core.logging import get_logger

logger = get_logger("skill_loader")

# Constants
SKILLS_INDEX_PATH = Path.home() / ".graxia" / "skills-index.yaml"
SESSION_DB_PATH = Path.home() / ".graxia" / "session_memory.db"
MAX_SKILL_SIZE_BYTES = 100_000  # 100KB limit per skill file
INJECTION_PATTERNS = [
    r"ignore\s+(previous|all)\s+(instructions|prompts)",
    r"you\s+are\s+now\s+(a|an)\s+",
    r"disregard\s+(your|all)\s+(rules|guidelines)",
    r"new\s+instructions?:",
    r"system\s*prompt\s*(override|change|replace)",
    r"act\s+as\s+(if|though)\s+",
    r"pretend\s+you\s+are\s+",
    r"roleplay\s+as\s+",
    r"bypass\s+(safety|security|guardrails)",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode",
]
ROLE_HIJACK_PATTERNS = [
    r"<\|system\|>",
    r"<\|user\|>",
    r"<\|assistant\|>",
    r"\[system\]",
    r"\[INST\]",
    r"<<SYS>>",
    r"<</SYS>>",
    r"###\s*System:",
    r"###\s*Human:",
    r"###\s*Assistant:",
]

# Auto-detection mappings
STACK_SKILL_MAP: dict[str, list[str]] = {
    "python": ["systematic-debugging", "rtk-tdd", "code-simplification", "security-review"],
    "javascript": ["frontend-design", "webapp-testing", "security-review"],
    "typescript": ["frontend-design", "webapp-testing", "security-review"],
    "rust": ["rtk-tdd", "design-patterns", "code-simplifier"],
    "go": ["systematic-debugging", "security-review"],
    "react": ["frontend-design", "webapp-testing"],
    "node": ["webapp-testing", "security-review"],
    "docker": ["subagent-infrastructure"],
    "kubernetes": ["subagent-infrastructure"],
    "mcp": ["mcp-builder"],
    "api": ["api-design", "security-review"],
    "test": ["test-driven-development", "rtk-tdd"],
    "docs": ["doc-coauthoring"],
    "data": ["subagent-data-ai"],
    "ai": ["subagent-data-ai", "reasoningbank-intelligence"],
}


@dataclass
class SkillMetadata:
    """Lightweight skill metadata (no content loaded)."""
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    category: str = "general"
    file_path: str = ""
    size_bytes: int = 0
    trust_level: str = "trusted"  # trusted | verified | untrusted
    last_verified: float = 0.0
    checksum: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "triggers": self.triggers,
            "category": self.category,
            "file_path": self.file_path,
            "size_bytes": self.size_bytes,
            "trust_level": self.trust_level,
        }


@dataclass
class SkillContent:
    """Full skill content loaded from file."""
    metadata: SkillMetadata
    content: str
    tokens_estimate: int = 0

    def __post_init__(self) -> None:
        if self.tokens_estimate == 0 and self.content:
            # Rough estimate: 1 token ≈ 4 chars
            self.tokens_estimate = len(self.content) // 4


@dataclass
class SearchResult:
    """Search result with relevance score."""
    skill: SkillMetadata
    score: float
    match_reason: str = ""


@dataclass
class DetectionResult:
    """Auto-detection result for a project."""
    project_path: str
    detected_stacks: list[str] = field(default_factory=list)
    detected_files: list[str] = field(default_factory=list)
    recommended_skills: list[SkillMetadata] = field(default_factory=list)


class TrustValidator:
    """Validates skill content for security issues."""

    @staticmethod
    def check_injection(content: str) -> tuple[bool, list[str]]:
        """Check for prompt injection patterns. Returns (safe, issues)."""
        issues: list[str] = []
        content_lower = content.lower()
        for pattern in INJECTION_PATTERNS:
            if re.search(pattern, content_lower):
                issues.append(f"Potential injection: {pattern}")
        return len(issues) == 0, issues

    @staticmethod
    def check_role_hijack(content: str) -> tuple[bool, list[str]]:
        """Check for role hijacking patterns. Returns (safe, issues)."""
        issues: list[str] = []
        for pattern in ROLE_HIJACK_PATTERNS:
            if re.search(pattern, content, re.IGNORECASE):
                issues.append(f"Role hijack pattern: {pattern}")
        return len(issues) == 0, issues

    @staticmethod
    def check_size(content_bytes: int) -> tuple[bool, str]:
        """Check file size against limit."""
        if content_bytes > MAX_SKILL_SIZE_BYTES:
            return False, f"File too large: {content_bytes} > {MAX_SKILL_SIZE_BYTES}"
        return True, ""

    @classmethod
    def validate(cls, content: str, trust_level: str = "trusted") -> tuple[bool, list[str]]:
        """Full validation. Returns (is_safe, all_issues)."""
        all_issues: list[str] = []

        # Size check
        size_ok, size_msg = cls.check_size(len(content.encode("utf-8")))
        if not size_ok:
            all_issues.append(size_msg)

        # Injection check (always run for untrusted, skip for trusted if desired)
        inj_ok, inj_issues = cls.check_injection(content)
        if not inj_ok:
            all_issues.extend(inj_issues)

        # Role hijack check
        hijack_ok, hijack_issues = cls.check_role_hijack(content)
        if not hijack_ok:
            all_issues.extend(hijack_issues)

        # For untrusted content, be more strict
        if trust_level == "untrusted" and all_issues:
            return False, all_issues

        return len(all_issues) == 0, all_issues


class SkillIndex:
    """Metadata-first skill loading system.

    Loads only metadata at startup (~2k tokens instead of ~300k).
    Full content loaded on-demand via load_full().

    Usage:
        index = SkillIndex()
        await index.initialize()

        # Search by query
        results = await index.search("debug python error", top_k=5)

        # Load full content
        skill = await index.load_full("systematic-debugging")

        # Auto-detect project skills
        detected = await index.auto_detect("/path/to/project")
    """

    def __init__(
        self,
        index_path: Optional[str] = None,
        db_path: Optional[str] = None,
        skill_dirs: Optional[list[str]] = None,
    ):
        self.index_path = Path(index_path) if index_path else SKILLS_INDEX_PATH
        self.db_path = Path(db_path) if db_path else SESSION_DB_PATH
        self.skill_dirs = skill_dirs or []
        self._skills: dict[str, SkillMetadata] = {}
        self._db: Optional[sqlite3.Connection] = None
        self._initialized = False
        self._validator = TrustValidator()

    async def initialize(self) -> None:
        """Initialize the index: create DB table, load metadata."""
        if self._initialized:
            return

        # Ensure .graxia directory exists
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize SQLite
        self._init_db()

        # Load or build index
        if self.index_path.exists():
            await self._load_index_yaml()
        else:
            await self._build_index_from_dirs()

        # Cache to SQLite
        await self._sync_to_db()

        self._initialized = True
        logger.info(
            "skill_index_initialized",
            skill_count=len(self._skills),
            index_path=str(self.index_path),
        )

    def _init_db(self) -> None:
        """Create SQLite table for skill metadata cache."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.db_path))
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS skill_metadata (
                name TEXT PRIMARY KEY,
                description TEXT,
                triggers TEXT,  -- JSON array
                category TEXT,
                file_path TEXT,
                size_bytes INTEGER,
                trust_level TEXT,
                last_verified REAL,
                checksum TEXT,
                updated_at REAL
            )
        """)
        self._db.commit()

    async def _load_index_yaml(self) -> None:
        """Load skill metadata from YAML index file."""
        try:
            text = self.index_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            if not data or not isinstance(data, list):
                logger.warning("empty_or_invalid_index", path=str(self.index_path))
                return

            for entry in data:
                if not isinstance(entry, dict) or "name" not in entry:
                    continue
                meta = SkillMetadata(
                    name=entry["name"],
                    description=entry.get("description", ""),
                    triggers=entry.get("triggers", []),
                    category=entry.get("category", "general"),
                    file_path=entry.get("file_path", ""),
                    size_bytes=entry.get("size_bytes", 0),
                    trust_level=entry.get("trust_level", "trusted"),
                    last_verified=entry.get("last_verified", 0.0),
                    checksum=entry.get("checksum", ""),
                )
                self._skills[meta.name] = meta

            logger.info("index_yaml_loaded", count=len(self._skills))
        except Exception as e:
            logger.exception("failed_to_load_index_yaml")

    async def _build_index_from_dirs(self) -> None:
        """Build index by scanning skill directories for SKILL.md files."""
        for skill_dir in self.skill_dirs:
            dir_path = Path(skill_dir)
            if not dir_path.exists():
                continue

            for skill_md in dir_path.rglob("SKILL.md"):
                try:
                    meta = await self._extract_metadata(skill_md)
                    if meta and meta.name not in self._skills:
                        self._skills[meta.name] = meta
                except Exception as e:
                    logger.warning("skill_extract_error", path=str(skill_md), error=str(e))

        # Save index
        await self._save_index_yaml()

    async def _extract_metadata(self, md_path: Path) -> Optional[SkillMetadata]:
        """Extract metadata from SKILL.md frontmatter without loading full content."""
        text = md_path.read_text(encoding="utf-8", errors="replace")
        checksum = hashlib.md5(text.encode()).hexdigest()[:12]

        # Parse frontmatter
        name = md_path.parent.name
        desc = ""
        triggers: list[str] = []

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

        # Determine trust level based on path
        trust_level = "trusted"
        if "untrusted" in str(md_path) or "external" in str(md_path):
            trust_level = "untrusted"
        elif "verified" in str(md_path):
            trust_level = "verified"

        # Get file size
        size_bytes = md_path.stat().st_size

        return SkillMetadata(
            name=name,
            description=desc[:500],
            triggers=triggers,
            category=self._guess_category(md_path),
            file_path=str(md_path),
            size_bytes=size_bytes,
            trust_level=trust_level,
            last_verified=time.time(),
            checksum=checksum,
        )

    def _guess_category(self, path: Path) -> str:
        """Guess skill category from path."""
        path_str = str(path).lower()
        if any(x in path_str for x in ["debug", "test", "tdd"]):
            return "development"
        if any(x in path_str for x in ["security", "audit"]):
            return "security"
        if any(x in path_str for x in ["frontend", "ui", "design"]):
            return "frontend"
        if any(x in path_str for x in ["data", "ml", "ai"]):
            return "data"
        if any(x in path_str for x in ["infra", "deploy", "devops"]):
            return "infrastructure"
        return "general"

    async def _save_index_yaml(self) -> None:
        """Save current index to YAML file."""
        data = [meta.to_dict() for meta in self._skills.values()]
        self.index_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

    async def _sync_to_db(self) -> None:
        """Sync metadata to SQLite for fast queries."""
        if not self._db:
            return

        for meta in self._skills.values():
            self._db.execute(
                """INSERT OR REPLACE INTO skill_metadata
                   (name, description, triggers, category, file_path, size_bytes,
                    trust_level, last_verified, checksum, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    meta.name,
                    meta.description,
                    json.dumps(meta.triggers),
                    meta.category,
                    meta.file_path,
                    meta.size_bytes,
                    meta.trust_level,
                    meta.last_verified,
                    meta.checksum,
                    time.time(),
                ),
            )
        self._db.commit()

    async def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Search skills by metadata (no full content loaded).

        Uses BM25-style scoring on:
        - Name match (exact, partial)
        - Description match
        - Trigger word match
        - Category match
        """
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))
        results: list[SearchResult] = []

        for meta in self._skills.values():
            score = 0.0
            reasons: list[str] = []

            # Exact name match (highest score)
            if query_lower == meta.name.lower():
                score += 1.0
                reasons.append("exact_name")
            elif query_lower in meta.name.lower():
                score += 0.7
                reasons.append("partial_name")

            # Trigger word matches
            for trigger in meta.triggers:
                if trigger in query_lower or query_lower in trigger:
                    score += 0.5
                    reasons.append(f"trigger:{trigger}")
                elif any(w in trigger for w in query_words):
                    score += 0.2
                    reasons.append(f"trigger_word:{trigger}")

            # Description word overlap
            desc_words = set(re.findall(r"\w+", meta.description.lower()))
            overlap = query_words & desc_words
            if overlap:
                score += min(len(overlap) * 0.15, 0.6)
                reasons.append(f"desc_overlap:{len(overlap)}")

            # Category match
            if meta.category in query_lower:
                score += 0.3
                reasons.append(f"category:{meta.category}")

            # Trust bonus
            if meta.trust_level == "trusted":
                score += 0.05

            if score > 0:
                results.append(SearchResult(
                    skill=meta,
                    score=round(score, 3),
                    match_reason=", ".join(reasons[:3]),
                ))

        # Sort by score descending
        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    async def load_full(self, skill_name: str) -> Optional[SkillContent]:
        """Load full SKILL.md content for a skill.

        Validates content before returning.
        """
        meta = self._skills.get(skill_name)
        if not meta:
            logger.warning("skill_not_found", name=skill_name)
            return None

        if not meta.file_path or not Path(meta.file_path).exists():
            logger.warning("skill_file_missing", name=skill_name, path=meta.file_path)
            return None

        try:
            file_path = Path(meta.file_path)
            content = file_path.read_text(encoding="utf-8", errors="replace")

            # Validate trust
            is_safe, issues = self._validator.validate(content, meta.trust_level)
            if not is_safe:
                logger.warning(
                    "skill_validation_failed",
                    name=skill_name,
                    issues=issues,
                )
                # Still return content but mark as untrusted
                meta.trust_level = "untrusted"

            return SkillContent(
                metadata=meta,
                content=content,
            )
        except Exception as e:
            logger.exception("failed_to_load_skill", name=skill_name)
            return None

    async def auto_detect(self, project_path: str) -> DetectionResult:
        """Detect project toolchain and suggest relevant skills.

        Scans for:
        - pyproject.toml, setup.py, requirements.txt (Python)
        - package.json (Node.js/JavaScript/TypeScript)
        - Cargo.toml (Rust)
        - go.mod (Go)
        - Dockerfile, docker-compose.yml (Docker)
        - *.tf (Terraform)
        - k8s/ or kubernetes/ (Kubernetes)
        """
        project = Path(project_path)
        if not project.exists():
            return DetectionResult(project_path=project_path)

        detected_stacks: list[str] = []
        detected_files: list[str] = []

        # Check for Python
        for f in ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"]:
            if (project / f).exists():
                detected_stacks.append("python")
                detected_files.append(f)
                break

        # Check for Node.js/JS/TS
        pkg_json = project / "package.json"
        if pkg_json.exists():
            detected_files.append("package.json")
            try:
                pkg_data = json.loads(pkg_json.read_text(encoding="utf-8"))
                deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
                if any(k.startswith("react") for k in deps):
                    detected_stacks.append("react")
                if any(k.startswith("next") for k in deps):
                    detected_stacks.append("node")
                if "typescript" in deps or "ts-node" in deps:
                    detected_stacks.append("typescript")
                elif any(k.startswith("@types/") for k in deps):
                    detected_stacks.append("typescript")
                else:
                    detected_stacks.append("javascript")
            except (json.JSONDecodeError, KeyError):
                detected_stacks.append("javascript")

        # Check for Rust
        if (project / "Cargo.toml").exists():
            detected_stacks.append("rust")
            detected_files.append("Cargo.toml")

        # Check for Go
        if (project / "go.mod").exists():
            detected_stacks.append("go")
            detected_files.append("go.mod")

        # Check for Docker
        if (project / "Dockerfile").exists() or (project / "docker-compose.yml").exists():
            detected_stacks.append("docker")
            if (project / "Dockerfile").exists():
                detected_files.append("Dockerfile")
            if (project / "docker-compose.yml").exists():
                detected_files.append("docker-compose.yml")

        # Check for Kubernetes
        if (project / "k8s").exists() or (project / "kubernetes").exists():
            detected_stacks.append("kubernetes")
            detected_files.append("k8s/ or kubernetes/")

        # Check for Terraform
        if list(project.glob("*.tf")):
            detected_stacks.append("terraform")
            detected_files.append("*.tf")

        # Check for MCP
        if list(project.glob("*mcp*.py")) or list(project.glob("*mcp*.ts")):
            detected_stacks.append("mcp")
            detected_files.append("*mcp*")

        # Check for API-related files
        if list(project.glob("*api*")) or list(project.glob("*endpoint*")):
            detected_stacks.append("api")

        # Check for test directories
        if (project / "tests").exists() or (project / "test").exists():
            detected_stacks.append("test")
            detected_files.append("tests/")

        # Check for docs
        if (project / "docs").exists() or (project / "README.md").exists():
            detected_stacks.append("docs")

        # Check for data/AI files
        if list(project.glob("*.ipynb")) or (project / "notebooks").exists():
            detected_stacks.append("data")
            detected_stacks.append("ai")

        # Map stacks to recommended skills
        recommended_names: set[str] = set()
        for stack in detected_stacks:
            if stack in STACK_SKILL_MAP:
                recommended_names.update(STACK_SKILL_MAP[stack])

        # Get metadata for recommended skills
        recommended = [
            self._skills[name]
            for name in recommended_names
            if name in self._skills
        ]

        return DetectionResult(
            project_path=project_path,
            detected_stacks=detected_stacks,
            detected_files=detected_files,
            recommended_skills=recommended,
        )

    async def refresh(self) -> int:
        """Force refresh the index. Returns number of skills loaded."""
        self._skills.clear()
        if self.index_path.exists():
            await self._load_index_yaml()
        else:
            await self._build_index_from_dirs()
        await self._sync_to_db()
        return len(self._skills)

    async def add_skill(self, meta: SkillMetadata) -> None:
        """Add or update a skill in the index."""
        self._skills[meta.name] = meta
        await self._sync_to_db()
        await self._save_index_yaml()

    async def remove_skill(self, name: str) -> bool:
        """Remove a skill from the index."""
        if name not in self._skills:
            return False
        del self._skills[name]
        if self._db:
            self._db.execute("DELETE FROM skill_metadata WHERE name = ?", (name,))
            self._db.commit()
        await self._save_index_yaml()
        return True

    def get_skill_count(self) -> int:
        """Get number of indexed skills."""
        return len(self._skills)

    def list_categories(self) -> dict[str, int]:
        """List categories and their skill counts."""
        counts: dict[str, int] = {}
        for meta in self._skills.values():
            counts[meta.category] = counts.get(meta.category, 0) + 1
        return counts

    async def close(self) -> None:
        """Close database connection."""
        if self._db:
            self._db.close()
            self._db = None


# Singleton instance
_index: Optional[SkillIndex] = None


async def get_skill_index() -> SkillIndex:
    """Get or create the singleton SkillIndex."""
    global _index
    if _index is None:
        _index = SkillIndex()
        await _index.initialize()
    return _index


# Tool handlers (for MCP integration)

async def _skill_search_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Handle skill_search MCP tool call."""
    index = await get_skill_index()
    query = args.get("query", "")
    top_k = int(args.get("top_k", 5))

    if not query:
        return {"content": [{"type": "text", "text": "ERROR: query is required"}], "isError": True}

    results = await index.search(query, top_k=top_k)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "results": [
                    {
                        "name": r.skill.name,
                        "description": r.skill.description,
                        "score": r.score,
                        "match_reason": r.match_reason,
                        "category": r.skill.category,
                        "trust_level": r.skill.trust_level,
                    }
                    for r in results
                ],
                "count": len(results),
            }, indent=2),
        }],
    }


async def _skill_load_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Handle skill_load MCP tool call."""
    index = await get_skill_index()
    skill_name = args.get("skill_name", "")

    if not skill_name:
        return {"content": [{"type": "text", "text": "ERROR: skill_name is required"}], "isError": True}

    skill = await index.load_full(skill_name)
    if skill is None:
        return {"content": [{"type": "text", "text": f"ERROR: Skill '{skill_name}' not found"}], "isError": True}

    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "name": skill.metadata.name,
                "description": skill.metadata.description,
                "content": skill.content,
                "tokens_estimate": skill.tokens_estimate,
                "trust_level": skill.metadata.trust_level,
                "category": skill.metadata.category,
            }, indent=2),
        }],
    }


async def _skill_detect_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Handle skill_detect MCP tool call."""
    index = await get_skill_index()
    project_path = args.get("project_path", "")

    if not project_path:
        return {"content": [{"type": "text", "text": "ERROR: project_path is required"}], "isError": True}

    result = await index.auto_detect(project_path)
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({
                "project_path": result.project_path,
                "detected_stacks": result.detected_stacks,
                "detected_files": result.detected_files,
                "recommended_skills": [
                    {
                        "name": s.name,
                        "description": s.description,
                        "category": s.category,
                    }
                    for s in result.recommended_skills
                ],
            }, indent=2),
        }],
    }


async def _skill_refresh_handler(args: dict[str, Any]) -> dict[str, Any]:
    """Handle skill_refresh MCP tool call."""
    index = await get_skill_index()
    count = await index.refresh()
    return {
        "content": [{
            "type": "text",
            "text": json.dumps({"refreshed": True, "skill_count": count}),
        }],
    }


# MCP tool definitions for integration

SKILL_LOADER_TOOLS = [
    {
        "name": "skill_search",
        "description": "MANDATORY FOR SKILL TASKS: Search 485+ skills by metadata. Auto-triggers on: feature creation, debugging, code review, planning, testing, deployment, research.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query (e.g., 'debug python error')"},
                "top_k": {"type": "integer", "default": 5, "description": "Max results to return"},
            },
            "required": ["query"],
        },
        "handler": _skill_search_handler,
        "category": "skills",
    },
    {
        "name": "skill_load",
        "description": "Load full skill content by name. Validates trust level before returning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string", "description": "Name of the skill to load"},
            },
            "required": ["skill_name"],
        },
        "handler": _skill_load_handler,
        "category": "skills",
    },
    {
        "name": "skill_detect",
        "description": "Auto-detect project toolchain and suggest relevant skills.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_path": {"type": "string", "description": "Path to project root"},
            },
            "required": ["project_path"],
        },
        "handler": _skill_detect_handler,
        "category": "skills",
    },
    {
        "name": "skill_refresh",
        "description": "Force refresh the skill index from disk.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": _skill_refresh_handler,
        "category": "skills",
    },
]
