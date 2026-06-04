"""Graxia Tool — Universal AI Agent OS.

Zero-setup AI agent platform:
- No API key required (uses local Ollama by default)
- 18 specialized sub-agents
- MCP server for Claude Desktop, Codex, Gemini, OpenCode
- Web UI, multi-tenancy, plugins, fine-tuning export
- Cost reduction: ~41% measured savings

Quick start:
    pip install graxia-tool
    graxia-install         # One-line setup
    graxia                 # Launch web UI
    graxia-mcp             # Start MCP server
"""
from __future__ import annotations

__version__ = "0.3.0"

# Expose key public API at top level
from .llm import get_llm_client, OllamaClient, AnthropicClient, OpenAIClient, MockLLMClient
from .agents import AGENT_REGISTRY, get_agent, list_agents

__all__ = [
    "__version__",
    "get_llm_client",
    "OllamaClient",
    "AnthropicClient",
    "OpenAIClient",
    "MockLLMClient",
    "AGENT_REGISTRY",
    "get_agent",
    "list_agents",
]
