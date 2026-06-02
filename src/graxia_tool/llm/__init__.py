"""LLM clients for Graxia Tool.

Supports:
- OllamaClient: Local LLM via Ollama (no API key needed, free, offline)
- AnthropicClient: Claude models via Anthropic API (requires ANTHROPIC_API_KEY)
- OpenAIClient: GPT models via OpenAI API (requires OPENAI_API_KEY)
- MockLLMClient: Deterministic mock for testing only

Default priority (no env vars set):
1. Ollama (local, free, no key) — RECOMMENDED for zero-setup
2. Anthropic (if ANTHROPIC_API_KEY set)
3. OpenAI (if OPENAI_API_KEY set)
"""
from __future__ import annotations

import asyncio
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

import httpx


# Cost per 1K tokens (input, output) — 0 for local models
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
    # Ollama — free, local (0 cost)
    "llama3.2": (0.0, 0.0),
    "llama3.1": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "gemma2": (0.0, 0.0),
    "phi3": (0.0, 0.0),
    "mistral": (0.0, 0.0),
    "codellama": (0.0, 0.0),
    "deepseek-coder": (0.0, 0.0),
}


# Default Ollama model — small, fast, good enough
DEFAULT_OLLAMA_MODEL = "llama3.2:1b"


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
    """Deterministic mock for testing — DO NOT USE IN PRODUCTION."""

    def __init__(self, model: str = "mock-model"):
        self.model = model

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> LLMResponse:
        start = time.time()
        await asyncio.sleep(0.01)
        duration_ms = int((time.time() - start) * 1000)
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


class OllamaClient(LLMClient):
    """Ollama local LLM client — FREE, no API key, runs offline.

    Requires Ollama installed and running: https://ollama.com
    Default: http://localhost:11434
    """

    BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or os.getenv("OLLAMA_HOST", self.BASE_URL)).rstrip("/")
        self.default_model = default_model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )
        self._available: Optional[bool] = None

    async def is_available(self) -> bool:
        """Check if Ollama is running and accessible."""
        if self._available is not None:
            return self._available
        try:
            resp = await self._client.get("/api/tags", timeout=2.0)
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    async def list_models(self) -> list[str]:
        """List available models on the Ollama server."""
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    async def ensure_model(self, model: Optional[str] = None) -> bool:
        """Ensure the specified model is available, pull if needed."""
        model = model or self.default_model
        models = await self.list_models()
        # Check if model exists (with or without tag)
        for m in models:
            if m == model or m.startswith(f"{model}:"):
                return True
        # Pull the model
        try:
            resp = await self._client.post(
                "/api/pull",
                json={"name": model, "stream": False},
                timeout=600.0,
            )
            resp.raise_for_status()
            return True
        except Exception:
            return False

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call Ollama generate API."""
        start = time.time()
        model = model or self.default_model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        if system:
            payload["system"] = system

        try:
            resp = await self._client.post("/api/generate", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            error_body = e.response.text
            raise RuntimeError(f"Ollama API error {e.response.status_code}: {error_body}")
        except httpx.ConnectError:
            raise RuntimeError(
                f"Cannot connect to Ollama at {self.base_url}. "
                f"Install from https://ollama.com and run: ollama pull {model}"
            )

        duration_ms = int((time.time() - start) * 1000)
        content = data.get("response", "")

        # Ollama returns prompt_eval_count and eval_count
        tokens_in = data.get("prompt_eval_count", len(prompt.split()))
        tokens_out = data.get("eval_count", len(content.split()))
        cost = self.estimate_cost(model, tokens_in, tokens_out)

        return LLMResponse(
            content=content,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            duration_ms=duration_ms,
            metadata={
                "total_duration": data.get("total_duration"),
                "load_duration": data.get("load_duration"),
            },
        )

    async def close(self):
        await self._client.aclose()


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


def get_llm_client(model: str = "auto") -> LLMClient:
    """Factory: get appropriate LLM client.

    Priority (default, no env vars):
    1. Ollama (local, free, no key) — RECOMMENDED
    2. Anthropic (if ANTHROPIC_API_KEY set)
    3. OpenAI (if OPENAI_API_KEY set)

    Args:
        model: "auto" (default), or specific model name
    """
    if model == "auto" or model == "ollama" or model.startswith(("llama", "qwen", "gemma", "phi", "mistral", "codellama", "deepseek")):
        # Try Ollama first (no API key, local)
        return OllamaClient()

    if model.startswith("claude-"):
        if os.getenv("ANTHROPIC_API_KEY"):
            return AnthropicClient(default_model=model)

    if model.startswith("gpt-"):
        if os.getenv("OPENAI_API_KEY"):
            return OpenAIClient(default_model=model)

    # Fallback: try Ollama (works without API key)
    return OllamaClient()


async def get_llm_client_async() -> LLMClient:
    """Async factory: detect best available LLM at runtime.

    Priority:
    1. Ollama if running (local, free, no key)
    2. Anthropic if ANTHROPIC_API_KEY set
    3. OpenAI if OPENAI_API_KEY set
    4. Ollama anyway (will fail with helpful error if not running)
    """
    # Try Ollama first
    ollama = OllamaClient()
    if await ollama.is_available():
        return ollama
    await ollama.close()

    # Try API clients
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicClient()

    if os.getenv("OPENAI_API_KEY"):
        return OpenAIClient()

    # Fallback: return Ollama anyway (will give helpful error)
    return OllamaClient()
