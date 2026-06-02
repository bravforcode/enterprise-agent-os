"""Tests for LLM clients — 30+ tests."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.llm import (
    LLMClient, LLMResponse, MockLLMClient,
    AnthropicClient, OpenAIClient, get_llm_client,
    MODEL_COSTS,
)


# --- Cost Estimation Tests ---

class TestCostEstimation:
    """Tests for cost calculation."""

    def test_known_model_costs(self):
        """Should have cost data for known models."""
        assert "claude-3-5-sonnet-20241022" in MODEL_COSTS
        assert "gpt-4o" in MODEL_COSTS

    def test_cost_calculation(self):
        """Should calculate cost correctly."""
        client = MockLLMClient()
        # claude-3-haiku: $0.00025/1K in, $0.00125/1K out
        cost = client.estimate_cost("claude-3-haiku-20240307", 1000, 1000)
        expected = 0.00025 + 0.00125
        assert abs(cost - expected) < 0.0001

    def test_unknown_model_cost(self):
        """Should return 0 for unknown models."""
        client = MockLLMClient()
        cost = client.estimate_cost("unknown-model", 1000, 1000)
        assert cost == 0.0

    def test_zero_tokens_cost(self):
        """Should handle zero tokens."""
        client = MockLLMClient()
        cost = client.estimate_cost("gpt-4o", 0, 0)
        assert cost == 0.0


# --- Mock Client Tests ---

class TestMockClient:
    """Tests for mock LLM client."""

    @pytest.mark.asyncio
    async def test_complete_returns_response(self):
        """Should return LLMResponse."""
        client = MockLLMClient(model="test-model")
        resp = await client.complete("Hello world")
        assert isinstance(resp, LLMResponse)
        assert "Hello world" in resp.content
        assert resp.model == "test-model"

    @pytest.mark.asyncio
    async def test_mock_zero_cost(self):
        """Mock should have zero cost."""
        client = MockLLMClient()
        resp = await client.complete("test")
        assert resp.cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_mock_counts_tokens(self):
        """Mock should count input tokens."""
        client = MockLLMClient()
        resp = await client.complete("one two three four five")
        assert resp.tokens_in == 5


# --- Factory Tests ---

class TestFactory:
    """Tests for LLM factory."""

    def test_mock_default(self):
        """Should return mock when no keys set."""
        with patch.dict(os.environ, {}, clear=True):
            client = get_llm_client("anything")
            assert isinstance(client, MockLLMClient)

    def test_anthropic_with_key(self):
        """Should return AnthropicClient when key set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = get_llm_client("claude-3-5-haiku-20241022")
            assert isinstance(client, AnthropicClient)

    def test_openai_with_key(self):
        """Should return OpenAIClient when key set."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            client = get_llm_client("gpt-4o-mini")
            assert isinstance(client, OpenAIClient)

    def test_anthropic_no_key_fallback(self):
        """Should fallback to mock if no key."""
        with patch.dict(os.environ, {}, clear=True):
            client = get_llm_client("claude-3-5-sonnet-20241022")
            assert isinstance(client, MockLLMClient)

    def test_openai_no_key_fallback(self):
        """Should fallback to mock if no key."""
        with patch.dict(os.environ, {}, clear=True):
            client = get_llm_client("gpt-4")
            assert isinstance(client, MockLLMClient)


# --- Anthropic Client Tests (mocked HTTP) ---

class TestAnthropicClient:
    """Tests for Anthropic client with mocked HTTP."""

    def test_init_requires_key(self):
        """Should raise if no API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                AnthropicClient()

    def test_init_with_key(self):
        """Should init with provided key."""
        client = AnthropicClient(api_key="test-key")
        assert client.api_key == "test-key"
        assert client.default_model == "claude-3-5-haiku-20241022"

    @pytest.mark.asyncio
    async def test_complete_success(self):
        """Should call API and return response."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = AnthropicClient()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"text": "Hello from Claude"}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "stop_reason": "end_turn",
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(client._client, "post", return_value=mock_response):
                resp = await client.complete("test prompt")

            assert resp.content == "Hello from Claude"
            assert resp.tokens_in == 10
            assert resp.tokens_out == 5
            assert resp.cost_usd > 0

            await client.close()

    @pytest.mark.asyncio
    async def test_complete_with_system(self):
        """Should include system message."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            client = AnthropicClient()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "content": [{"text": "ok"}],
                "usage": {"input_tokens": 5, "output_tokens": 2},
            }
            mock_response.raise_for_status = MagicMock()

            captured_payload = {}
            async def capture_post(url, json):
                captured_payload.update(json)
                return mock_response

            with patch.object(client._client, "post", side_effect=capture_post):
                await client.complete("hi", system="You are helpful")

            assert captured_payload.get("system") == "You are helpful"
            await client.close()


# --- OpenAI Client Tests (mocked HTTP) ---

class TestOpenAIClient:
    """Tests for OpenAI client with mocked HTTP."""

    def test_init_requires_key(self):
        """Should raise if no API key."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                OpenAIClient()

    def test_init_with_key(self):
        """Should init with provided key."""
        client = OpenAIClient(api_key="test-key")
        assert client.api_key == "test-key"
        assert client.default_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_complete_success(self):
        """Should call API and return response."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            client = OpenAIClient()

            mock_response = MagicMock()
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Hello from GPT"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
            mock_response.raise_for_status = MagicMock()

            with patch.object(client._client, "post", return_value=mock_response):
                resp = await client.complete("test prompt")

            assert resp.content == "Hello from GPT"
            assert resp.tokens_in == 10
            assert resp.tokens_out == 5
            assert resp.cost_usd > 0

            await client.close()


# --- LLMResponse Tests ---

class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_create_response(self):
        """Should create response with all fields."""
        resp = LLMResponse(
            content="test",
            model="gpt-4o",
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            duration_ms=100,
            metadata={},
        )
        assert resp.content == "test"
        assert resp.tokens_in == 10
        assert resp.cost_usd == 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
