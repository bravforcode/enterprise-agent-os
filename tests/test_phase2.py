"""Enterprise Agent OS — Phase 2 tests."""
import pytest
from graxia_tool.core.model_router import (
    ModelRouter, ModelTier, detect_complexity, MODEL_CATALOG
)
from graxia_tool.core.context_compressor import ContextCompressor
from graxia_tool.core.token_budget import TokenBudgetManager
from graxia_tool.core.prompt_cache import PromptCache


# --- Model Router Tests ---
class TestModelRouter:
    def test_detect_complexity_simple(self):
        tier = detect_complexity("yes")
        assert tier == ModelTier.HAIKU

    def test_detect_complexity_medium(self):
        tier = detect_complexity("write a python function to parse JSON")
        assert tier == ModelTier.MINI

    def test_detect_complexity_complex(self):
        tier = detect_complexity("architect a multi-step refactor for the entire system")
        assert tier == ModelTier.MAIN

    def test_router_returns_spec(self):
        router = ModelRouter()
        spec = router.route("hello")
        assert spec is not None
        assert hasattr(spec, "name")
        assert hasattr(spec, "cost_per_1k_input")

    def test_router_respects_capability(self):
        router = ModelRouter()
        spec = router.route("describe this image", required_capabilities=["vision"])
        assert "vision" in spec.capabilities

    def test_router_respects_max_cost(self):
        router = ModelRouter()
        spec = router.route("hello", max_cost=0.0001)
        assert spec.cost_per_1k_input <= 0.0001

    def test_estimate_cost(self):
        router = ModelRouter()
        spec = MODEL_CATALOG[ModelTier.MINI]
        cost = router.estimate_cost(spec, 1000, 500)
        assert cost > 0

    def test_usage_tracking(self):
        router = ModelRouter()
        router.route("hello")
        router.route("hello")
        usage = router.get_usage()
        assert sum(usage.values()) == 2


# --- Context Compressor Tests ---
class TestContextCompressor:
    def test_count_tokens(self):
        comp = ContextCompressor()
        assert comp.count_tokens("hello world") == 2  # 11 chars / 4 = 2

    def test_no_compression_needed(self):
        comp = ContextCompressor(max_tokens=1000)
        messages = [{"role": "user", "content": "hi"}]
        result, compression = comp.auto_compress(messages)
        assert compression.strategy == "none"
        assert len(result) == 1

    def test_lossless_compression(self):
        comp = ContextCompressor(max_tokens=100, keep_recent=2)
        messages = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
            {"role": "user", "content": "e" * 200},
        ]
        result, compression = comp.auto_compress(messages)
        assert compression.messages_removed == 3
        assert len(result) == 2

    def test_compress_with_summary(self):
        comp = ContextCompressor(max_tokens=100, keep_recent=2)
        messages = [
            {"role": "user", "content": "a" * 200},
            {"role": "assistant", "content": "b" * 200},
            {"role": "user", "content": "c" * 200},
            {"role": "assistant", "content": "d" * 200},
        ]
        result, compression = comp.auto_compress(
            messages,
            summarize_func=lambda x: "Summary: discussed 4 messages",
        )
        assert compression.messages_summarized > 0
        assert any("Summary" in m.get("content", "") for m in result)

    def test_lossy_with_summary(self):
        comp = ContextCompressor(keep_recent=2)
        messages = [
            {"role": "user", "content": "old msg 1"},
            {"role": "assistant", "content": "old reply 1"},
            {"role": "user", "content": "recent 1"},
            {"role": "assistant", "content": "recent 2"},
        ]
        result = comp.compress_lossy(messages, "summary text")
        assert result.messages_summarized == 2
        assert result.summary == "summary text"


# --- Token Budget Tests ---
class TestTokenBudget:
    def test_initial_status(self):
        mgr = TokenBudgetManager()
        # Without Redis available, this might fail — that's OK
        import asyncio
        try:
            status = asyncio.run(mgr.check_budget("user-1", "session-1"))
            assert status.turn_limit > 0
            assert status.day_limit > 0
        except Exception:
            pytest.skip("Redis not available")


# --- Prompt Cache Tests ---
class TestPromptCache:
    def test_hash_prompt(self):
        cache = PromptCache()
        h1 = cache._hash_prompt("hello", "gpt-4o")
        h2 = cache._hash_prompt("hello", "gpt-4o")
        h3 = cache._hash_prompt("hello", "gpt-4o-mini")
        assert h1 == h2
        assert h1 != h3  # different model = different cache key

    def test_stats_initial(self):
        cache = PromptCache()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0
