"""Run state store for autonomous mode.

Persists past runs to a small JSON file under ``~/.graxia/autonomous/runs.json``
so the learner can read them back at the end of a run.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class RunStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNED = "replanned"


@dataclass
class StepRecord:
    step_id: int
    tool: str
    args: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    output: Any = None
    error: Optional[str] = None
    duration_s: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "tool": self.tool,
            "args": self.args,
            "success": self.success,
            "output": self.output if not isinstance(self.output, (bytes, bytearray)) else None,
            "error": self.error,
            "duration_s": round(self.duration_s, 3),
        }


@dataclass
class RunRecord:
    run_id: str
    goal: str
    status: RunStatus = RunStatus.PLANNED
    plan_steps: int = 0
    tool_chain: List[str] = field(default_factory=list)
    steps: List[StepRecord] = field(default_factory=list)
    final_output: Any = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    replans: int = 0
    lessons: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def duration_s(self) -> float:
        end = self.finished_at or time.time()
        return max(0.0, end - self.started_at)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "run_id": self.run_id,
            "goal": self.goal,
            "status": self.status.value,
            "plan_steps": self.plan_steps,
            "tool_chain": list(self.tool_chain),
            "steps": [s.to_dict() for s in self.steps],
            "final_output": self.final_output if not isinstance(self.final_output, (bytes, bytearray)) else None,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "replans": self.replans,
            "duration_s": round(self.duration_s(), 2),
            "lessons": list(self.lessons),
            "metadata": dict(self.metadata),
        }
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunRecord":
        rec = cls(
            run_id=d.get("run_id", str(uuid.uuid4())),
            goal=d.get("goal", ""),
            status=RunStatus(d.get("status", "planned")),
            plan_steps=int(d.get("plan_steps", 0)),
            tool_chain=list(d.get("tool_chain", [])),
            final_output=d.get("final_output"),
            error=d.get("error"),
            started_at=float(d.get("started_at", time.time())),
            finished_at=d.get("finished_at"),
            replans=int(d.get("replans", 0)),
            lessons=list(d.get("lessons", [])),
            metadata=dict(d.get("metadata", {})),
        )
        for sd in d.get("steps", []):
            rec.steps.append(StepRecord(
                step_id=int(sd.get("step_id", 0)),
                tool=sd.get("tool", ""),
                args=sd.get("args", {}) or {},
                success=bool(sd.get("success", True)),
                output=sd.get("output"),
                error=sd.get("error"),
                duration_s=float(sd.get("duration_s", 0.0)),
            ))
        return rec


class RunStore:
    """Tiny JSON-backed store for RunRecord objects.

    Stays tiny on purpose: this is meant for *meta-cognition*, not analytics.
    """

    def __init__(self, path: Optional[Path] = None):
        self.path: Path = path or (Path.home() / ".graxia" / "autonomous" / "runs.json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._records: Dict[str, RunRecord] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for r in data.get("runs", []):
                rec = RunRecord.from_dict(r)
                self._records[rec.run_id] = rec
        except (OSError, json.JSONDecodeError):
            self._records = {}

    def _flush(self) -> None:
        data = {"runs": [r.to_dict() for r in self._records.values()]}
        self.path.write_text(
            json.dumps(data, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- CRUD ----

    def upsert(self, record: RunRecord) -> None:
        self._records[record.run_id] = record
        self._flush()

    def get(self, run_id: str) -> Optional[RunRecord]:
        return self._records.get(run_id)

    def list(self, limit: int = 10) -> List[RunRecord]:
        recs = sorted(
            self._records.values(),
            key=lambda r: r.started_at,
            reverse=True,
        )
        return recs[:limit]

    def clear(self) -> None:
        self._records = {}
        self._flush()
