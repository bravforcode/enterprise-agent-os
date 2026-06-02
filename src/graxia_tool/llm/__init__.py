"""Real LLM client for Anthropic and OpenAI APIs.

Provides:
- AnthropicClient: claude-3-5-sonnet, claude-3-haiku, etc.
- OpenAIClient: gpt-4, gpt-3.5-turbo, etc.
- MockLLMClient: deterministic mock for testing
- LLMFactory: route to correct client based on model name
"""
from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# Cost per 1K tokens (input, output)
MODEL_COSTS = {
    # Anthropic
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-5-haiku-20241022": (0.0008, 0.004),
    "claude-3-opus-20240229": (0.015, 0.075),
    "claude-3-haiku-20240307": (0.00025, 0.00125),
    "claude-3-sonnet-20240229": (0.003, 0.015),
    # OpenAI
    "gpt-4-turbo": (0.01, 0.03),
    "gpt-4": (0.03, 0.06),
    "gpt-3.5-turbo": (0.0005, 0.0015),
    "gpt-4o": (0.0025, 0.01),
    "gpt-4o-mini": (0.00015, 0.0006),
}


@dataclass
class LLMResponse:
    """Standardized LLM response."""
    content: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    duration_ms: int
    metadata: dict[str, Any]


class LLMClient(ABC):
    """Abstract LLM client."""

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Send a completion request."""
        raise NotImplementedError

    def estimate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost for a given model and token counts."""
        if model not in MODEL_COSTS:
            return 0.0
        cost_in, cost_out = MODEL_COSTS[model]
        return (tokens_in / 1000 * cost_in) + (tokens_out / 1000 * cost_out)


class MockLLMClient(LLMClient):
    """Deterministic mock for testing."""

    def __init__(self, model: str = "mock-model"):
        self.model = model

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Return mock response."""
        start = time.time()
        # Simulate processing
        await asyncio.sleep(0.01)
        duration_ms = int((time.time() - start) * 1000)

        # Mock content based on prompt
        content = f"[Mock response to: {prompt[:100]}...]"
        tokens_in = len(prompt.split())
        tokens_out = len(content.split())

        return LLMResponse(
            content=content,
            model=self.model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=0.0,
            duration_ms=duration_ms,
            metadata={"mock": True},
        )


class AnthropicClient(LLMClient):
    """Anthropic API client (Claude models)."""

    BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(self, api_key: Optional[str] = None, default_model: str = "claude-3-5-haiku-20241022"):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        self.default_model = default_model
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
            timeout=60.0,
        )

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call Anthropic Messages API."""
        start = time.time()
        model = model or self.default_model

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system

        try:
            resp = await self._client.post("/messages", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            raise RuntimeError(f"Anthropic API error {e.response.status_code}: {error_body}")

        duration_ms = int((time.time() - start) * 1000)
        content = data["content"][0]["text"]
        usage = data.get("usage", {})
        tokens_in = usage.get("input_tokens", 0)
        tokens_out = usage.get("output_tokens", 0)
        cost = self.estimate_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            duration_ms=duration_ms,
            metadata={"stop_reason": data.get("stop_reason")},
        )

    async def close(self):
        await self._client.aclose()


class OpenAIClient(LLMClient):
    """OpenAI API client (GPT models)."""

    BASE_URL = "https://api.openai.com/v1"

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o-mini"):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self.default_model = default_model
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "content-type": "application/json",
            },
            timeout=60.0,
        )

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call OpenAI Chat Completions API."""
        start = time.time()
        model = model or self.default_model

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            raise RuntimeError(f"OpenAI API error {e.response.status_code}: {error_body}")

        duration_ms = int((time.time() - start) * 1000)
        content = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        cost = self.estimate_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            duration_ms=duration_ms,
            metadata={"finish_reason": data["choices"][0].get("finish_reason")},
        )

    async def close(self):
        await self._client.aclose()


def get_llm_client(model: str = "mock") -> LLMClient:
    """Factory: get appropriate LLM client based on model name.

    Returns:
    - AnthropicClient for claude-* models
    - OpenAIClient for gpt-* models
    - MockLLMClient for anything else or when no API keys set
    """
    if model.startswith("claude-"):
        if os.getenv("ANTHROPIC_API_KEY"):
            return AnthropicClient(default_model=model)
    elif model.startswith("gpt-"):
        if os.getenv("OPENAI_API_KEY"):
            return OpenAIClient(default_model=model)

    # Fallback to mock
    return MockLLMClient(model=model)
