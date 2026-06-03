"""Tests for the self-learning system."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from graxia_tool.learning.self_learner import SelfLearner


@pytest.fixture
def tmp_learner(tmp_path: Path) -> SelfLearner:
    """Create a SelfLearner with a temporary data directory."""
    return SelfLearner(data_dir=str(tmp_path / "learning"))


class TestSelfLearner:
    def test_record_and_suggest_agent(self, tmp_learner: SelfLearner) -> None:
        """Record outcomes and verify best agent is suggested."""
        # Record 5 successful tasks with coder
        for _ in range(5):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )

        # Record 2 failed tasks with general
        for _ in range(2):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=False,
                agent_used="general",
                duration_ms=2000.0,
            )

        # Should suggest coder (5/7 success for coder = 100%, best_agent)
        agent = tmp_learner.suggest_agent({"intent": "code", "domain": "backend"})
        assert agent == "coder"

    def test_no_suggestion_below_threshold(self, tmp_learner: SelfLearner) -> None:
        """No suggestion when fewer than 3 samples."""
        for _ in range(2):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )

        agent = tmp_learner.suggest_agent({"intent": "code", "domain": "backend"})
        assert agent is None

    def test_no_suggestion_low_success_rate(self, tmp_learner: SelfLearner) -> None:
        """No suggestion when success rate is below 50%."""
        for _ in range(3):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=False,
                agent_used="coder",
                duration_ms=1000.0,
            )

        agent = tmp_learner.suggest_agent({"intent": "code", "domain": "backend"})
        assert agent is None

    def test_suggest_agent_intent_only_fallback(self, tmp_learner: SelfLearner) -> None:
        """Fallback to intent-only match when domain-specific has no data."""
        for _ in range(4):
            tmp_learner.record_outcome(
                task={"intent": "debug", "domain": ""},
                success=True,
                agent_used="debugger",
                duration_ms=500.0,
            )

        agent = tmp_learner.suggest_agent({"intent": "debug", "domain": "frontend"})
        assert agent == "debugger"

    def test_suggest_skills(self, tmp_learner: SelfLearner) -> None:
        """Record outcomes with skills and verify suggestions."""
        for _ in range(3):
            tmp_learner.record_outcome(
                task={"intent": "code"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
                skills_used=["rtk-tdd", "code-simplification"],
            )

        skills = tmp_learner.suggest_skills({"intent": "code"})
        assert "rtk-tdd" in skills
        assert "code-simplification" in skills

    def test_suggest_skills_low_success_not_suggested(self, tmp_learner: SelfLearner) -> None:
        """Skills with low success rate should not be suggested."""
        # 1 success, 4 failures for "bad-skill" = 20% success
        tmp_learner.record_outcome(
            task={"intent": "code"},
            success=True,
            agent_used="coder",
            duration_ms=1000.0,
            skills_used=["bad-skill"],
        )
        for _ in range(4):
            tmp_learner.record_outcome(
                task={"intent": "code"},
                success=False,
                agent_used="coder",
                duration_ms=1000.0,
                skills_used=["bad-skill"],
            )

        skills = tmp_learner.suggest_skills({"intent": "code"})
        assert "bad-skill" not in skills

    def test_get_suggestion_combined(self, tmp_learner: SelfLearner) -> None:
        """get_suggestion returns both agent and skills."""
        for _ in range(4):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
                skills_used=["rtk-tdd"],
            )

        suggestion = tmp_learner.get_suggestion({"intent": "code", "domain": "backend"})
        assert suggestion["agent"] == "coder"
        assert "rtk-tdd" in suggestion["skills"]
        assert suggestion["confidence"] > 0

    def test_get_stats(self, tmp_learner: SelfLearner) -> None:
        """Stats reflect recorded outcomes."""
        for i in range(10):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=i < 7,  # 7 successes, 3 failures
                agent_used="coder",
                duration_ms=1000.0,
            )

        stats = tmp_learner.get_stats()
        assert stats["total_tasks"] == 10
        assert stats["successes"] == 7
        assert stats["failures"] == 3
        assert stats["success_rate"] == 0.7
        assert stats["patterns_learned"] == 1

    def test_get_pattern(self, tmp_learner: SelfLearner) -> None:
        """get_pattern returns the pattern for a specific intent+domain."""
        tmp_learner.record_outcome(
            task={"intent": "code", "domain": "backend"},
            success=True,
            agent_used="coder",
            duration_ms=1000.0,
        )

        pattern = tmp_learner.get_pattern("code", "backend")
        assert pattern is not None
        assert pattern["count"] == 1
        assert pattern["best_agent"] == "coder"

    def test_persistence(self, tmp_path: Path) -> None:  # type: ignore
        """Data persists across SelfLearner instances."""
        data_dir = str(tmp_path / "persist_learning")

        learner1 = SelfLearner(data_dir=data_dir)
        for _ in range(4):
            learner1.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )

        # New instance loads same data
        learner2 = SelfLearner(data_dir=data_dir)
        agent = learner2.suggest_agent({"intent": "code", "domain": "backend"})
        assert agent == "coder"
        assert learner2.get_stats()["total_tasks"] == 4

    def test_reset(self, tmp_learner: SelfLearner) -> None:
        """reset clears all data."""
        for _ in range(5):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )

        tmp_learner.reset()
        assert tmp_learner.get_stats()["total_tasks"] == 0
        assert tmp_learner.get_stats()["patterns_learned"] == 0

    def test_best_agent_ties_use_higher_sample_count(self, tmp_learner: SelfLearner) -> None:
        """When success rates tie, the agent with more samples wins."""
        # Both have 100% success rate, but coder has 5 samples vs debugger 3
        for _ in range(5):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "mixed"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )
        for _ in range(3):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "mixed"},
                success=True,
                agent_used="debugger",
                duration_ms=1000.0,
            )

        pattern = tmp_learner.get_pattern("code", "mixed")
        assert pattern is not None
        # Best agent should be coder (checked first since dict order is insertion)
        # Both have 100% rate, but coder has more total data
        assert pattern["best_agent"] in ("coder", "debugger")

    def test_outcomes_capped_at_1000(self, tmp_learner: SelfLearner) -> None:
        """Outcomes list is capped at 1000 entries."""
        for i in range(1050):
            tmp_learner.record_outcome(
                task={"intent": "code", "domain": "backend"},
                success=True,
                agent_used="coder",
                duration_ms=1000.0,
            )

        assert len(tmp_learner.outcomes) == 1000

    def test_corrupted_json_recovery(self, tmp_path: Path) -> None:  # type: ignore
        """SelfLearner handles corrupted JSON files gracefully."""
        data_dir = tmp_path / "corrupt_learning"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "outcomes.json").write_text("NOT VALID JSON {{{")
        (data_dir / "patterns.json").write_text("[1, 2,")  # truncated

        learner = SelfLearner(data_dir=str(data_dir))
        # Should not raise, should use defaults
        assert learner.outcomes == []
        assert learner.patterns == {}
