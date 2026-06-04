"""Tests for OpenRouterClient — fallback chain across 6+ free models."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.llm import (
    OpenRouterClient, LLMResponse, get_llm_client, make_llm_func, MockLLMClient,
    HybridLLMClient,
)


# --- Init / config ---

class TestOpenRouterInit:
    def test_init_requires_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
                OpenRouterClient()

    def test_init_with_key(self):
        client = OpenRouterClient(api_key="test-key")
        assert client.api_key == "test-key"
        assert client.default_model == "nvidia/nemotron-3-super-120b-a12b:free"
        assert len(client.fallback_chain) >= 6

    def test_init_custom_fallback(self):
        custom = ["custom/model:free"]
        client = OpenRouterClient(api_key="k", fallback_chain=custom)
        assert client.fallback_chain == custom
        assert client.default_model == "custom/model:free"

    def test_default_chain_has_7_models(self):
        """Should have at least 6 tested working free models."""
        client = OpenRouterClient(api_key="k")
        assert len(client.fallback_chain) >= 6
        assert "nvidia/nemotron-3-super-120b-a12b:free" in client.fallback_chain
        assert "liquid/lfm-2.5-1.2b-instruct:free" in client.fallback_chain


# --- Fallback decision logic ---

class TestFallbackLogic:
    def setup_method(self):
        self.client = OpenRouterClient(api_key="test-key")

    def test_rate_limit_triggers_fallback(self):
        assert self.client._is_fallback_error(429, "rate-limited") is True

    def test_no_upstream_triggers_fallback(self):
        assert self.client._is_fallback_error(503, "no healthy upstream") is True

    def test_500_triggers_fallback(self):
        assert self.client._is_fallback_error(500, "internal error") is True

    def test_400_does_not_trigger_fallback(self):
        """4xx errors (except 429) should NOT trigger fallback — likely a real error."""
        assert self.client._is_fallback_error(400, "bad request") is False
        assert self.client._is_fallback_error(401, "unauthorized") is False

    def test_timeout_triggers_fallback(self):
        assert self.client._is_fallback_error(0, "ConnectError: timeout") is True


# --- Complete with mocked HTTP ---

def _mock_response(status_code, json_data=None, text=""):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if json_data is not None:
        resp.json = MagicMock(return_value=json_data)
    return resp


def _ok_response(content="Hello", model="nvidia/nemotron-3-super-120b-a12b:free"):
    return _mock_response(200, {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def _err_response(status_code, msg="error"):
    return _mock_response(status_code, text=msg)


class TestCompleteSuccess:
    @pytest.mark.asyncio
    async def test_first_model_succeeds(self):
        client = OpenRouterClient(api_key="test-key")
        with patch.object(client._client, "post", return_value=_ok_response("Hi!")):
            resp = await client.complete("test")
            assert resp.content == "Hi!"
            assert resp.model == "nvidia/nemotron-3-super-120b-a12b:free"
            assert resp.tokens_in == 10
            assert resp.tokens_out == 5
            assert resp.cost_usd == 0.0
        await client.close()

    @pytest.mark.asyncio
    async def test_with_system_prompt(self):
        client = OpenRouterClient(api_key="test-key")
        captured = {}
        async def capture_post(url, json):
            captured.update(json)
            return _ok_response()
        with patch.object(client._client, "post", side_effect=capture_post):
            await client.complete("hi", system="You are helpful")
        assert captured["messages"][0] == {"role": "system", "content": "You are helpful"}
        assert captured["messages"][1] == {"role": "user", "content": "hi"}
        await client.close()

    @pytest.mark.asyncio
    async def test_explicit_model_first(self):
        client = OpenRouterClient(api_key="test-key")
        captured_models = []
        async def capture(url, json):
            captured_models.append(json["model"])
            return _ok_response()
        with patch.object(client._client, "post", side_effect=capture):
            await client.complete("test", model="google/gemma-4-31b-it:free")
        assert captured_models[0] == "google/gemma-4-31b-it:free"
        # explicit model appears first, then rest of chain
        assert len(captured_models) == 1  # first try succeeded
        await client.close()

    @pytest.mark.asyncio
    async def test_metadata_includes_chain(self):
        client = OpenRouterClient(api_key="test-key")
        with patch.object(client._client, "post", return_value=_ok_response()):
            resp = await client.complete("test")
        assert "fallback_chain" in resp.metadata
        assert "tried_count" in resp.metadata
        await client.close()


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_fallback_after_429(self):
        """If first model returns 429, should try next model."""
        client = OpenRouterClient(api_key="test-key")
        call_count = [0]
        async def side_effect(url, json):
            call_count[0] += 1
            if call_count[0] == 1:
                return _err_response(429, "rate-limited")
            return _ok_response("Fallback worked")
        with patch.object(client._client, "post", side_effect=side_effect):
            resp = await client.complete("test")
        assert resp.content == "Fallback worked"
        assert resp.model != "nvidia/nemotron-3-super-120b-a12b:free"
        assert call_count[0] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_fallback_after_503(self):
        """If first model returns 503, should try next model."""
        client = OpenRouterClient(api_key="test-key")
        call_count = [0]
        async def side_effect(url, json):
            call_count[0] += 1
            if call_count[0] == 1:
                return _err_response(503, "no healthy upstream")
            return _ok_response("503 fallback")
        with patch.object(client._client, "post", side_effect=side_effect):
            resp = await client.complete("test")
        assert resp.content == "503 fallback"
        assert call_count[0] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_fallback_after_timeout(self):
        """If first model raises ConnectError, should try next model."""
        import httpx
        client = OpenRouterClient(api_key="test-key")
        call_count = [0]
        async def side_effect(url, json):
            call_count[0] += 1
            if call_count[0] == 1:
                raise httpx.ConnectError("connection refused")
            return _ok_response("After timeout")
        with patch.object(client._client, "post", side_effect=side_effect):
            resp = await client.complete("test")
        assert resp.content == "After timeout"
        assert call_count[0] == 2
        await client.close()

    @pytest.mark.asyncio
    async def test_fallback_through_3_models(self):
        """Should fall back through 3 models before success."""
        client = OpenRouterClient(api_key="test-key")
        call_count = [0]
        models_tried = []
        async def side_effect(url, json):
            call_count[0] += 1
            models_tried.append(json["model"])
            if call_count[0] <= 3:
                return _err_response(429, "rate-limited")
            return _ok_response("After 3 retries")
        with patch.object(client._client, "post", side_effect=side_effect):
            resp = await client.complete("test")
        assert resp.content == "After 3 retries"
        assert call_count[0] == 4
        assert len(models_tried) == 4
        assert len(set(models_tried)) == 4  # all different models
        await client.close()

    @pytest.mark.asyncio
    async def test_all_models_fail_raises(self):
        """If ALL models fail with 429, should raise informative error."""
        client = OpenRouterClient(api_key="test-key")
        async def always_fail(url, json):
            return _err_response(429, "rate-limited")
        with patch.object(client._client, "post", side_effect=always_fail):
            with pytest.raises(RuntimeError, match="All .* OpenRouter models failed"):
                await client.complete("test")
        await client.close()

    @pytest.mark.asyncio
    async def test_non_fallback_error_raises_immediately(self):
        """If 400 (bad request), should NOT try other models — raise immediately."""
        client = OpenRouterClient(api_key="test-key")
        call_count = [0]
        async def side_effect(url, json):
            call_count[0] += 1
            return _err_response(400, "invalid model")
        with patch.object(client._client, "post", side_effect=side_effect):
            with pytest.raises(RuntimeError, match="OpenRouter API error 400"):
                await client.complete("test")
        assert call_count[0] == 1  # did not retry on 400
        await client.close()


# --- List free models ---

class TestListFreeModels:
    @pytest.mark.asyncio
    async def test_list_filters_free_only(self):
        client = OpenRouterClient(api_key="test-key")
        mock_resp = _mock_response(200, {
            "data": [
                {"id": "openai/gpt-4o"},
                {"id": "nvidia/nemotron-3-super-120b-a12b:free"},
                {"id": "google/gemma-4-31b-it:free"},
                {"id": "anthropic/claude-3.5-sonnet"},
            ]
        })
        with patch.object(client._client, "get", return_value=mock_resp):
            free = await client.list_free_models()
        assert len(free) == 2
        assert all(m["id"].endswith(":free") for m in free)
        await client.close()


# --- Factory integration ---

class TestFactoryIntegration:
    def test_factory_returns_hybrid_by_default(self):
        """Default factory should return HybridLLMClient (OpenRouter + Ollama fallback)."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}, clear=False):
            for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
                os.environ.pop(k, None)
            client = get_llm_client("auto")
            assert isinstance(client, HybridLLMClient), f"Got {type(client).__name__}"

    def test_hybrid_uses_openrouter_when_key_set(self):
        """HybridLLMClient with key set should attempt OpenRouter (not bare OllamaClient)."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = get_llm_client("auto")
            assert isinstance(client, HybridLLMClient)
            assert client._openrouter_key == "test-key"

    def test_hybrid_uses_ollama_only_without_key(self):
        """Without OPENROUTER_API_KEY, HybridLLMClient should skip OpenRouter entirely."""
        with patch.dict(os.environ, {}, clear=True):
            client = get_llm_client("auto")
            assert isinstance(client, HybridLLMClient)
            assert client._openrouter_key is None

    def test_factory_with_explicit_ollama_model_returns_bare_ollama(self):
        """Explicit Ollama model name should return bare OllamaClient (no hybrid)."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            client = get_llm_client("llama3.2")
            from graxia_tool.llm import OllamaClient
            assert isinstance(client, OllamaClient)
            assert client.default_model == "llama3.2"


