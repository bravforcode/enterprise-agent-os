"""Enterprise Agent OS — Phase 9-14 tests."""
import pytest
import asyncio
import json
from pathlib import Path
from datetime import datetime

from agent_os.optimization import (
    CostOptimizer,
    OptimizationConfig,
    BatchProcessor,
    TokenBudgetManager,
)
from agent_os.eval.datasets import (
    ALL_DATASETS,
    CODE_GENERATION,
    QA,
    REASONING,
    SUMMARIZATION,
    TRANSLATION,
    get_dataset,
    list_datasets,
    get_total_case_count,
)
from agent_os.eval.regression import (
    RegressionHarness,
    RegressionResult,
    RegressionReport,
)
from agent_os.pipeline import (
    EndToEndPipeline,
    PipelineRequest,
    PipelineResponse,
)
from agent_os.observability.prometheus import (
    record_run,
    record_agent,
    record_pattern,
    record_cache,
    record_compression,
    record_memory,
    record_rag,
    record_policy,
    record_eval,
    record_guardrail,
    get_metrics,
)


# --- Cost Optimization Tests ---
class TestCostOptimizer:
    @pytest.mark.asyncio
    async def test_cache_hit(self):
        config = OptimizationConfig(enable_smart_cache=True, enable_request_dedup=False)
        optimizer = CostOptimizer(config=config)

        # Mock cache with async interface
        class MockCache:
            def __init__(self):
                self.store = {}
            async def get(self, key):
                return self.store.get(key)
            async def set(self, key, val, ttl=None):
                self.store[key] = val

        optimizer.prompt_cache = MockCache()
        call_count = 0

        async def llm(model, prompt):
            nonlocal call_count
            call_count += 1
            return f"response-{call_count}"

        # First call - should hit LLM
        r1, _ = await optimizer.optimize_call("hello", llm)
        assert r1 == "response-1"
        # Second call - should hit cache
        r2, meta = await optimizer.optimize_call("hello", llm)
        assert r2 == "response-1"
        assert meta["cache_hit"]

    @pytest.mark.asyncio
    async def test_dedup(self):
        config = OptimizationConfig(enable_smart_cache=False, enable_request_dedup=True)
        optimizer = CostOptimizer(config=config)
        call_count = 0

        async def slow_llm(model, prompt):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return f"r-{call_count}"

        # Submit 2 identical calls concurrently
        results = await asyncio.gather(
            optimizer.optimize_call("same prompt", slow_llm),
            optimizer.optimize_call("same prompt", slow_llm),
        )
        # At least one should be a dedup
        assert optimizer.savings.deduped_requests >= 1

    @pytest.mark.asyncio
    async def test_model_downgrade(self):
        config = OptimizationConfig(
            enable_smart_cache=False,
            enable_request_dedup=False,
            enable_model_downgrade=True,
            enable_compression=False,
        )
        optimizer = CostOptimizer(config=config)

        async def llm(model, prompt):
            return f"model-{model}"

        # Short prompt → should downgrade to haiku
        _, meta = await optimizer.optimize_call("hi", llm)
        assert meta["model_used"] == "haiku"
        assert "model_downgrade" in meta["optimizations"]


class TestBatchProcessor:
    @pytest.mark.asyncio
    async def test_batch_flush(self):
        processor = BatchProcessor(batch_size=3, batch_timeout_ms=50)

        async def batch_fn(items):
            return [f"out-{i}" for i in items]

        results = await asyncio.gather(
            processor.submit("a", batch_fn),
            processor.submit("b", batch_fn),
            processor.submit("c", batch_fn),
        )
        assert all(r.startswith("out-") for r in results)


class TestTokenBudgetManager:
    def test_set_and_check(self):
        mgr = TokenBudgetManager()
        mgr.set_budget("user-1", daily_limit=1000, per_request_limit=500)
        assert mgr.can_user_spend("user-1", 500)
        assert not mgr.can_user_spend("user-1", 1500)
        assert mgr.record_spend("user-1", 500)
        assert not mgr.record_spend("user-1", 600)

    def test_usage_pct(self):
        mgr = TokenBudgetManager()
        mgr.set_budget("user-1", daily_limit=1000)
        mgr.record_spend("user-1", 500)
        assert mgr.get_usage("user-1")["usage_pct"] == 0.5


# --- Eval Datasets Tests ---
class TestEvalDatasets:
    def test_all_datasets_loaded(self):
        assert len(ALL_DATASETS) == 5
        assert "code_generation" in ALL_DATASETS
        assert "qa" in ALL_DATASETS
        assert "reasoning" in ALL_DATASETS
        assert "summarization" in ALL_DATASETS
        assert "translation" in ALL_DATASETS

    def test_get_dataset(self):
        ds = get_dataset("qa")
        assert ds.name == "qa"
        assert len(ds.cases) > 0

    def test_list_datasets(self):
        names = list_datasets()
        assert "code_generation" in names

    def test_total_cases(self):
        total = get_total_case_count()
        assert total >= 15  # we have at least 15+ cases

    def test_dataset_has_required_fields(self):
        for ds in ALL_DATASETS.values():
            for case in ds.cases:
                assert case.input
                assert case.expected
                assert case.evaluator
                assert case.name
                assert len(case.tags) > 0


