"""Enterprise Agent OS — Evaluation Framework.

Regression tests for agent quality.
Benchmark suite with expected outputs.
Quality metrics tracking.
"""
from __future__ import annotations
import time
import statistics
from datetime import datetime
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from ..core.logging import get_logger

logger = get_logger("eval")


@dataclass
class EvalCase:
    """A single evaluation test case."""
    name: str
    input: str
    expected: Any
    evaluator: Callable[[Any, Any], float]  # returns 0.0-1.0 score
    tags: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    """Result of an evaluation."""
    case_name: str
    score: float
    passed: bool
    duration_ms: int
    input: str
    actual: Any
    expected: Any
    error: Optional[str] = None


@dataclass
class EvalReport:
    """Aggregate eval report."""
    total: int
    passed: int
    failed: int
    pass_rate: float
    avg_score: float
    avg_duration_ms: float
    results: list[EvalResult]
    started_at: datetime
    completed_at: datetime


class EvalRunner:
    """
    Runs evaluations against agents.
    """

    def __init__(self, pass_threshold: float = 0.7):
        self.pass_threshold = pass_threshold
        self.cases: list[EvalCase] = []

    def add_case(
        self,
        name: str,
        input: str,
        expected: Any,
        evaluator: Callable[[Any, Any], float],
        tags: Optional[list[str]] = None,
    ) -> None:
        """Add an evaluation case."""
        self.cases.append(EvalCase(
            name=name,
            input=input,
            expected=expected,
            evaluator=evaluator,
            tags=tags or [],
        ))

    async def run(self, agent_func) -> EvalReport:
        """
        Run all eval cases against an agent function.

        Args:
            agent_func: Async function(input: str) -> output

        Returns:
            EvalReport with all results
        """
        started = datetime.utcnow()
        results = []
        for case in self.cases:
            t0 = time.time()
            try:
                actual = await agent_func(case.input)
                score = case.evaluator(actual, case.expected)
                error = None
            except Exception as e:
                actual = None
                score = 0.0
                error = str(e)
            duration_ms = int((time.time() - t0) * 1000)
            result = EvalResult(
                case_name=case.name,
                score=score,
                passed=score >= self.pass_threshold,
                duration_ms=duration_ms,
                input=case.input,
                actual=actual,
                expected=case.expected,
                error=error,
            )
            results.append(result)
            logger.info(
                "eval_case",
                name=case.name,
                score=score,
                passed=result.passed,
                ms=duration_ms,
            )
        completed = datetime.utcnow()
        passed = sum(1 for r in results if r.passed)
        return EvalReport(
            total=len(results),
            passed=passed,
            failed=len(results) - passed,
            pass_rate=passed / len(results) if results else 0,
            avg_score=statistics.mean([r.score for r in results]) if results else 0,
            avg_duration_ms=statistics.mean([r.duration_ms for r in results]) if results else 0,
            results=results,
            started_at=started,
            completed_at=completed,
        )


# --- Common evaluators ---
def exact_match(actual: Any, expected: Any) -> float:
    """Exact string match."""
    if isinstance(expected, str):
        return 1.0 if str(actual).strip() == expected.strip() else 0.0
    return 1.0 if actual == expected else 0.0


def contains_match(actual: Any, expected: Any) -> float:
    """Check if actual contains expected string."""
    if not expected:
        return 1.0
    return 1.0 if str(expected).lower() in str(actual).lower() else 0.0


def keyword_match(required_keywords: list[str]) -> Callable:
    """Check if output contains required keywords."""
    def evaluator(actual: Any, expected: Any) -> float:
        actual_lower = str(actual).lower()
        hits = sum(1 for kw in required_keywords if kw.lower() in actual_lower)
        return hits / len(required_keywords) if required_keywords else 1.0
    return evaluator


def similarity_match(actual: Any, expected: Any) -> float:
    """Jaccard similarity of words."""
    if not actual or not expected:
        return 0.0
    actual_words = set(str(actual).lower().split())
    expected_words = set(str(expected).lower().split())
    if not expected_words:
        return 0.0
    intersection = actual_words & expected_words
    union = actual_words | expected_words
    return len(intersection) / len(union) if union else 0.0
