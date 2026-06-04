"""LLM clients for Graxia Tool.

Supports:
- OpenRouterClient: Cloud free-tier models via OpenRouter (requires OPENROUTER_API_KEY, auto-fallback chain)
- OllamaClient: Local LLM via Ollama (no API key needed, free, offline)
- AnthropicClient: Claude models via Anthropic API (requires ANTHROPIC_API_KEY)
- OpenAIClient: GPT models via OpenAI API (requires OPENAI_API_KEY)
- MockLLMClient: Deterministic mock for testing only

Default priority (no env vars set):
1. OpenRouter (if OPENROUTER_API_KEY set) — RECOMMENDED for cloud free tier
2. Ollama (local, free, no key) — offline alternative
3. Anthropic (if ANTHROPIC_API_KEY set)
4. OpenAI (if OPENAI_API_KEY set)
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
    # OpenRouter free tier — all 0 cost
    "nvidia/nemotron-3-super-120b-a12b:free": (0.0, 0.0),
    "liquid/lfm-2.5-1.2b-instruct:free": (0.0, 0.0),
    "google/gemma-4-31b-it:free": (0.0, 0.0),
    "google/gemma-4-26b-a4b-it:free": (0.0, 0.0),
    "nvidia/nemotron-nano-12b-v2-vl:free": (0.0, 0.0),
    "moonshotai/kimi-k2.6:free": (0.0, 0.0),
    "z-ai/glm-4.5-air:free": (0.0, 0.0),
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


class OpenRouterClient(LLMClient):
    """OpenRouter API client with automatic fallback chain across free models.

    OpenRouter aggregates many LLM providers and exposes a single OpenAI-compatible
    API. The free tier (`* :free` model ids) requires only an API key (no payment).
    Free models are rate-limited and may return 429/503; this client tries models
    in a configurable fallback order until one succeeds.

    Requires: OPENROUTER_API_KEY env var (or pass api_key= explicitly)

    Default fallback chain (ordered by speed and reliability, tested 2026-06-04):
        1. nvidia/nemotron-3-super-120b-a12b:free   (1.03s, 1M ctx, 120B params)
        2. liquid/lfm-2.5-1.2b-instruct:free          (0.82s, 32K ctx, 1.2B params)
        3. google/gemma-4-31b-it:free                 (3.26s, 262K ctx, 31B)
        4. google/gemma-4-26b-a4b-it:free             (2.18s, 262K ctx, 26B)
        5. nvidia/nemotron-nano-12b-v2-vl:free        (1.89s, 128K ctx, 12B + vision)
        6. moonshotai/kimi-k2.6:free                  (12.88s, 262K ctx, MoE)
    """

    BASE_URL = "https://openrouter.ai/api/v1"

    DEFAULT_FALLBACK_CHAIN = [
        "nvidia/nemotron-3-super-120b-a12b:free",
        "liquid/lfm-2.5-1.2b-instruct:free",
        "google/gemma-4-31b-it:free",
        "google/gemma-4-26b-a4b-it:free",
        "nvidia/nemotron-nano-12b-v2-vl:free",
        "moonshotai/kimi-k2.6:free",
        "z-ai/glm-4.5-air:free",
    ]

    # Errors that should trigger fallback to next model
    FALLBACK_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        api_key: Optional[str] = None,
        fallback_chain: Optional[list[str]] = None,
        default_model: Optional[str] = None,
        timeout: float = 60.0,
        max_retries_per_model: int = 1,
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not set")
        self.fallback_chain = fallback_chain or self.DEFAULT_FALLBACK_CHAIN
        self.default_model = default_model or self.fallback_chain[0]
        self.max_retries_per_model = max_retries_per_model
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anomalyco/opencode",
                "X-Title": "Graxia Tool",
            },
            timeout=timeout,
        )

    def _is_fallback_error(self, status_code: int, error_text: str) -> bool:
        """Check if the error warrants falling back to next model."""
        if status_code in self.FALLBACK_STATUS_CODES:
            return True
        # Network/parse errors also trigger fallback
        if "ConnectError" in error_text or "timeout" in error_text.lower():
            return True
        return False

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Call OpenRouter chat completions API with fallback chain.

        Tries `model` first if specified, then iterates the fallback chain.
        Returns the first successful response.
        """
        # Build the try-order: explicit model first (if provided), then chain
        if model:
            try_order = [model] + [m for m in self.fallback_chain if m != model]
        else:
            try_order = list(self.fallback_chain)

        last_error: Optional[Exception] = None
        tried: list[dict[str, Any]] = []

        for current_model in try_order:
            for attempt in range(self.max_retries_per_model + 1):
                messages = []
                if system:
                    messages.append({"role": "system", "content": system})
                messages.append({"role": "user", "content": prompt})

                payload = {
                    "model": current_model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": messages,
                }

                start = time.time()
                try:
                    resp = await self._client.post("/chat/completions", json=payload)
                    if resp.status_code >= 400:
                        err_body = resp.text
                        tried.append({
                            "model": current_model,
                            "attempt": attempt + 1,
                            "status": resp.status_code,
                            "error": err_body[:200],
                        })
                        if self._is_fallback_error(resp.status_code, err_body):
                            # Fall through to next model
                            break
                        # Non-fallback HTTP error: raise immediately
                        raise RuntimeError(
                            f"OpenRouter API error {resp.status_code} on {current_model}: {err_body[:300]}"
                        )
                    data = resp.json()
                except (httpx.ConnectError, httpx.TimeoutException) as e:
                    tried.append({
                        "model": current_model,
                        "attempt": attempt + 1,
                        "status": 0,
                        "error": f"{type(e).__name__}: {str(e)[:100]}",
                    })
                    if attempt < self.max_retries_per_model:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    last_error = e
                    break  # try next model
                except RuntimeError:
                    raise
                except Exception as e:
                    tried.append({
                        "model": current_model,
                        "attempt": attempt + 1,
                        "status": 0,
                        "error": f"{type(e).__name__}: {str(e)[:100]}",
                    })
                    last_error = e
                    break  # try next model

                # Success
                duration_ms = int((time.time() - start) * 1000)
                choice = data["choices"][0]
                content = choice["message"]["content"]
                usage = data.get("usage", {})
                tokens_in = usage.get("prompt_tokens", 0)
                tokens_out = usage.get("completion_tokens", 0)
                cost = self.estimate_cost(current_model, tokens_in, tokens_out)

                return LLMResponse(
                    content=content,
                    model=current_model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost,
                    duration_ms=duration_ms,
                    metadata={
                        "finish_reason": choice.get("finish_reason"),
                        "tried_count": len(tried),
                        "fallback_chain": self.fallback_chain,
                    },
                )
            # end per-model retry loop
        # end for-each-model loop

        # All models failed
        summary = "; ".join(
            f"{t['model']}={t['status']}" for t in tried[-5:]
        )
        # Detect the common "free-models-per-day" daily quota exhaustion
        all_429 = all(t["status"] == 429 for t in tried)
        daily_quota_msg = ""
        if all_429:
            for t in tried:
                if "free-models-per-day" in t.get("error", ""):
                    daily_quota_msg = (
                        " (OpenRouter DAILY free-tier quota exhausted — "
                        "resets at UTC midnight, or add credits at https://openrouter.ai/credits)"
                    )
                    break
        raise RuntimeError(
            f"All {len(try_order)} OpenRouter models failed. Tried: {summary}. "
            f"Last error: {last_error}{daily_quota_msg}"
        )

    async def list_free_models(self) -> list[dict[str, Any]]:
        """List available free models on OpenRouter."""
        try:
            resp = await self._client.get("/models")
            resp.raise_for_status()
            data = resp.json()
            return [m for m in data.get("data", []) if m.get("id", "").endswith(":free")]
        except Exception as e:
            raise RuntimeError(f"Failed to list OpenRouter models: {e}")

    async def close(self):
        await self._client.aclose()


