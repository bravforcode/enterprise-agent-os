"""Tests for Ollama client and helper."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from graxia_tool.llm import (
    AnthropicClient,
    LLMResponse,
    MockLLMClient,
    OllamaClient,
    OpenAIClient,
    get_llm_client,
    get_llm_client_async,
)
from graxia_tool.ollama_helper import (
    OLLAMA_URL,
    has_model,
    is_ollama_installed,
    is_ollama_running,
    list_models,
)


# ----- OllamaClient -----


@pytest.mark.asyncio
async def test_ollama_client_init_default_url():
    """Default URL should be localhost:11434."""
    client = OllamaClient()
    assert OLLAMA_URL in client.base_url or "11434" in client.base_url


@pytest.mark.asyncio
async def test_ollama_client_custom_url():
    client = OllamaClient(base_url="http://example.com:1234")
    assert client.base_url == "http://example.com:1234"


@pytest.mark.asyncio
async def test_ollama_client_custom_model():
    client = OllamaClient(default_model="qwen2.5:7b")
    assert client.default_model == "qwen2.5:7b"


@pytest.mark.asyncio
async def test_ollama_client_env_var_url(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-server.local:11434")
    client = OllamaClient()
    assert client.base_url == "http://gpu-server.local:11434"


@pytest.mark.asyncio
async def test_ollama_client_env_var_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "gemma2:2b")
    client = OllamaClient()
    assert client.default_model == "gemma2:2b"


@pytest.mark.asyncio
async def test_ollama_is_available_true():
    client = OllamaClient()
    # Mock httpx client
    mock_response = MagicMock()
    mock_response.status_code = 200
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=mock_response)
    assert await client.is_available() is True


@pytest.mark.asyncio
async def test_ollama_is_available_false_connection_error():
    client = OllamaClient()
    client._client = MagicMock()
    client._client.get = AsyncMock(side_effect=Exception("Connection refused"))
    assert await client.is_available() is False


@pytest.mark.asyncio
async def test_ollama_list_models():
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "models": [
            {"name": "llama3.2:1b"},
            {"name": "qwen2.5:7b"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    client._client = MagicMock()
    client._client.get = AsyncMock(return_value=mock_response)
    models = await client.list_models()
    assert models == ["llama3.2:1b", "qwen2.5:7b"]


@pytest.mark.asyncio
async def test_ollama_complete_success():
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": "Hello from Ollama!",
        "prompt_eval_count": 10,
        "eval_count": 5,
        "total_duration": 1234567890,
        "load_duration": 500000000,
    }
    mock_response.raise_for_status = MagicMock()
    client._client = MagicMock()
    client._client.post = AsyncMock(return_value=mock_response)
    result = await client.complete("Hello")
    assert isinstance(result, LLMResponse)
    assert result.content == "Hello from Ollama!"
    assert result.tokens_in == 10
    assert result.tokens_out == 5
    assert result.cost_usd == 0.0  # Local model is free
    assert result.model == "llama3.2"


@pytest.mark.asyncio
async def test_ollama_complete_with_system():
    client = OllamaClient()
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "response": "ok",
        "prompt_eval_count": 1,
        "eval_count": 1,
    }
    mock_response.raise_for_status = MagicMock()
    client._client = MagicMock()
    post_mock = AsyncMock(return_value=mock_response)
    client._client.post = post_mock
    await client.complete("hi", system="You are helpful")
    # Check the payload included the system field
    call_args = post_mock.call_args
    assert "system" in call_args.kwargs["json"]


@pytest.mark.asyncio
async def test_ollama_complete_connection_error():
    import httpx
    client = OllamaClient()
    client._client = MagicMock()
    client._client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
        await client.complete("hi")


# ----- Model costs -----


def test_ollama_models_are_free():
    from graxia_tool.llm import MODEL_COSTS
    # All Ollama model costs should be 0
    for model, (c_in, c_out) in MODEL_COSTS.items():
        if model.startswith(("llama", "qwen", "gemma", "phi", "mistral", "codellama", "deepseek")):
            assert c_in == 0.0, f"{model} input cost should be 0"
            assert c_out == 0.0, f"{model} output cost should be 0"


def test_anthropic_models_have_costs():
    from graxia_tool.llm import MODEL_COSTS
    for model in ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]:
        assert model in MODEL_COSTS
        c_in, c_out = MODEL_COSTS[model]
        assert c_in > 0
        assert c_out > 0


def test_openai_models_have_costs():
    from graxia_tool.llm import MODEL_COSTS
    for model in ["gpt-4", "gpt-3.5-turbo", "gpt-4o-mini"]:
        assert model in MODEL_COSTS


# ----- Factory -----


def test_factory_returns_ollama_by_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = get_llm_client()
    assert isinstance(client, OllamaClient)


def test_factory_anthropic_with_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    client = get_llm_client("claude-3-5-sonnet-20241022")
    assert isinstance(client, AnthropicClient)


def test_factory_openai_with_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = get_llm_client("gpt-4o")
    assert isinstance(client, OpenAIClient)


def test_factory_explicit_ollama(monkeypatch):
    client = get_llm_client("llama3.2")
    assert isinstance(client, OllamaClient)


def test_factory_qwen_routes_to_ollama(monkeypatch):
    client = get_llm_client("qwen2.5")
    assert isinstance(client, OllamaClient)


def test_factory_codellama_routes_to_ollama():
    client = get_llm_client("codellama")
    assert isinstance(client, OllamaClient)


@pytest.mark.asyncio
async def test_factory_async_picks_ollama_when_running():
    ollama = OllamaClient()
    ollama._client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    ollama._client.get = AsyncMock(return_value=mock_response)

    with patch("graxia_tool.llm.OllamaClient", return_value=ollama):
        client = await get_llm_client_async()
        assert isinstance(client, OllamaClient)


# ----- Mock LLM Client -----


@pytest.mark.asyncio
async def test_mock_client():
    client = MockLLMClient()
    result = await client.complete("test")
    assert result.metadata.get("mock") is True
    assert "Mock" in result.content


# ----- Ollama helper -----


def test_helper_is_ollama_installed():
    """Just check the function is callable and returns bool."""
    result = is_ollama_installed()
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_helper_is_ollama_running():
    result = await is_ollama_running()
    assert isinstance(result, bool)


@pytest.mark.asyncio
async def test_helper_list_models():
    result = await list_models()
    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_helper_has_model():
    result = await has_model("llama3.2:1b")
    assert isinstance(result, bool)


# ----- Estimate cost -----


def test_estimate_cost_local_model():
    client = OllamaClient()
    cost = client.estimate_cost("llama3.2", 1000, 1000)
    assert cost == 0.0


def test_estimate_cost_anthropic():
    client = OllamaClient()
    cost = client.estimate_cost("claude-3-5-sonnet-20241022", 1000, 1000)
    expected = 0.003 + 0.015  # 1K in + 1K out
    assert abs(cost - expected) < 0.0001


def test_estimate_cost_unknown_model():
    client = OllamaClient()
    cost = client.estimate_cost("unknown-model-xyz", 1000, 1000)
    assert cost == 0.0
