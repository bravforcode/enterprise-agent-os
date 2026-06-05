"""Skill Registry — loads SKILL.md + YAML frontmatter, manages trust/versioning."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class TrustLevel(str, Enum):
    TRUSTED = "trusted"
    VERIFIED = "verified"
    UNTRUSTED = "untrusted"


@dataclass(frozen=True, order=True)
class SemVer:
    major: int = 0
    minor: int = 1
    patch: int = 0

    # ---- helpers ----------------------------------------------------------

    @classmethod
    def parse(cls, raw: str | None) -> SemVer:
        if not raw:
            return cls()
        parts = raw.strip().lstrip("v").split(".")
        nums = [int(p) for p in parts[:3]]
        return cls(*nums)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def is_compatible(self, other: SemVer) -> bool:
        """SemVer compatibility: same major, other <= self."""
        return self.major == other.major and other <= self


@dataclass
class SkillMeta:
    """Lightweight metadata — returned first in progressive disclosure."""
    name: str
    version: SemVer
    trust: TrustLevel
    category: str = ""
    triggers: List[str] = field(default_factory=list)
    description: str = ""
    source_path: str = ""
    sha256: str = ""
    loaded_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": str(self.version),
            "trust": self.trust.value,
            "category": self.category,
            "triggers": self.triggers,
            "description": self.description,
            "source_path": self.source_path,
            "sha256": self.sha256,
        }


@dataclass
class Skill:
    """Full skill — metadata + full markdown body."""
    meta: SkillMeta
    body: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = self.meta.to_dict()
        d["body"] = self.body
        return d


# ---------------------------------------------------------------------------
# YAML frontmatter parser (stdlib only — no pyyaml)
# ---------------------------------------------------------------------------

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_yaml_minimal(text: str) -> Tuple[Dict[str, Any], str]:
    """Tiny YAML subset parser: key: value, key: [a, b], key: 'quoted'."""
    meta: Dict[str, Any] = {}
    m = _FRONT_RE.match(text)
    if not m:
        return meta, text
    raw = m.group(1)
    body = text[m.end():]
    current_key: str | None = None
    for line in raw.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  ") and current_key:
            # continuation (list item or indented value)
            item = line.strip().strip("- ").strip()
            if isinstance(meta[current_key], list):
                meta[current_key].append(item)
            else:
                meta[current_key] = item
            continue
        kv = line.split(":", 1)
        if len(kv) == 2:
            key = kv[0].strip()
            val = kv[1].strip().strip("'\"")
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1]
                meta[key] = [v.strip().strip("'\"") for v in inner.split(",") if v.strip()]
            elif val == "":
                meta[key] = []
            else:
                meta[key] = val
            current_key = key
    return meta, body


# ---------------------------------------------------------------------------
# Keyword extraction for auto-loading
# ---------------------------------------------------------------------------

_STOP = frozenset(
    "the a an is are was were be been being have has had do does did "
    "will would shall should may might can could of in to for on with "
    "at by from as into through during before after above below between "
    "out off over under again further then once here there when where why "
    "how all both each few more most other some such no nor not only own "
    "same so than too very just don now about up it its i me my we our "
    "you your he him his she her they them their this that these those".split()
)


def _extract_keywords(text: str) -> Set[str]:
    words = re.findall(r"[a-z0-9_\-]{2,}", text.lower())
    return {w for w in words if w not in _STOP}


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """In-memory + SQLite-persisted registry of skills."""

    def __init__(self, db_path: str | Path = ".graxia_skills.db") -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()
        self._skills: Dict[str, Skill] = {}
        self._load_from_db()

    # ---- schema -----------------------------------------------------------

    def _ensure_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS skills (
                name        TEXT PRIMARY KEY,
                version     TEXT NOT NULL,
                trust       TEXT NOT NULL DEFAULT 'untrusted',
                category    TEXT DEFAULT '',
                triggers    TEXT DEFAULT '[]',
                description TEXT DEFAULT '',
                source_path TEXT DEFAULT '',
                sha256      TEXT DEFAULT '',
                body        TEXT DEFAULT '',
                loaded_at   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS version_log (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                version    TEXT NOT NULL,
                prev_ver   TEXT,
                action     TEXT NOT NULL,
                ts         REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_skills_trust ON skills(trust);
            CREATE INDEX IF NOT EXISTS idx_skills_category ON skills(category);
            """
        )
        self._conn.commit()

    def _load_from_db(self) -> None:
        for row in self._conn.execute("SELECT * FROM skills"):
            meta = SkillMeta(
                name=row["name"],
                version=SemVer.parse(row["version"]),
                trust=TrustLevel(row["trust"]),
                category=row["category"],
                triggers=json.loads(row["triggers"]),
                description=row["description"],
                source_path=row["source_path"],
                sha256=row["sha256"],
                loaded_at=row["loaded_at"],
            )
            self._skills[meta.name] = Skill(meta=meta, body=row["body"])

    def _persist(self, skill: Skill) -> None:
        m = skill.meta
        self._conn.execute(
            """INSERT OR REPLACE INTO skills
               (name,version,trust,category,triggers,description,source_path,sha256,body,loaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                m.name, str(m.version), m.trust.value, m.category,
                json.dumps(m.triggers), m.description, m.source_path,
                m.sha256, skill.body, m.loaded_at,
            ),
        )
        self._conn.commit()

    def _log_version(self, name: str, ver: str, prev: str | None, action: str) -> None:
        self._conn.execute(
            "INSERT INTO version_log (name,version,prev_ver,action,ts) VALUES (?,?,?,?,?)",
            (name, ver, prev, action, time.time()),
        )
        self._conn.commit()

    # ---- loading from disk ------------------------------------------------

    def load_from_path(self, path: str | Path, trust: TrustLevel = TrustLevel.UNTRUSTED) -> Skill:
        """Load a single SKILL.md file."""
        p = Path(path)
        raw = p.read_text(encoding="utf-8")
        sha = hashlib.sha256(raw.encode()).hexdigest()
        front, body = _parse_yaml_minimal(raw)

        name = front.get("name", p.stem)
        version = SemVer.parse(front.get("version"))
        category = front.get("category", "")
        triggers = front.get("triggers", [])
        if isinstance(triggers, str):
            triggers = [triggers]
        description = front.get("description", "")

        # Trust override: never upgrade beyond declared trust
        declared_trust = TrustLevel(front.get("trust", trust.value))
        effective_trust = _min_trust(declared_trust, trust)

        meta = SkillMeta(
            name=name,
            version=version,
            trust=effective_trust,
            category=category,
            triggers=triggers,
            description=description,
            source_path=str(p.resolve()),
            sha256=sha,
        )
        skill = Skill(meta=meta, body=body)

        prev = self._skills.get(name)
        prev_ver = str(prev.meta.version) if prev else None

        self._skills[name] = skill
        self._persist(skill)
        self._log_version(name, str(version), prev_ver, "loaded")
        return skill

    def load_directory(self, directory: str | Path, trust: TrustLevel = TrustLevel.UNTRUSTED) -> List[Skill]:
        """Recursively load all SKILL.md files under *directory*."""
        d = Path(directory)
        loaded: List[Skill] = []
        for md in d.rglob("SKILL.md"):
            loaded.append(self.load_from_path(md, trust=trust))
        return loaded

    # ---- retrieval --------------------------------------------------------

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def get_meta(self, name: str) -> SkillMeta | None:
        s = self._skills.get(name)
        return s.meta if s else None

    def all_skills(self) -> List[SkillMeta]:
        return [s.meta for s in self._skills.values()]

    # ---- auto-loading (keyword matching) ----------------------------------

    def auto_load(self, task_description: str, top_k: int = 3) -> List[Skill]:
        """Return top-k skills whose triggers/description match *task_description*."""
        kw = _extract_keywords(task_description)
        scored: List[Tuple[float, Skill]] = []
        for skill in self._skills.values():
            skill_kw = _extract_keywords(
                " ".join(skill.meta.triggers) + " " + skill.meta.description
            )
            overlap = len(kw & skill_kw)
            if overlap:
                scored.append((overlap / max(len(kw), 1), skill))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    # ---- search -----------------------------------------------------------

    def search(
        self,
        query: str = "",
        category: str = "",
        triggers: List[str] | None = None,
        trust: TrustLevel | None = None,
    ) -> List[SkillMeta]:
        results: List[SkillMeta] = []
        qkw = _extract_keywords(query) if query else set()
        for skill in self._skills.values():
            m = skill.meta
            if trust and m.trust != trust:
                continue
            if category and m.category != category:
                continue
            if triggers and not set(triggers) & set(m.triggers):
                continue
            if qkw:
                skill_kw = _extract_keywords(
                    " ".join(m.triggers) + " " + m.description + " " + m.name
                )
                if not (qkw & skill_kw):
                    continue
            results.append(m)
        return results

    # ---- versioning -------------------------------------------------------

    def version_history(self, name: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM version_log WHERE name=? ORDER BY ts DESC", (name,)
        ).fetchall()
        return [dict(r) for r in rows]

    def check_compatibility(self, name: str, required: SemVer) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        return skill.meta.version.is_compatible(required)

    # ---- trust management -------------------------------------------------

    def set_trust(self, name: str, trust: TrustLevel) -> bool:
        skill = self._skills.get(name)
        if not skill:
            return False
        old = skill.meta.trust
        skill.meta.trust = trust
        self._persist(skill)
        self._log_version(name, str(skill.meta.version), None, f"trust:{old.value}->{trust.value}")
        return True

    # ---- progressive disclosure -------------------------------------------

    def meta_only(self, name: str) -> Dict[str, Any] | None:
        """Return metadata dict without body."""
        m = self.get_meta(name)
        return m.to_dict() if m else None

    def full(self, name: str) -> Dict[str, Any] | None:
        """Return metadata + body."""
        s = self.get(name)
        return s.to_dict() if s else None

    # ---- cleanup ----------------------------------------------------------

    def remove(self, name: str) -> bool:
        if name not in self._skills:
            return False
        del self._skills[name]
        self._conn.execute("DELETE FROM skills WHERE name=?", (name,))
        self._conn.commit()
        self._log_version(name, "", None, "removed")
        return True

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_TRUST_ORDER = {
    TrustLevel.TRUSTED: 0,
    TrustLevel.VERIFIED: 1,
    TrustLevel.UNTRUSTED: 2,
}


def _min_trust(a: TrustLevel, b: TrustLevel) -> TrustLevel:
    return a if _TRUST_ORDER[a] <= _TRUST_ORDER[b] else b
