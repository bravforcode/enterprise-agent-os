"""ANUS.md context loader and saver.

ANUS.md is a markdown file with YAML frontmatter that the agent reads at
session start. It encodes:
  - the project the agent is working on
  - the goals the user is trying to reach
  - hard constraints (things the agent must not violate)
  - soft preferences (language, style, ...)
  - cumulative learnings (the agent's evolving self-knowledge)
  - a short history of past autonomous runs

The schema is intentionally simple: a single markdown file, hand-editable,
diff-friendly. The agent is the primary producer; the user can override.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


DEFAULT_ANUS_FILENAME = "ANUS.md"


def default_context_path() -> Path:
    """Fallback location: ``~/.graxia/autonomous/ANUS.md``."""
    return Path.home() / ".graxia" / "autonomous" / DEFAULT_ANUS_FILENAME


def _resolve(project_path: Optional[str]) -> Path:
    """Resolve where the ANUS.md for a given project should live.

    Priority:
        1. ``{project_path}/ANUS.md`` if the path is non-empty (we'll
           create parent dirs on save).
        2. ``~/.graxia/autonomous/ANUS.md`` fallback (always works).
    """
    if project_path:
        return Path(project_path) / DEFAULT_ANUS_FILENAME
    return default_context_path()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Learning:
    """A single lesson learned by the agent."""
    date: str
    lesson: str
    applied: bool = False
    source: str = "autonomous"

    def to_dict(self) -> Dict[str, Any]:
        return {"date": self.date, "lesson": self.lesson,
                "applied": self.applied, "source": self.source}


@dataclass
class HistoryEntry:
    """A short record of a past autonomous run."""
    run_id: str
    query: str
    plan_steps: int = 0
    success: bool = True
    duration_s: float = 0.0
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "query": self.query,
            "plan_steps": self.plan_steps,
            "success": self.success,
            "duration_s": round(self.duration_s, 2),
            "timestamp": self.timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }


@dataclass
class ANUSProject:
    """In-memory representation of an ANUS.md file."""
    project: str = "default"
    goals: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    learnings: List[Learning] = field(default_factory=list)
    history: List[HistoryEntry] = field(default_factory=list)
    notes: str = ""

    # ---- helpers ----
    def recent_learnings(self, limit: int = 5) -> List[Learning]:
        return list(self.learnings[-limit:])

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "goals": list(self.goals),
            "constraints": list(self.constraints),
            "preferences": dict(self.preferences),
            "learnings": [l.to_dict() for l in self.learnings],
            "history": [h.to_dict() for h in self.history],
        }


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)


def _split_frontmatter(text: str):
    """Return (frontmatter_dict_or_None, body_str)."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = None
    return fm, m.group(2).strip()


def _dump_frontmatter(meta: Dict[str, Any], body: str) -> str:
    """Serialize a frontmatter dict + body into a single markdown string."""
    fm_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{fm_text}\n---\n\n{body.strip()}\n"


def _project_from_meta(meta: Dict[str, Any], body: str) -> ANUSProject:
    p = ANUSProject()
    if not meta:
        return ANUSProject(notes=body)
    p.project = str(meta.get("project", "default"))
    p.goals = [str(g) for g in (meta.get("goals") or [])]
    p.constraints = [str(c) for c in (meta.get("constraints") or [])]
    p.preferences = dict(meta.get("preferences") or {})
    p.learnings = [
        Learning(
            date=str(l.get("date", "")),
            lesson=str(l.get("lesson", "")),
            applied=bool(l.get("applied", False)),
            source=str(l.get("source", "autonomous")),
        )
        for l in (meta.get("learnings") or [])
        if isinstance(l, dict) and l.get("lesson")
    ]
    p.history = [
        HistoryEntry(
            run_id=str(h.get("run_id", "")),
            query=str(h.get("query", "")),
            plan_steps=int(h.get("plan_steps", 0)),
            success=bool(h.get("success", True)),
            duration_s=float(h.get("duration_s", 0.0)),
            timestamp=str(h.get("timestamp", "")),
        )
        for h in (meta.get("history") or [])
        if isinstance(h, dict) and h.get("run_id")
    ]
    p.notes = body
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ANUSContext:
    """Read/write the ANUS.md for a project.

    Usage::

        ctx = ANUSContext()
        project = ctx.load()                      # auto-resolves path
        project = ctx.load("/path/to/project")    # explicit project root
        ctx.save(project)
        ctx.append_learning(project, "...")
        ctx.append_history(project, RunRecord(...))
    """

    def __init__(self, project_path: Optional[str] = None):
        self._explicit_path: Optional[Path] = (
            Path(project_path) / DEFAULT_ANUS_FILENAME
            if project_path
            else None
        )

    # -- path --

    def path_for(self, project_path: Optional[str] = None) -> Path:
        if self._explicit_path is not None:
            return self._explicit_path
        return _resolve(project_path)

    # -- load / save --

    def load(self, project_path: Optional[str] = None) -> ANUSProject:
        path = self.path_for(project_path)
        if not path.exists():
            return ANUSProject(notes="")
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return ANUSProject(notes="")
        meta, body = _split_frontmatter(text)
        if meta is None:
            return ANUSProject(notes=text)
        return _project_from_meta(meta, body)

    def save(
        self,
        project: ANUSProject,
        project_path: Optional[str] = None,
    ) -> Path:
        path = self.path_for(project_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "project": project.project,
            "goals": list(project.goals),
            "constraints": list(project.constraints),
            "preferences": dict(project.preferences),
            "learnings": [l.to_dict() for l in project.learnings],
            "history": [h.to_dict() for h in project.history],
        }
        body = project.notes or _render_notes(project)
        path.write_text(_dump_frontmatter(meta, body), encoding="utf-8")
        return path

    def exists(self, project_path: Optional[str] = None) -> bool:
        return self.path_for(project_path).exists()

    # -- mutations --

    def append_learning(
        self,
        project: ANUSProject,
        lesson: str,
        applied: bool = True,
        source: str = "autonomous",
        date: Optional[str] = None,
    ) -> Learning:
        entry = Learning(
            date=date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            lesson=lesson.strip(),
            applied=applied,
            source=source,
        )
        if entry.lesson:
            project.learnings.append(entry)
        return entry

    def append_history(self, project: ANUSProject, entry: HistoryEntry) -> None:
        project.history.append(entry)
        # cap history at last 50 entries to keep the file small
        if len(project.history) > 50:
            project.history = project.history[-50:]

    def upsert_goal(self, project: ANUSProject, goal: str) -> None:
        goal = goal.strip()
        if goal and goal not in project.goals:
            project.goals.append(goal)

    def upsert_constraint(self, project: ANUSProject, constraint: str) -> None:
        constraint = constraint.strip()
        if constraint and constraint not in project.constraints:
            project.constraints.append(constraint)

    def set_preference(self, project: ANUSProject, key: str, value: Any) -> None:
        if key:
            project.preferences[key] = value


def _render_notes(project: ANUSProject) -> str:
    """Render the free-form notes section (markdown body)."""
    lines = [
        f"# {project.project}",
        "",
        "Free-form project notes go here. The agent appends learnings to the",
        "frontmatter `learnings:` list; this body is for human-authored context.",
        "",
        "## Preferences",
    ]
    for k, v in (project.preferences or {}).items():
        lines.append(f"- **{k}**: {v}")
    if not project.preferences:
        lines.append("- (none yet)")
    return "\n".join(lines) + "\n"
