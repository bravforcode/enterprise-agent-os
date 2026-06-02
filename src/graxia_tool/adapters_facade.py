"""Agent OS adapters — facade."""
from .adapters.universal import (
    VAULT_AGENT_MAP,
    expand_vault_agent,
    export_all_tools,
    export_skill_manifest,
    to_anthropic_tools,
    to_gemini_tools,
    to_generic_tools,
    to_openai_tools,
)

__all__ = [
    "VAULT_AGENT_MAP",
    "expand_vault_agent",
    "export_all_tools",
    "export_skill_manifest",
    "to_anthropic_tools",
    "to_gemini_tools",
    "to_generic_tools",
    "to_openai_tools",
]