# --- Regression Harness Tests ---
class TestRegressionHarness:
    @pytest.mark.asyncio
    async def test_run_single_dataset(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            async def perfect_agent(input_text):
                return input_text

            harness = RegressionHarness(output_dir=tmp_dir, pass_threshold=0.5)
            report = await harness.run(perfect_agent, datasets=["qa"], save_report=False)
            assert report.total_datasets == 1
            assert report.total_cases > 0
            assert report.overall_pass_rate >= 0.0

    @pytest.mark.asyncio
    async def test_run_with_failures(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            async def failing_agent(input_text):
                return "WRONG"

            harness = RegressionHarness(output_dir=tmp_dir, pass_threshold=0.99)
            report = await harness.run(failing_agent, datasets=["qa"], save_report=False)
            assert report.total_failed > 0

    @pytest.mark.asyncio
    async def test_save_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            async def agent(input_text):
                return "answer"

            harness = RegressionHarness(output_dir=tmp_dir)
            report = await harness.run(agent, datasets=["qa"], save_report=True)
            from pathlib import Path
            files = list(Path(tmp_dir).glob("regression_*.json"))
            assert len(files) == 1

    def test_print_report(self):
        harness = RegressionHarness()
        report = RegressionReport(
            total_datasets=1,
            total_cases=10,
            total_passed=8,
            total_failed=2,
            overall_pass_rate=0.8,
            duration_ms=100.0,
            dataset_results=[
                RegressionResult(
                    dataset_name="qa",
                    total=10,
                    passed=8,
                    failed=2,
                    pass_rate=0.8,
                    duration_ms=50.0,
                )
            ],
        )
        text = harness.print_report(report)
        assert "AGENT OS REGRESSION TEST REPORT" in text
        assert "qa" in text
        assert "80.0%" in text


# --- End-to-End Pipeline Tests ---
class TestPipeline:
    @pytest.mark.asyncio
    async def test_basic_pipeline(self):
        pipeline = EndToEndPipeline()
        request = PipelineRequest(input="write a python function to add two numbers")
        response = await pipeline.process(request)
        assert response.request_id
        assert response.intent is not None
        assert response.success
        assert response.output is not None
        assert response.duration_ms > 0
        assert len(response.stages) > 0

    @pytest.mark.asyncio
    async def test_pipeline_blocks_harmful(self):
        pipeline = EndToEndPipeline()
        request = PipelineRequest(input="how to make a bomb")
        response = await pipeline.process(request)
        assert not response.success
        assert "guardrail" in (response.blocked_reason or "").lower() or "blocked" in (response.blocked_reason or "").lower()

    @pytest.mark.asyncio
    async def test_pipeline_with_pattern(self):
        pipeline = EndToEndPipeline()
        request = PipelineRequest(
            input="review this code",
            pattern="pipeline",
        )
        response = await pipeline.process(request)
        assert response.pattern_used == "pipeline"

    @pytest.mark.asyncio
    async def test_pipeline_records_stages(self):
        pipeline = EndToEndPipeline()
        request = PipelineRequest(input="test the agent")
        response = await pipeline.process(request)
        stage_names = [s["name"] for s in response.stages]
        assert "classify" in stage_names
        assert "route" in stage_names or "pattern" in stage_names
        assert "execute" in stage_names or any("run" in n for n in stage_names)


# --- Prometheus Metrics Tests ---
class TestPrometheusMetrics:
    def test_record_run(self):
        record_run("code_generation", "tech", "success", 1.5)

    def test_record_agent(self):
        record_agent("coder", "pipeline", 0.5, True)

    def test_record_pattern(self):
        record_pattern("supervisor", True, 3)

    def test_record_cache(self):
        record_cache("prompt", True)
        record_cache("prompt", False)

    def test_record_compression(self):
        record_compression("lossy", 2.5)

    def test_record_memory(self):
        record_memory("working", "store", False)
        record_memory("long_term", "recall", True)

    def test_record_rag(self):
        record_rag("hybrid", 0.1, 5)

    def test_record_policy(self):
        record_policy("allow")
        record_policy("deny")

    def test_record_eval(self):
        record_eval(8, 10)

    def test_record_guardrail(self):
        record_guardrail("injection", True)
        record_guardrail("pii", False)

    def test_get_metrics_returns_bytes(self):
        m = get_metrics()
        assert isinstance(m, bytes)
        assert len(m) > 0
        assert b"agentos" in m
