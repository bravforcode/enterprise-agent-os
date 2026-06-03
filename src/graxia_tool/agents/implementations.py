"""Enterprise Agent OS — Sub-Agent Implementations.

18 specialized sub-agents:
1. Coder — write/implement code
2. Debugger — debug issues
3. Tester — write tests
4. Reviewer — code review
5. Deployer — deployment
6. Documenter — documentation
7. Researcher — research/investigation
8. DataEngineer — data pipelines
9. Sysadmin — system operations
10. Conversational — chat
11. General — fallback
12. Validator — output validation
13. Planner — task planning
14. Architect — system design
15. SecurityAuditor — security analysis
16. DatabaseAdmin — schema, queries, migrations
17. NetworkEngineer — DNS, load balancing, security
18. FrontendDesigner — UI/UX, components, accessibility
"""
from __future__ import annotations
from typing import Any, Optional
from .base import BaseSubAgent, SubAgentResult
from ..core.logging import get_logger

logger = get_logger("agents")


class Coder(BaseSubAgent):
    name = "coder"
    description = "Write and implement code"
    required_skills = ["rtk-tdd", "test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a coder agent. Write clean, idiomatic, well-structured code. Provide complete working implementations with proper error handling."
        return await self.execute_with_llm(query, system, output_key="code", output_extra={"language": "python"})


class Debugger(BaseSubAgent):
    name = "debugger"
    description = "Debug and fix issues"
    required_skills = ["systematic-debugging", "doubt-driven-development"]
    required_tools = ["file_read", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a debugger agent. Systematically analyze issues, identify root causes, and provide fixes. Use a structured debugging approach."
        return await self.execute_with_llm(query, system, output_key="diagnosis")


class Tester(BaseSubAgent):
    name = "tester"
    description = "Write and run tests"
    required_skills = ["rtk-tdd", "test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a tester agent. Write comprehensive tests using pytest. Cover edge cases, error conditions, and happy paths."
        return await self.execute_with_llm(query, system, output_key="tests", output_extra={"framework": "pytest"})


class Reviewer(BaseSubAgent):
    name = "reviewer"
    description = "Code review"
    required_skills = ["caveman-review", "requesting-code-review"]
    required_tools = ["file_read"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a code reviewer agent. Review code for correctness, security, performance, and best practices. Provide actionable feedback."
        return await self.execute_with_llm(query, system, output_key="review")


class Deployer(BaseSubAgent):
    name = "deployer"
    description = "Deployment operations"
    required_skills = ["finishing-a-development-branch"]
    required_tools = ["shell_exec", "git", "deploy"]
    max_tokens = 8192

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a deployment agent. Plan and execute deployments with rollback strategies, health checks, and risk assessment."
        return await self.execute_with_llm(query, system, output_key="plan", output_extra={"requires_approval": True})


class Documenter(BaseSubAgent):
    name = "documenter"
    description = "Documentation"
    required_skills = []
    required_tools = ["file_read", "file_write"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a documentation agent. Write clear, concise documentation with examples. Use markdown formatting."
        return await self.execute_with_llm(query, system, output_key="docs", output_extra={"format": "markdown"})


class Researcher(BaseSubAgent):
    name = "researcher"
    description = "Research and investigation"
    required_skills = ["web-search", "researcher"]
    required_tools = ["web_search", "file_read"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a research agent. Investigate topics thoroughly and provide well-structured findings. Include relevant details and sources."
        return await self.execute_with_llm(query, system, output_key="findings")


class DataEngineer(BaseSubAgent):
    name = "data_engineer"
    description = "Data pipelines and ETL"
    required_skills = []
    required_tools = ["file_read", "file_write", "shell_exec", "database_query"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a data engineer agent. Design data pipelines, ETL processes, and schemas. Focus on data quality and validation."
        return await self.execute_with_llm(query, system, output_key="pipeline")


class Sysadmin(BaseSubAgent):
    name = "sysadmin"
    description = "System operations"
    required_skills = []
    required_tools = ["shell_exec", "file_read", "file_write"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a systems administrator agent. Manage system operations with safe, verified commands. Include rollback steps."
        return await self.execute_with_llm(query, system, output_key="commands")


class Conversational(BaseSubAgent):
    name = "conversational"
    description = "General conversation"
    required_skills = []
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a conversational agent. Be helpful, concise, and friendly in your responses."
        return await self.execute_with_llm(query, system, output_key="response")


class General(BaseSubAgent):
    name = "general"
    description = "General purpose fallback"

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a general-purpose agent. Handle any task with practical, well-reasoned responses."
        return await self.execute_with_llm(query, system, output_key="response")


class Validator(BaseSubAgent):
    name = "validator"
    description = "Validate output"
    required_skills = ["verification-before-completion"]
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        # Validation logic
        output = context.get("output", "") if context else ""
        issues = []
        if not output:
            issues.append("Empty output")
        if len(output) < 10:
            issues.append("Output too short")
        valid = len(issues) == 0
        return SubAgentResult(
            success=True,
            output={"valid": valid, "issues": issues, "output_length": len(output)},
        )


class Planner(BaseSubAgent):
    name = "planner"
    description = "Task planning"
    required_skills = ["planning-and-task-breakdown", "writing-plans"]
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a planning agent. Break tasks into ordered steps with time estimates and dependencies."
        return await self.execute_with_llm(query, system, output_key="plan")


class Architect(BaseSubAgent):
    name = "architect"
    description = "System design and architecture"
    required_skills = []
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a system architect agent. Design systems with clear components, data flow, and trade-off analysis."
        return await self.execute_with_llm(query, system, output_key="design")


class SecurityAuditor(BaseSubAgent):
    name = "security_auditor"
    description = "Security analysis"
    required_skills = []
    required_tools = ["file_read", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a security auditor agent. Identify vulnerabilities, assess severity, and recommend fixes. Follow OWASP guidelines."
        return await self.execute_with_llm(query, system, output_key="audit")


class DatabaseAdmin(BaseSubAgent):
    """Database administration agent — schema design, queries, migrations, optimization."""
    name = "database_admin"
    description = "Database schema design, query optimization, migrations"
    required_skills = ["test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a database administrator agent. Design schemas, write optimized queries, plan migrations, and tune performance."
        return await self.execute_with_llm(query, system, output_key="sql")


class NetworkEngineer(BaseSubAgent):
    """Network engineering agent — DNS, load balancing, firewalls, CDN."""
    name = "network_engineer"
    description = "Network design, DNS, load balancing, security"
    required_skills = []
    required_tools = ["file_read", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a network engineer agent. Design networks, configure DNS, load balancers, firewalls, and CDN."
        return await self.execute_with_llm(query, system, output_key="config")


class FrontendDesigner(BaseSubAgent):
    """Frontend design agent — UI/UX, components, accessibility, responsive design."""
    name = "frontend_designer"
    description = "UI/UX design, components, accessibility, responsive layouts"
    required_skills = []
    required_tools = ["file_read", "file_write"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        system = "You are a frontend designer agent. Design UI/UX with accessible, responsive components. Follow WCAG guidelines."
        return await self.execute_with_llm(query, system, output_key="code")


# Registry
AGENT_REGISTRY: dict[str, type[BaseSubAgent]] = {
    "coder": Coder,
    "debugger": Debugger,
    "tester": Tester,
    "reviewer": Reviewer,
    "deployer": Deployer,
    "documenter": Documenter,
    "researcher": Researcher,
    "data_engineer": DataEngineer,
    "sysadmin": Sysadmin,
    "conversational": Conversational,
    "general": General,
    "validator": Validator,
    "planner": Planner,
    "architect": Architect,
    "security_auditor": SecurityAuditor,
    "database_admin": DatabaseAdmin,
    "network_engineer": NetworkEngineer,
    "frontend_designer": FrontendDesigner,
}


def get_agent(name: str, **kwargs) -> Optional[BaseSubAgent]:
    """Get an agent by name."""
    cls = AGENT_REGISTRY.get(name)
    if cls:
        return cls(**kwargs)
    return None


def list_agents() -> list[str]:
    """List all available agents."""
    return list(AGENT_REGISTRY.keys())
