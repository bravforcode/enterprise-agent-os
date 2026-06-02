"""Enterprise AI Agent Operating System.

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

__version__ = "0.2.0"

# Lazy imports to avoid loading heavy deps at import time
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
    "run_agent",
]