class HybridLLMClient(LLMClient):
    """Hybrid client: try OpenRouter first, fall back to Ollama.

    Priority order:
    1. OpenRouter (cloud, free tier, auto-fallback across 7 free models)
    2. Ollama (local, offline, no quota)

    If OPENROUTER_API_KEY is set (in env or via openrouter_key arg):
        - Try OpenRouter chain first
        - On total failure (all 7 models rate-limited/down), try Ollama
    If OPENROUTER_API_KEY is NOT set:
        - Use Ollama directly (no OpenRouter attempt)

    The Ollama fallback only triggers if Ollama is actually running.
    If neither works, raises a clear error explaining both failures.

    Args:
        openrouter_key: API key. Use the literal string "USE_ENV" to use env var.
                        Pass empty string "" to force-disable OpenRouter.
                        Pass a real key to use it.
                        Default ("USE_ENV") -> check env var OPENROUTER_API_KEY.
        ollama_url: Ollama base URL.
        ollama_model: Default Ollama model.
    """

    _USE_ENV = "USE_ENV"  # Sentinel

    def __init__(
        self,
        openrouter_key: Optional[str] = _USE_ENV,
        ollama_url: Optional[str] = None,
        ollama_model: Optional[str] = None,
    ):
        if openrouter_key is self._USE_ENV:
            # Default: use env var
            self._openrouter_key = os.getenv("OPENROUTER_API_KEY") or None
        else:
            # Explicitly passed (string or None to disable)
            self._openrouter_key = openrouter_key or None
        self._ollama_url = ollama_url or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self._ollama_model = ollama_model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
        self._openrouter: Optional[OpenRouterClient] = None
        self._ollama: Optional[OllamaClient] = None
        self._ollama_checked = False
        self._ollama_available = False

    def _get_openrouter(self) -> Optional[OpenRouterClient]:
        if not self._openrouter_key:
            return None
        if self._openrouter is None:
            self._openrouter = OpenRouterClient(api_key=self._openrouter_key)
        return self._openrouter

    async def _ensure_ollama(self) -> bool:
        """Probe Ollama once and cache result."""
        if self._ollama_checked:
            return self._ollama_available
        self._ollama_checked = True
        if self._ollama is None:
            self._ollama = OllamaClient(base_url=self._ollama_url, default_model=self._ollama_model)
        self._ollama_available = await self._ollama.is_available()
        if not self._ollama_available:
            await self._ollama.close()
            self._ollama = None
        return self._ollama_available

    async def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        model: Optional[str] = None,
    ) -> LLMResponse:
        """Try OpenRouter first, then Ollama.

        Returns the first successful response. Raises if both fail.
        """
        or_error: Optional[Exception] = None
        ollama_error: Optional[Exception] = None
        tried_clients: list[str] = []

        # Step 1: Try OpenRouter (if key set)
        or_client = self._get_openrouter()
        if or_client is not None:
            tried_clients.append("openrouter")
            try:
                resp = await or_client.complete(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model,
                )
                # Mark in metadata which client was used
                if resp.metadata is None:
                    resp.metadata = {}
                resp.metadata["client_chain"] = tried_clients
                resp.metadata["primary_client"] = "openrouter"
                return resp
            except Exception as e:
                or_error = e

        # Step 2: Fall back to Ollama
        tried_clients.append("ollama")
        ollama_ok = await self._ensure_ollama()
        if not ollama_ok or self._ollama is None:
            ollama_error = RuntimeError(
                f"Ollama not running at {self._ollama_url}. "
                f"Start with: ollama serve"
            )
        else:
            try:
                resp = await self._ollama.complete(
                    prompt=prompt,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    model=model or self._ollama_model,
                )
                if resp.metadata is None:
                    resp.metadata = {}
                resp.metadata["client_chain"] = tried_clients
                resp.metadata["primary_client"] = "ollama"
                resp.metadata["openrouter_failed"] = (
                    f"{type(or_error).__name__}: {str(or_error)[:200]}"
                    if or_error else None
                )
                return resp
            except Exception as e:
                ollama_error = e

        # Both failed
        or_msg = f"OpenRouter: {type(or_error).__name__}: {str(or_error)[:200]}" if or_error else "OpenRouter: not configured (no OPENROUTER_API_KEY)"
        ol_msg = f"Ollama: {type(ollama_error).__name__}: {str(ollama_error)[:200]}" if ollama_error else "Ollama: not configured"
        raise RuntimeError(
            f"HybridLLMClient: all backends failed.\n  {or_msg}\n  {ol_msg}\n"
            f"  Fix: set OPENROUTER_API_KEY (cloud) OR start Ollama (offline) at {self._ollama_url}"
        )

    async def close(self):
        if self._openrouter is not None:
            try:
                await self._openrouter.close()
            except Exception:
                pass
            self._openrouter = None
        if self._ollama is not None:
            try:
                await self._ollama.close()
            except Exception:
                pass
            self._ollama = None


