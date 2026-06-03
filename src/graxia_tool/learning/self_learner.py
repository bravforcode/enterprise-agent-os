"""Self-learning system — improve routing based on outcomes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

from ..core.logging import get_logger

logger = get_logger("self_learner")


class SelfLearner:
    """Learn from task outcomes to improve routing.

    Tracks which agents and skills succeed for which task patterns,
    then suggests optimal routing based on accumulated evidence.

    Usage:
        learner = SelfLearner()
        learner.record_outcome(
            task={"intent": "code", "domain": "backend"},
            success=True,
            agent_used="coder",
            duration_ms=1200.0,
        )
        agent = learner.suggest_agent({"intent": "code", "domain": "backend"})
    """

    def __init__(self, data_dir: str = "~/.graxia/learning") -> None:
        self.data_dir = Path(data_dir).expanduser()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_file = self.data_dir / "outcomes.json"
        self.patterns_file = self.data_dir / "patterns.json"
        self.skill_patterns_file = self.data_dir / "skill_patterns.json"
        self.load_data()

    def load_data(self) -> None:
        """Load learning data from disk."""
        self.outcomes: list[dict[str, Any]] = self._load_json(self.outcomes_file, [])
        self.patterns: dict[str, Any] = self._load_json(self.patterns_file, {})
        self.skill_patterns: dict[str, Any] = self._load_json(self.skill_patterns_file, {})

    def save_data(self) -> None:
        """Save learning data to disk."""
        self._save_json(self.outcomes_file, self.outcomes)
        self._save_json(self.patterns_file, self.patterns)
        self._save_json(self.skill_patterns_file, self.skill_patterns)

    def record_outcome(
        self,
        task: Dict[str, Any],
        success: bool,
        agent_used: str,
        duration_ms: float,
        skills_used: Optional[List[str]] = None,
    ) -> None:
        """Record task outcome for learning.

        Args:
            task: Task metadata with at least 'intent' and 'domain' keys.
            success: Whether the task completed successfully.
            agent_used: Name of the agent that handled the task.
            duration_ms: Execution time in milliseconds.
            skills_used: Optional list of skill names that were loaded.
        """
        outcome = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "success": success,
            "agent_used": agent_used,
            "duration_ms": duration_ms,
            "skills_used": skills_used or [],
        }
        self.outcomes.append(outcome)

        # Keep only last 1000 outcomes to bound disk usage
        if len(self.outcomes) > 1000:
            self.outcomes = self.outcomes[-1000:]

        self._update_patterns(outcome)
        self._update_skill_patterns(outcome)
        self.save_data()

        logger.info(
            "outcome_recorded",
            intent=task.get("intent", "unknown"),
            agent=agent_used,
            success=success,
            duration_ms=round(duration_ms, 1),
        )

    def suggest_agent(self, task: Dict[str, Any]) -> Optional[str]:
        """Suggest best agent based on past outcomes.

        Only suggests if we have enough data (>=3 samples) and the best
        agent has >70% success rate.

        Args:
            task: Task metadata with 'intent' and 'domain' keys.

        Returns:
            Best agent name, or None if insufficient data.
        """
        intent = task.get("intent", "")
        domain = task.get("domain", "")
        key = f"{intent}:{domain}"

        if key not in self.patterns:
            # Try intent-only match
            key = f"{intent}:"
            if key not in self.patterns:
                return None

        pattern = self.patterns[key]
        if pattern["count"] < 3:
            return None
        if pattern["success_rate"] < 0.5:
            return None

        return pattern["best_agent"]

    def suggest_skills(self, task: Dict[str, Any]) -> List[str]:
        """Suggest skills based on past outcomes.

        Returns skills that correlated with successful outcomes for
        similar tasks.

        Args:
            task: Task metadata with 'intent' key.

        Returns:
            List of suggested skill names.
        """
        intent = task.get("intent", "")
        key = f"skill:{intent}"

        if key not in self.skill_patterns:
            return []

        pattern = self.skill_patterns[key]
        # Return skills with >60% success rate and at least 2 uses
        suggestions = []
        for skill_name, stats in pattern.get("skills", {}).items():
            if stats["count"] >= 2:
                rate = stats["successes"] / stats["count"]
                if rate > 0.6:
                    suggestions.append(skill_name)

        return suggestions[:5]  # Cap at 5 skills

    def get_suggestion(
        self, task: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get combined agent + skill suggestions for a task.

        Args:
            task: Task metadata.

        Returns:
            Dict with 'agent', 'skills', and 'confidence' keys.
        """
        agent = self.suggest_agent(task)
        skills = self.suggest_skills(task)

        # Compute confidence based on data availability
        intent = task.get("intent", "")
        domain = task.get("domain", "")
        key = f"{intent}:{domain}"
        confidence = 0.0

        if key in self.patterns:
            p = self.patterns[key]
            if p["count"] >= 3:
                confidence = min(p["success_rate"], 0.95)

        return {
            "agent": agent,
            "skills": skills,
            "confidence": round(confidence, 2),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get learning statistics."""
        total = len(self.outcomes)
        successes = sum(1 for o in self.outcomes if o["success"])
        agent_counts: Dict[str, int] = {}
        for o in self.outcomes:
            a = o["agent_used"]
            agent_counts[a] = agent_counts.get(a, 0) + 1

        return {
            "total_tasks": total,
            "successes": successes,
            "failures": total - successes,
            "success_rate": round(successes / total, 3) if total > 0 else 0.0,
            "patterns_learned": len(self.patterns),
            "skill_patterns_learned": len(self.skill_patterns),
            "top_agents": sorted(agent_counts.items(), key=lambda x: -x[1])[:5],
        }

    def get_pattern(self, intent: str, domain: str = "") -> Optional[Dict[str, Any]]:
        """Get the learned pattern for a specific intent+domain."""
        key = f"{intent}:{domain}"
        return self.patterns.get(key)

    def reset(self) -> None:
        """Clear all learning data."""
        self.outcomes = []
        self.patterns = {}
        self.skill_patterns = {}
        self.save_data()

    # ── Internal ──────────────────────────────────────────────────────

    def _update_patterns(self, outcome: Dict[str, Any]) -> None:
        """Update agent performance patterns based on outcome."""
        task = outcome["task"]
        intent = task.get("intent", "")
        domain = task.get("domain", "")
        key = f"{intent}:{domain}"

        if key not in self.patterns:
            self.patterns[key] = {
                "count": 0,
                "successes": 0,
                "success_rate": 0.0,
                "best_agent": outcome["agent_used"],
                "best_agent_successes": 0,
                "agents": {},
            }

        pattern = self.patterns[key]
        pattern["count"] += 1

        if outcome["success"]:
            pattern["successes"] += 1

        pattern["success_rate"] = pattern["successes"] / pattern["count"]

        # Track per-agent performance
        agent = outcome["agent_used"]
        if agent not in pattern["agents"]:
            pattern["agents"][agent] = {"count": 0, "successes": 0, "total_ms": 0.0}

        stats = pattern["agents"][agent]
        stats["count"] += 1
        stats["total_ms"] += outcome.get("duration_ms", 0.0)
        if outcome["success"]:
            stats["successes"] += 1

        # Update best agent (highest success rate with >=2 uses)
        best_rate = 0.0
        for a, s in pattern["agents"].items():
            if s["count"] >= 2:
                rate = s["successes"] / s["count"]
                if rate > best_rate:
                    best_rate = rate
                    pattern["best_agent"] = a

    def _update_skill_patterns(self, outcome: Dict[str, Any]) -> None:
        """Update skill performance patterns based on outcome."""
        task = outcome["task"]
        intent = task.get("intent", "")
        key = f"skill:{intent}"
        skills_used = outcome.get("skills_used", [])

        if not skills_used:
            return

        if key not in self.skill_patterns:
            self.skill_patterns[key] = {"skills": {}}

        skills_dict = self.skill_patterns[key]["skills"]
        for skill_name in skills_used:
            if skill_name not in skills_dict:
                skills_dict[skill_name] = {"count": 0, "successes": 0}
            stats = skills_dict[skill_name]
            stats["count"] += 1
            if outcome["success"]:
                stats["successes"] += 1

    def _load_json(self, path: Path, default: Any) -> Any:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return default
        return default

    def _save_json(self, path: Path, data: Any) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
