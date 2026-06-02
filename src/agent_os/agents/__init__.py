"""Enterprise Agent OS — Sub-Agent Module."""
from .base import BaseSubAgent, SubAgentResult
from .implementations import (
    Coder, Debugger, Tester, Reviewer, Deployer,
    Documenter, Researcher, DataEngineer, Sysadmin,
    Conversational, General, Validator, Planner, Architect, SecurityAuditor,
    AGENT_REGISTRY, get_agent, list_agents,
)

__all__ = [
    "BaseSubAgent",
    "SubAgentResult",
    "Coder", "Debugger", "Tester", "Reviewer", "Deployer",
    "Documenter", "Researcher", "DataEngineer", "Sysadmin",
    "Conversational", "General", "Validator", "Planner", "Architect", "SecurityAuditor",
    "AGENT_REGISTRY",
    "get_agent",
    "list_agents",
]
