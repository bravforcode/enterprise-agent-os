"""Enterprise Agent OS — 18 specialized sub-agents."""
from __future__ import annotations
from typing import Any, Optional
from .base import BaseSubAgent, SubAgentResult
from ..core.logging import get_logger

logger = get_logger("agents")


class Coder(BaseSubAgent):
    name = "coder"
    description = "Write/implement code"
    required_skills = ["rtk-tdd", "test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Write clean, idiomatic code with error handling.", output_key="code", output_extra={"language": "python"})


class Debugger(BaseSubAgent):
    name = "debugger"
    description = "Debug/fix issues"
    required_skills = ["systematic-debugging", "doubt-driven-development"]
    required_tools = ["file_read", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Systematically debug: reproduce, isolate root cause, fix.", output_key="diagnosis")


class Tester(BaseSubAgent):
    name = "tester"
    description = "Write/run tests"
    required_skills = ["rtk-tdd", "test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Write comprehensive pytest tests covering edge cases.", output_key="tests", output_extra={"framework": "pytest"})


class Reviewer(BaseSubAgent):
    name = "reviewer"
    description = "Code review"
    required_skills = ["caveman-review", "requesting-code-review"]
    required_tools = ["file_read"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Review code for correctness, security, performance.", output_key="review")


class Deployer(BaseSubAgent):
    name = "deployer"
    description = "Deployment ops"
    required_skills = ["finishing-a-development-branch"]
    required_tools = ["shell_exec", "git", "deploy"]
    max_tokens = 8192

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Plan deploys with rollback, health checks, risk assessment.", output_key="plan", output_extra={"requires_approval": True})


class Documenter(BaseSubAgent):
    name = "documenter"
    description = "Documentation"
    required_skills = []
    required_tools = ["file_read", "file_write"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Write clear markdown docs with examples.", output_key="docs", output_extra={"format": "markdown"})


class Researcher(BaseSubAgent):
    name = "researcher"
    description = "Research/investigation"
    required_skills = ["web-search", "researcher"]
    required_tools = ["web_search", "file_read"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Research thoroughly, provide structured findings with sources.", output_key="findings")


class DataEngineer(BaseSubAgent):
    name = "data_engineer"
    description = "Data pipelines/ETL"
    required_skills = []
    required_tools = ["file_read", "file_write", "shell_exec", "database_query"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Design data pipelines and ETL with validation.", output_key="pipeline")


class Sysadmin(BaseSubAgent):
    name = "sysadmin"
    description = "System operations"
    required_skills = []
    required_tools = ["shell_exec", "file_read", "file_write"]

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Safe system ops with rollback steps.", output_key="commands")


class Conversational(BaseSubAgent):
    name = "conversational"
    description = "General conversation"
    required_skills = []
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Be helpful, concise, and friendly.", output_key="response")


class General(BaseSubAgent):
    name = "general"
    description = "General purpose fallback"

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Handle any task with practical, well-reasoned responses.", output_key="response")


class Validator(BaseSubAgent):
    name = "validator"
    description = "Validate output"
    required_skills = ["verification-before-completion"]
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        output = context.get("output", "") if context else ""
        issues = []
        if not output:
            issues.append("Empty output")
        if len(output) < 10:
            issues.append("Output too short")
        return SubAgentResult(success=True, output={"valid": len(issues) == 0, "issues": issues, "output_length": len(output)})


class Planner(BaseSubAgent):
    name = "planner"
    description = "Task planning"
    required_skills = ["planning-and-task-breakdown", "writing-plans"]
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Break tasks into ordered steps with estimates.", output_key="plan")


class Architect(BaseSubAgent):
    name = "architect"
    description = "System design"
    required_skills = []
    required_tools = []

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Design systems with components, data flow, trade-offs.", output_key="design")


class SecurityAuditor(BaseSubAgent):
    name = "security_auditor"
    description = "Security analysis"
    required_skills = []
    required_tools = ["file_read", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Identify vulnerabilities, assess severity, recommend OWASP fixes.", output_key="audit")


class DatabaseAdmin(BaseSubAgent):
    name = "database_admin"
    description = "Database schema/queries/migrations"
    required_skills = ["test-driven-development"]
    required_tools = ["file_read", "file_write", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Design schemas, optimize queries, plan migrations.", output_key="sql")


class NetworkEngineer(BaseSubAgent):
    name = "network_engineer"
    description = "Network/DNS/load balancing"
    required_skills = []
    required_tools = ["file_read", "shell_exec"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Design networks, configure DNS, load balancers, firewalls.", output_key="config")


class FrontendDesigner(BaseSubAgent):
    name = "frontend_designer"
    description = "UI/UX/components/a11y"
    required_skills = []
    required_tools = ["file_read", "file_write"]
    max_tokens = 200

    async def execute(self, query: str, context: Optional[dict] = None) -> SubAgentResult:
        return await self.execute_with_llm(query, "Design accessible, responsive UI/UX following WCAG.", output_key="code")


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