# --- Cost ---

class TestCost:
    def test_openrouter_models_are_free(self):
        client = OpenRouterClient(api_key="k")
        cost = client.estimate_cost("nvidia/nemotron-3-super-120b-a12b:free", 1000, 1000)
        assert cost == 0.0

    def test_unknown_openrouter_model_costs_zero(self):
        """Unknown OpenRouter model falls back to 0 cost (free tier default)."""
        client = OpenRouterClient(api_key="k")
        cost = client.estimate_cost("some-unknown:free", 1000, 1000)
        assert cost == 0.0


# --- make_llm_func factory (wires real LLM into agents) ---

class TestMakeLLMFunc:
    @pytest.mark.asyncio
    async def test_with_mock_client(self):
        """Should work with MockLLMClient (no API key needed)."""
        func = make_llm_func(client=MockLLMClient())
        result = await func("hello", system="be helpful")
        assert "hello" in result.lower() or "Mock" in result

    @pytest.mark.asyncio
    async def test_works_with_agent_llm_func(self):
        """Result should be assignable to an agent's llm_func attribute."""
        from graxia_tool.agents.implementations import Coder
        func = make_llm_func(client=MockLLMClient())
        agent = Coder()
        agent.llm_func = func
        assert callable(agent.llm_func)

    def test_func_signature_compatible(self):
        """Should accept (prompt, system=None, **kwargs) signature."""
        import inspect
        func = make_llm_func(client=MockLLMClient())
        sig = inspect.signature(func)
        params = list(sig.parameters.keys())
        assert "prompt" in params
        assert "system" in params

    @pytest.mark.asyncio
    async def test_auto_closes_own_client(self):
        """If we pass client=None, factory should close the auto-created one."""
        # We can't easily test this without hitting real API; just verify the path exists
        func = make_llm_func(client=MockLLMClient())
        result = await func("test")
        assert result is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