def make_llm_func(client: Optional[LLMClient] = None, model: str = "auto"):
    """Create a callable that matches the agent's llm_func signature.

    The returned function has signature: (prompt: str, system: Optional[str] = None, **kwargs) -> str
    It can be passed to agents as `agent.llm_func = make_llm_func()`.

    Args:
        client: Pre-built LLMClient. If None, calls get_llm_client().
        model: Model to use (only if client is None).

    Returns:
        Async function suitable for agent.llm_func.
    """
    own_client = client is None
    if own_client:
        client = get_llm_client(model)

    async def llm_func(prompt: str, system: Optional[str] = None, **kwargs) -> str:
        try:
            call_kwargs = {
                "prompt": prompt,
                "system": system,
            }
            if "max_tokens" in kwargs:
                call_kwargs["max_tokens"] = kwargs["max_tokens"]
            else:
                call_kwargs["max_tokens"] = 1024
            if "temperature" in kwargs:
                call_kwargs["temperature"] = kwargs["temperature"]
            if "model" in kwargs and kwargs["model"] is not None:
                call_kwargs["model"] = kwargs["model"]
            resp = await client.complete(**call_kwargs)
            return resp.content
        finally:
            if own_client and hasattr(client, "close"):
                try:
                    await client.close()
                except Exception:
                    pass

    return llm_func


