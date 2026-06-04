"""Self-improvement loop: distill lessons from a run and update ANUS.md.

After each autonomous run, the learner:
    1. inspects the run record (steps, success/failure, tool chain)
    2. asks the LLM "what should we add to ANUS.md so we do better next time?"
    3. appends the answers to the project context's `learnings:` list
    4. writes ANUS.md back to disk

The learner can run *without* an LLM (it produces generic, conservative
lessons in that case) so the rest of the system stays usable offline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..llm import LLMClient
from .context import ANUSContext, ANUSProject, HistoryEntry
from .store import RunRecord, RunStatus


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class Lesson:
    text: str
    applied: bool = True
    source: str = "autonomous"
    confidence: float = 0.7

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "applied": self.applied,
                "source": self.source, "confidence": self.confidence}


class SelfLearner:
    """Generate and persist lessons from autonomous runs."""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    # -- public --------------------------------------------------------

    async def distill(
        self,
        record: RunRecord,
        max_lessons: int = 3,
    ) -> List[Lesson]:
        """Return a short list of Lesson objects distilled from this run."""
        if self.llm is not None:
            try:
                lessons = await self._llm_distill(record, max_lessons)
                if lessons:
                    return lessons
            except Exception:
                pass
        return _heuristic_distill(record, max_lessons)

    async def apply(
        self,
        record: RunRecord,
        project: ANUSProject,
        context: ANUSContext,
        project_path: Optional[str] = None,
        max_lessons: int = 3,
    ) -> List[Lesson]:
        """Distill lessons, append them to ``project``, save ANUS.md, return them.

        ``project_path`` is forwarded to :meth:`ANUSContext.save` so the file
        is written next to the user's project rather than to the global
        fallback location.
        """
        lessons = await self.distill(record, max_lessons=max_lessons)
        for les in lessons:
            context.append_learning(
                project,
                lesson=les.text,
                applied=les.applied,
                source=les.source,
            )
        # also append a short history entry
        context.append_history(project, HistoryEntry(
            run_id=record.run_id,
            query=record.goal,
            plan_steps=record.plan_steps,
            success=record.status == RunStatus.COMPLETED,
            duration_s=record.duration_s(),
        ))
        context.save(project, project_path=project_path)
        record.lessons = [l.text for l in lessons]
        return lessons

    # -- internals -----------------------------------------------------

    async def _llm_distill(self, record: RunRecord, max_lessons: int) -> List[Lesson]:
        if self.llm is None:
            return []
        # Build a compact trace for the LLM
        trace_lines = []
        for s in record.steps:
            ok = "OK" if s.success else "FAIL"
            out = (str(s.output or "")[:80] if s.output else str(s.error or ""))
            trace_lines.append(f"{s.step_id}. {s.tool} -> {ok}: {out}")
        prompt = f"""You are a self-reflective agent. The following autonomous run just finished.

GOAL: {record.goal}
STATUS: {record.status.value}
TOOL CHAIN: {' -> '.join(record.tool_chain) or '(none)'}
DURATION: {record.duration_s():.1f}s
REPLANS: {record.replans}

TRACE:
{chr(10).join(trace_lines) or '(no steps)'}

Produce at most {max_lessons} short, generalizable lessons that would help
the next run be faster, more reliable, or cheaper. Reply with a JSON array
of objects: [{{"text": "...", "applied": <bool>, "confidence": <0.0-1.0>}}].

Reply with ONLY the JSON array, no markdown, no commentary."""

        resp = await self.llm.complete(
            prompt=prompt,
            system="You are a precise self-reflection engine. Respond with JSON only.",
            max_tokens=500, temperature=0.3,
        )
        items = _parse_lesson_array(resp.content or "")
        out: List[Lesson] = []
        for it in items[:max_lessons]:
            txt = str(it.get("text", "")).strip()
            if not txt:
                continue
            out.append(Lesson(
                text=txt[:280],
                applied=bool(it.get("applied", True)),
                source="llm",
                confidence=float(it.get("confidence", 0.7)),
            ))
        return out


# ---------------------------------------------------------------------------
# Heuristic fallback lessons
# ---------------------------------------------------------------------------

def _heuristic_distill(record: RunRecord, max_lessons: int) -> List[Lesson]:
    """Cheap, conservative lessons that don't need an LLM."""
    out: List[Lesson] = []
    if not record.steps:
        out.append(Lesson(
            text=f"Planner returned no steps for goal: {record.goal[:60]!r}",
            applied=False, source="heuristic", confidence=0.6,
        ))
        return out
    failed = [s for s in record.steps if not s.success]
    if failed and record.replans >= 1:
        tools = sorted({s.tool for s in failed})
        out.append(Lesson(
            text=(
                f"Tool(s) {', '.join(tools)} failed on goal type "
                f"{_bucket_goal(record.goal)!r}; consider a fallback tool or "
                "preflight check."
            ),
            applied=False, source="heuristic", confidence=0.7,
        ))
    if record.replans > 0:
        out.append(Lesson(
            text=(
                f"Required {record.replans} replan(s) for goal "
                f"{_bucket_goal(record.goal)!r}; pre-conditions are too strict."
            ),
            applied=False, source="heuristic", confidence=0.6,
        ))
    if record.status == RunStatus.COMPLETED and len(record.tool_chain) > 0:
        first = record.tool_chain[0]
        out.append(Lesson(
            text=(
                f"Goal type {_bucket_goal(record.goal)!r} is well-served by "
                f"starting with tool {first!r}."
            ),
            applied=True, source="heuristic", confidence=0.6,
        ))
    return out[:max_lessons]


def _bucket_goal(goal: str) -> str:
    """Coarse goal category used for heuristic lessons."""
    g = goal.lower()
    if any(k in g for k in ("search", "find", "lookup", "look up")):
        return "search"
    if any(k in g for k in ("code", "implement", "fix", "debug", "build")):
        return "code"
    if any(k in g for k in ("analyze", "summarize", "summary", "report")):
        return "analysis"
    if any(k in g for k in ("plan", "schedule", "organize")):
        return "planning"
    return "general"


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def _parse_lesson_array(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return [x for x in obj if isinstance(x, dict)]
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, list):
                return [x for x in obj if isinstance(x, dict)]
        except json.JSONDecodeError:
            pass
    return []
