"""LLM-based session distillation.

After an agent runs, this module asks the LLM to extract *what worked,
what failed, and what to do next time* and writes that as one or more
SKILL.md files into the space. The LLM receives:

  - the session messages (truncated),
  - the outcome label and free-form note,
  - a strict JSON response schema (a list of skills).

The distiller is LLM-agnostic: it uses the existing
:class:`graxia_tool.llm.HybridLLMClient` (or any object with the same
``complete(prompt, system=...)`` async method).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from .schema import Skill, SkillMetadata
from .skill_store import SkillStore


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

SessionMessage = Dict[str, Any]  # {"role": "user"|"assistant"|"tool", "content": "..."}


@dataclass
class DistillResult:
    """Outcome of a distillation run."""

    space: str
    skills: List[Skill] = field(default_factory=list)
    raw_response: str = ""
    errors: List[str] = field(default_factory=list)

    @property
    def saved(self) -> List[SkillMetadata]:
        return [s.meta for s in self.skills]


# ---------------------------------------------------------------------------
# Distiller
# ---------------------------------------------------------------------------

_DISTILL_SYSTEM = (
    "You are a skill curator. Given a session transcript and its outcome, "
    "extract durable, reusable lessons. Each skill should be a short "
    "Markdown body (under 400 words) with a clear, actionable rule, the "
    "context that triggered it, and (if relevant) the failure mode it "
    "prevents. Do not include session-specific noise (timestamps, "
    "transient file paths, names of tools the user happened to be using).\n"
    "Return STRICT JSON of the form: "
    '{"skills": [{"name": "kebab-name", "description": "<= 140 chars", '
    '"tags": ["..."], "body": "markdown body"}]}. '
    "No prose, no fences."
)

_DISTILL_USER_TEMPLATE = (
    "Outcome: {outcome}\n"
    "Outcome note: {outcome_note}\n\n"
    "Session transcript (most recent last, possibly truncated):\n"
    "{transcript}\n\n"
    "Return JSON only."
)


class Distiller:
    """Distill sessions into SKILL.md files.

    Args:
        llm_client: Any object with ``async complete(prompt, system=...)``.
        max_messages: Cap on messages passed to the LLM.
        max_chars_per_message: Truncate long messages.
        store_factory: Optional callable ``(space) -> SkillStore``; if
                       not given, uses :class:`SkillStore` with the
                       default base dir.
    """

    def __init__(
        self,
        llm_client: Any,
        *,
        max_messages: int = 30,
        max_chars_per_message: int = 800,
        store_factory: Optional[Any] = None,
    ) -> None:
        self.llm = llm_client
        self.max_messages = max_messages
        self.max_chars_per_message = max_chars_per_message
        self._store_factory = store_factory or (lambda space: SkillStore(space))

    # --- public ----------------------------------------------------------

    async def distill(
        self,
        space: str,
        session_messages: Sequence[SessionMessage],
        outcome: str = "success",
        outcome_note: str = "",
        *,
        source_session: str = "",
        save: bool = True,
    ) -> DistillResult:
        """Run one distillation pass.

        Args:
            space: Target space (folder name).
            session_messages: List of message dicts.
            outcome: One of "success" | "failure" | "partial".
            outcome_note: Free-form note about the outcome.
            source_session: Optional id of the source session.
            save: If True, persist new skills to disk (default).

        Returns:
            A :class:`DistillResult`. The list of extracted skills is
            populated even when ``save=False`` (so callers can preview).
        """
        transcript = self._format_transcript(session_messages)
        prompt = _DISTILL_USER_TEMPLATE.format(
            outcome=outcome or "unknown",
            outcome_note=(outcome_note or "").strip(),
            transcript=transcript,
        )

        try:
            resp = await self.llm.complete(
                prompt=prompt,
                system=_DISTILL_SYSTEM,
                max_tokens=2000,
                temperature=0.2,
            )
        except Exception as e:
            return DistillResult(
                space=space,
                raw_response="",
                errors=[f"llm call failed: {type(e).__name__}: {e}"],
            )

        raw = getattr(resp, "content", "") or ""
        parsed_skills, errs = _parse_skills_json(raw)
        result = DistillResult(space=space, raw_response=raw, errors=errs)

        for ps in parsed_skills:
            name = _slugify_skill_name(ps.get("name", ""))
            if not name:
                result.errors.append("skipping skill with no usable name")
                continue
            body = (ps.get("body") or "").strip() or ps.get("description", "").strip()
            if not body:
                result.errors.append(f"skipping {name!r}: empty body")
                continue
            description = (ps.get("description") or "").strip()[:280]
            tags = ps.get("tags") or []
            if not isinstance(tags, list):
                tags = [str(tags)]
            tags = [str(t).strip().lower() for t in tags if str(t).strip()]
            meta = SkillMetadata(
                name=name,
                description=description,
                tags=tags,
                source_session=source_session,
            )
            result.skills.append(Skill(meta=meta, body=body))

        if save and result.skills:
            store = self._store_factory(space)
            saved: List[Skill] = []
            for skill in result.skills:
                try:
                    saved.append(store.upsert(
                        name=skill.meta.name,
                        description=skill.meta.description,
                        body=skill.body,
                        tags=skill.meta.tags,
                        source_session=source_session or skill.meta.source_session,
                    ))
                except Exception as e:
                    result.errors.append(
                        f"failed to save {skill.meta.name!r}: {type(e).__name__}: {e}"
                    )
            result.skills = saved

        return result

    # --- helpers ---------------------------------------------------------

    def _format_transcript(self, messages: Sequence[SessionMessage]) -> str:
        if not messages:
            return "(no messages)"
        # Keep the tail (most recent context)
        msgs = list(messages)[-self.max_messages :]
        out: List[str] = []
        for m in msgs:
            role = str(m.get("role", "user"))
            content = m.get("content", "")
            if not isinstance(content, str):
                content = json.dumps(content, default=str)
            content = content.strip()
            if len(content) > self.max_chars_per_message:
                content = content[: self.max_chars_per_message] + "\n... (truncated)"
            out.append(f"[{role}] {content}")
        return "\n\n".join(out)


# ---------------------------------------------------------------------------
# JSON parsing (lenient: handles code-fence-wrapped responses)
# ---------------------------------------------------------------------------

_JSON_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_skills_json(raw: str) -> "tuple[List[Dict[str, Any]], List[str]]":
    """Parse the LLM's JSON response into a list of skill dicts."""
    errs: List[str] = []
    if not raw:
        return [], ["empty LLM response"]
    s = raw.strip()
    # Strip leading/trailing code fences if present
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z0-9]*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    # Find the JSON object
    m = _JSON_OBJ_RE.search(s)
    if not m:
        return [], [f"no JSON object in response: {raw[:200]}"]
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return [], [f"JSON parse error: {e}; head: {raw[:200]}"]
    skills = data.get("skills")
    if not isinstance(skills, list):
        return [], ["response missing 'skills' list"]
    cleaned: List[Dict[str, Any]] = []
    for i, item in enumerate(skills):
        if not isinstance(item, dict):
            errs.append(f"skill[{i}] is not an object")
            continue
        cleaned.append(item)
    return cleaned, errs


def _slugify_skill_name(raw: Any) -> str:
    """Coerce a skill name into a safe, lowercase, hyphenated slug."""
    s = str(raw or "").strip().lower()
    s = re.sub(r"[^a-z0-9._-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    if not s:
        return ""
    if len(s) > 64:
        s = s[:64].rstrip("-")
    return s