def get_llm_client(model: str = "auto") -> LLMClient:
    """Factory: get appropriate LLM client.

    Priority (default, no env vars):
    1. HybridLLMClient (OpenRouter + Ollama) — RECOMMENDED, best of both worlds
    2. Anthropic (if ANTHROPIC_API_KEY set and model is claude-*)
    3. OpenAI (if OPENAI_API_KEY set and model is gpt-*)
    4. OllamaClient alone (if model matches Ollama naming)

    Args:
        model: "auto" (default), or specific model name
    """
    # Explicit Anthropic/OpenAI model request: honor it
    if model.startswith("claude-"):
        if os.getenv("ANTHROPIC_API_KEY"):
            return AnthropicClient(default_model=model)

    if model.startswith("gpt-"):
        if os.getenv("OPENAI_API_KEY"):
            return OpenAIClient(default_model=model)

    # Explicit Ollama model request: return bare OllamaClient (no hybrid)
    if model == "ollama" or model.startswith(("llama", "qwen", "gemma", "phi", "mistral", "codellama", "deepseek")):
        return OllamaClient(default_model=model)

    # Default: HybridLLMClient (OpenRouter + Ollama fallback)
    return HybridLLMClient()


async def get_llm_client_async() -> LLMClient:
    """Async factory: detect best available LLM at runtime.

    Priority:
    1. HybridLLMClient (OpenRouter + Ollama) — tries OpenRouter first, Ollama as fallback
    2. AnthropicClient (if ANTHROPIC_API_KEY set and model is claude-*)
    3. OpenAIClient (if OPENAI_API_KEY set and model is gpt-*)
    4. OllamaClient (bare, if model matches)
    5. HybridLLMClient anyway (will give clear error if both backends unavailable)
    """
    # Default: HybridLLMClient (best fallback chain)
    return HybridLLMClient()
