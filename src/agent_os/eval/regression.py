"""Regression test harness for continuous quality monitoring.

Run golden datasets against the agent to detect regressions.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Awaitable

from .framework import EvalRunner, EvalReport, EvalCase
from .datasets import ALL_DATASETS, GoldenDataset, get_dataset, list_datasets, get_total_case_count


@dataclass
class RegressionResult:
    """Result of a regression test run."""
    dataset_name: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    failed_cases: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RegressionReport:
    """Overall regression test report."""
    total_datasets: int
    total_cases: int
    total_passed: int
    total_failed: int
    overall_pass_rate: float
    duration_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    dataset_results: list[RegressionResult] = field(default_factory=list)
    regressions: list[dict[str, Any]] = field(default_factory=list)


class RegressionHarness:
    """Runs golden datasets for regression testing.

    Usage:
        async def my_agent(input_text):
            return some_llm_call(input_text)

        harness = RegressionHarness()
        report = await harness.run(my_agent, datasets=["code_generation", "qa"])
    """

    def __init__(self, output_dir: str = "./eval_results", pass_threshold: float = 0.7):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.pass_threshold = pass_threshold

    async def run(
        self,
        agent_func: Callable[[str], Awaitable[str]],
        datasets: list[str] | None = None,
        save_report: bool = True,
    ) -> RegressionReport:
        """Run regression tests against specified datasets.

        Args:
            agent_func: Async function that takes input and returns output
            datasets: List of dataset names. If None, runs all.
            save_report: Whether to save report to disk
        """
        start = time.time()
        if datasets is None:
            datasets = list_datasets()

        dataset_results: list[RegressionResult] = []
        total_cases = 0
        total_passed = 0
        total_failed = 0

        for ds_name in datasets:
            ds = get_dataset(ds_name)
            ds_result = await self._run_dataset(ds, agent_func)
            dataset_results.append(ds_result)
            total_cases += ds_result.total
            total_passed += ds_result.passed
            total_failed += ds_result.failed

        # Detect regressions (failures)
        regressions = [
            {
                "dataset": r.dataset_name,
                "case_id": fc["case_id"],
                "input": fc.get("input", ""),
                "expected": fc.get("expected", ""),
                "actual": fc.get("actual", ""),
            }
            for r in dataset_results
            for fc in r.failed_cases
        ]

        report = RegressionReport(
            total_datasets=len(dataset_results),
            total_cases=total_cases,
            total_passed=total_passed,
            total_failed=total_failed,
            overall_pass_rate=total_passed / total_cases if total_cases > 0 else 0.0,
            duration_ms=(time.time() - start) * 1000,
            dataset_results=dataset_results,
            regressions=regressions,
        )

        if save_report:
            self._save_report(report)

        return report

    async def _run_dataset(
        self,
        dataset: GoldenDataset,
        agent_func: Callable[[str], Awaitable[str]],
    ) -> RegressionResult:
        """Run a single dataset."""
        start = time.time()
        runner = EvalRunner(pass_threshold=self.pass_threshold)
        for case in dataset.cases:
            runner.add_case(case.name, case.input, case.expected, evaluator=case.evaluator)
        report: EvalReport = await runner.run(agent_func)
        duration = (time.time() - start) * 1000

        failed_cases = [
            {
                "case_id": case.name,
                "input": case.input,
                "expected": case.expected,
                "actual": str(result.actual),
                "tags": case.tags,
            }
            for case, result in zip(dataset.cases, report.results)
            if not result.passed
        ]

        return RegressionResult(
            dataset_name=dataset.name,
            total=report.total,
            passed=report.passed,
            failed=report.failed,
            pass_rate=report.pass_rate,
            duration_ms=duration,
            failed_cases=failed_cases,
        )

    def _save_report(self, report: RegressionReport) -> None:
        """Save report to JSON file."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = self.output_dir / f"regression_{timestamp}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(asdict(report), f, indent=2, default=str)

    def print_report(self, report: RegressionReport) -> str:
        """Format report as a human-readable string."""
        lines = [
            "=" * 60,
            "AGENT OS REGRESSION TEST REPORT",
            "=" * 60,
            f"Timestamp: {report.timestamp.isoformat()}",
            f"Duration: {report.duration_ms:.1f}ms",
            f"Datasets: {report.total_datasets}",
            f"Total Cases: {report.total_cases}",
            f"Passed: {report.total_passed}",
            f"Failed: {report.total_failed}",
            f"Pass Rate: {report.overall_pass_rate:.1%}",
            "",
            "Per-Dataset Results:",
            "-" * 60,
        ]
        for ds in report.dataset_results:
            status = "PASS" if ds.pass_rate >= self.pass_threshold else "FAIL"
            lines.append(
                f"  [{status}] {ds.dataset_name}: "
                f"{ds.passed}/{ds.total} ({ds.pass_rate:.1%}) in {ds.duration_ms:.0f}ms"
            )

        if report.regressions:
            lines.append("")
            lines.append(f"Regressions ({len(report.regressions)}):")
            lines.append("-" * 60)
            for reg in report.regressions[:10]:  # Show first 10
                lines.append(f"  - [{reg['dataset']}] {reg['case_id']}")
                lines.append(f"    Input: {reg['input'][:80]}")
                lines.append(f"    Expected: {reg['expected'][:80]}")
                lines.append(f"    Actual:   {reg['actual'][:80]}")
            if len(report.regressions) > 10:
                lines.append(f"  ... and {len(report.regressions) - 10} more")

        lines.append("=" * 60)
        return "\n".join(lines)


# CLI entry point
async def _cli_main() -> None:
    """CLI: python -m agent_os.eval.regression <dataset_name>"""
    import sys
    from agent_os.agents.implementations import Coder, Conversational, General

    if len(sys.argv) < 2:
        print("Usage: python -m agent_os.eval.regression <dataset_name>")
        print(f"Available: {', '.join(list_datasets())}")
        sys.exit(1)

    dataset_name = sys.argv[1]

    async def eval_agent(input_text: str) -> str:
        agent = General()
        result = await agent.run(input_text)
        return str(result.output) if result.output else ""

    harness = RegressionHarness()
    report = await harness.run(eval_agent, datasets=[dataset_name])
    print(harness.print_report(report))
    sys.exit(0 if report.overall_pass_rate >= harness.pass_threshold else 1)


if __name__ == "__main__":
    asyncio.run(_cli_main())
