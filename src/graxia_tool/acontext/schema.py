"""Skill frontmatter schema (SKILL.md).

A skill is a single Markdown file with a small YAML frontmatter block.
We do not pull in PyYAML to keep the dependency surface small: a tiny
hand-rolled parser is enough for the keys we control. The keys are:

    name           — kebab-case identifier
    description    — one-liner shown to the LLM during recall
    tags           — list of free-form tags (lowercase)
    created_at     — ISO-8601 timestamp
    updated_at     — ISO-8601 timestamp
    source_session — optional id of the session that produced this skill
    version        — positive integer, bumped on update

The Markdown body (everything after the frontmatter) is the *content*
the agent actually consumes at recall time.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Skill model
# ---------------------------------------------------------------------------

@dataclass
class SkillMetadata:
    """Structured metadata stored in the YAML frontmatter of a SKILL.md file."""

    name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    source_session: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("SkillMetadata.name is required")
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    def touch(self) -> None:
        """Update `updated_at` and bump `version`."""
        self.updated_at = _now_iso()
        self.version += 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Skill:
    """A skill: metadata + Markdown body."""

    meta: SkillMetadata
    body: str

    @property
    def name(self) -> str:
        return self.meta.name

    @property
    def tags(self) -> List[str]:
        return list(self.meta.tags)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*\n?(.*)\Z",
    re.DOTALL,
)


def parse_frontmatter(text: str) -> "tuple[SkillMetadata, str]":
    """Parse a SKILL.md file into (metadata, body).

    Accepts a minimal subset of YAML: strings, lists via `[a, b]` or
    `- a\\n- b`, integers, and bools. Enough for our frontmatter and
    avoids pulling in PyYAML.

    If a file has no frontmatter (or the frontmatter has no ``name``),
    the returned :class:`SkillMetadata` has ``name=""`` and timestamps
    are left blank — callers can fill them in from the filename.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # No frontmatter — return a meta with empty description and a
        # blank placeholder (timestamps blanked to avoid lying about
        # when the file was last seen).
        return _empty_meta(), text

    raw_yaml, body = m.group(1), m.group(2)
    parsed = _parse_minimal_yaml(raw_yaml)
    name = str(parsed.get("name", "")).strip()
    if not name:
        meta = _empty_meta()
    else:
        meta = SkillMetadata(
            name=name,
            description=str(parsed.get("description", "")).strip(),
            tags=[str(t).strip() for t in parsed.get("tags", []) if str(t).strip()],
            created_at=str(parsed.get("created_at", "")).strip(),
            updated_at=str(parsed.get("updated_at", "")).strip(),
            source_session=str(parsed.get("source_session", "")).strip(),
            version=int(parsed.get("version", 1) or 1),
        )
    return meta, body.lstrip("\n")


def _empty_meta() -> SkillMetadata:
    """Construct a SkillMetadata with a name, bypassing __post_init__'s
    name check. Used only for the parse-without-frontmatter path.
    """
    obj = SkillMetadata.__new__(SkillMetadata)
    obj.name = ""
    obj.description = ""
    obj.tags = []
    obj.created_at = ""
    obj.updated_at = ""
    obj.source_session = ""
    obj.version = 1
    return obj


def render_skill(skill: Skill) -> str:
    """Render a Skill back into a SKILL.md string."""
    meta = skill.meta
    lines = ["---"]
    lines.append(f"name: {_yaml_scalar(meta.name)}")
    lines.append(f"description: {_yaml_scalar(meta.description)}")
    lines.append(f"created_at: {_yaml_scalar(meta.created_at)}")
    lines.append(f"updated_at: {_yaml_scalar(meta.updated_at)}")
    if meta.source_session:
        lines.append(f"source_session: {_yaml_scalar(meta.source_session)}")
    lines.append(f"version: {int(meta.version)}")
    if meta.tags:
        lines.append("tags:")
        for tag in meta.tags:
            lines.append(f"  - {_yaml_scalar(tag)}")
    else:
        lines.append("tags: []")
    lines.append("---")
    body = skill.body.rstrip() + "\n"
    return "\n".join(lines) + "\n\n" + body


# ---------------------------------------------------------------------------
# Tiny YAML (subset)
# ---------------------------------------------------------------------------

def _yaml_scalar(value: str) -> str:
    """Quote a string for safe YAML output."""
    if value == "":
        return '""'
    # Quote if it contains characters that YAML treats specially
    if any(c in value for c in [":", "#", "{", "}", "[", "]", ",", "&", "*", "!", "|", ">", "'", '"', "%", "@", "`"]):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _parse_minimal_yaml(text: str) -> Dict[str, Any]:
    """Parse a tiny subset of YAML: maps with string/int/bool/list values.

    Supports:
        key: value
        key: "quoted value"
        key: [a, b, c]
        key:
          - a
          - b
    """
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.strip().startswith("#"):
            i += 1
            continue
        # Only top-level (no leading spaces)
        if line[:1] not in (" ", "\t"):
            key, value, consumed = _parse_kv(line, lines, i)
            if key is not None:
                result[key] = value
                i += consumed
                continue
        i += 1
    return result


def _parse_kv(line: str, lines: List[str], idx: int) -> "tuple[Optional[str], Any, int]":
    stripped = line.strip()
    if ":" not in stripped:
        return None, None, 1
    key, _, rest = stripped.partition(":")
    key = key.strip()
    rest = rest.strip()
    if rest == "":
        # List may follow on subsequent indented lines
        list_items, consumed = _collect_list(lines, idx + 1)
        if list_items is not None:
            return key, list_items, 1 + consumed
        return key, [], 1
    if rest.startswith("[") and rest.endswith("]"):
        inner = rest[1:-1].strip()
        items = [s.strip().strip('"').strip("'") for s in _split_csv(inner) if s.strip()]
        return key, items, 1
    if rest.lower() in ("true", "false"):
        return key, rest.lower() == "true", 1
    try:
        if "." in rest:
            return key, float(rest), 1
        return key, int(rest), 1
    except ValueError:
        pass
    # Strip surrounding quotes if present
    if len(rest) >= 2 and rest[0] == rest[-1] and rest[0] in ('"', "'"):
        return key, rest[1:-1], 1
    return key, rest, 1


def _collect_list(lines: List[str], start: int) -> "tuple[Optional[List[str]], int]":
    items: List[str] = []
    consumed = 0
    saw_item = False
    for j in range(start, len(lines)):
        line = lines[j]
        stripped = line.strip()
        if not stripped:
            consumed += 1
            continue
        if line[:1] in (" ", "\t") and stripped.startswith("- "):
            items.append(stripped[2:].strip().strip('"').strip("'"))
            saw_item = True
            consumed += 1
        elif line[:1] in (" ", "\t") and stripped == "-":
            items.append("")
            saw_item = True
            consumed += 1
        else:
            break
    if not saw_item:
        return None, 0
    return items, consumed


def _split_csv(s: str) -> List[str]:
    out: List[str] = []
    depth = 0
    buf = ""
    in_str: Optional[str] = None
    for ch in s:
        if in_str:
            buf += ch
            if ch == in_str:
                in_str = None
            continue
        if ch in ('"', "'"):
            in_str = ch
            buf += ch
            continue
        if ch in "[{(":
            depth += 1
            buf += ch
            continue
        if ch in "]})":
            depth -= 1
            buf += ch
            continue
        if ch == "," and depth == 0:
            out.append(buf.strip())
            buf = ""
            continue
        buf += ch
    if buf.strip():
        out.append(buf.strip())
    return out
