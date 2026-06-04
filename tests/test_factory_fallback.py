"""Test that factory falls back properly when LLM backends are configured."""
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.llm import (
    OpenRouterClient, OllamaClient, HybridLLMClient,
    AnthropicClient, OpenAIClient, get_llm_client,
)


def test_no_keys_returns_hybrid_with_ollama_fallback():
    """Without OPENROUTER_API_KEY, factory returns HybridLLMClient (uses Ollama)."""
    env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
    # Also explicitly delete from the patched env to ensure it's gone
    with patch.dict(os.environ, env, clear=False):
        os.environ.pop("OPENROUTER_API_KEY", None)
        client = get_llm_client("auto")
        assert isinstance(client, HybridLLMClient), f"Got {type(client).__name__}"
        assert client._openrouter_key is None, f"OR key should be None when env unset, got {client._openrouter_key!r}"
        print(f"  No OpenRouter key -> {type(client).__name__} (OR disabled, Ollama fallback)")
    pass


def test_openrouter_key_enables_or_in_hybrid():
    """With OPENROUTER_API_KEY, HybridLLMClient should have OR key set."""
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
        client = get_llm_client("auto")
        assert isinstance(client, HybridLLMClient), f"Got {type(client).__name__}"
        assert client._openrouter_key == "test-key", "OR key should be set"
        print(f"  With OpenRouter key -> {type(client).__name__} (OR enabled)")
    pass


def test_explicit_anthropic_still_works():
    """If user explicitly requests claude- and has key, still use Anthropic."""
    env = {"ANTHROPIC_API_KEY": "test-key"}
    with patch.dict(os.environ, env, clear=False):
        client = get_llm_client("claude-3-5-sonnet-20241022")
        assert isinstance(client, AnthropicClient), f"Got {type(client).__name__}"
        print(f"  claude- with key -> {type(client).__name__} (correct)")
    pass


def test_explicit_gpt_still_works():
    env = {"OPENAI_API_KEY": "test-key"}
    with patch.dict(os.environ, env, clear=False):
        client = get_llm_client("gpt-4o")
        assert isinstance(client, OpenAIClient), f"Got {type(client).__name__}"
        print(f"  gpt- with key -> {type(client).__name__} (correct)")
    pass


def test_priority_order_hybrid_with_all_keys():
    """When all keys are set, default factory returns HybridLLMClient (OR first, Ollama fallback)."""
    env = {
        "OPENROUTER_API_KEY": "test-key",
        "ANTHROPIC_API_KEY": "test-key",
        "OPENAI_API_KEY": "test-key",
    }
    with patch.dict(os.environ, env, clear=False):
        client = get_llm_client("auto")
        assert isinstance(client, HybridLLMClient), f"Got {type(client).__name__}"
        # Hybrid has OR key set (not Anthropic or OpenAI)
        assert client._openrouter_key == "test-key"
        print(f"  All keys set, auto -> {type(client).__name__} (correct priority)")
    pass


if __name__ == "__main__":
    print("=" * 60)
    print("FACTORY FALLBACK TESTS (updated for HybridLLMClient)")
    print("=" * 60)
    tests = [
        test_no_keys_returns_hybrid_with_ollama_fallback,
        test_openrouter_key_enables_or_in_hybrid,
        test_explicit_anthropic_still_works,
        test_explicit_gpt_still_works,
        test_priority_order_hybrid_with_all_keys,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print("  PASS\n")
        except Exception as e:
            print(f"  FAIL: {e}\n")
            failed += 1
    print("=" * 60)
    print(f"Result: {len(tests) - failed}/{len(tests)} passed")
    sys.exit(failed)
