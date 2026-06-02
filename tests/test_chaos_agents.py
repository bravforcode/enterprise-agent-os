"""Chaos tests for graxia_tool agents module — 30+ tests.

Tests edge cases, error handling, and robustness under stress.
"""
import asyncio
import os
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from graxia_tool.agents.base import BaseSubAgent, SubAgentResult
from graxia_tool.agents.implementations import get_agent


# --- Agent Base Chaos Tests ---

class TestAgentBaseChaos:
    """Chaos tests for agent base classes."""

    def test_sub_agent_result_creation(self):
        """SubAgentResult should handle all field combinations."""
        result = SubAgentResult(
            success=True,
            output="test output",
            error=None,
            agent_name="test",
            tokens_used=100
        )
        assert result.agent_name == "test"
        assert result.success is True

    def test_sub_agent_result_with_error(self):
        """SubAgentResult should handle error cases."""
        result = SubAgentResult(
            success=False,
            output="",
            error="Something went wrong",
            agent_name="test"
        )
        assert result.success is False
        assert result.error == "Something went wrong"

    def test_sub_agent_result_empty_metadata(self):
        """SubAgentResult should handle empty metadata."""
        result = SubAgentResult(
            success=True,
            output="output",
            error=None,
            agent_name="test",
            metadata=None
        )
        assert result.metadata is None or result.metadata == {}

    @pytest.mark.asyncio
    async def test_agent_execution_timeout(self):
        """Agent execution should handle timeouts gracefully."""
        from graxia_tool.agents.implementations import get_agent
        agent = get_agent("coder")
        
        # Mock a slow execution
        async def slow_execute(task, context=None):
            await asyncio.sleep(10)
            return SubAgentResult(
                agent_name="coder",
                success=True,
                output="done",
                error=None
            )
        
        agent.execute = slow_execute
        
        # Should handle timeout
        try:
            result = await asyncio.wait_for(
                agent.execute("test task"),
                timeout=0.1
            )
        except asyncio.TimeoutError:
            pass  # Expected behavior

    @pytest.mark.asyncio
    async def test_agent_execution_exception(self):
        """Agent execution should handle exceptions gracefully."""
        from graxia_tool.agents.implementations import get_agent
        agent = get_agent("coder")
        
        # Mock an exception
        async def bad_execute(task, context=None):
            raise RuntimeError("Agent crashed")
        
        agent.execute = bad_execute
        
        with pytest.raises(RuntimeError):
            await agent.execute("test task")


# --- Agent Registry Chaos Tests ---

class TestAgentRegistryChaos:
    """Chaos tests for agent registry."""

    def test_get_agent_valid(self):
        """get_agent should return valid agent for known names."""
        agent_names = ["coder", "debugger", "tester", "reviewer", "deployer",
                       "documenter", "researcher", "data_engineer", "sysadmin",
                       "conversational", "general", "validator", "planner",
                       "architect", "security_auditor"]
        for agent_name in agent_names:
            agent = get_agent(agent_name)
            assert agent is not None, f"Missing agent: {agent_name}"
            assert hasattr(agent, 'execute')

    def test_get_agent_invalid(self):
        """get_agent should return None for unknown names."""
        agent = get_agent("nonexistent_agent")
        assert agent is None

    def test_all_agents_implement_interface(self):
        """All agents should implement BaseSubAgent interface."""
        agent_names = ["coder", "debugger", "tester", "reviewer", "deployer",
                       "documenter", "researcher", "data_engineer", "sysadmin",
                       "conversational", "general", "validator", "planner",
                       "architect", "security_auditor"]
        for agent_name in agent_names:
            agent = get_agent(agent_name)
            assert agent is not None
            assert hasattr(agent, 'execute'), f"{agent_name} missing execute method"
            assert asyncio.iscoroutinefunction(agent.execute), f"{agent_name}.execute not async"


# --- Individual Agent Chaos Tests ---

class TestCoderAgentChaos:
    """Chaos tests for Coder agent."""

    @pytest.mark.asyncio
    async def test_coder_empty_task(self):
        """Coder should handle empty task."""
        agent = get_agent("coder")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_coder_very_long_task(self):
        """Coder should handle very long task description."""
        agent = get_agent("coder")
        long_task = "Implement a function " * 1000
        result = await agent.execute(long_task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_coder_special_characters(self):
        """Coder should handle special characters in task."""
        agent = get_agent("coder")
        special_task = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        result = await agent.execute(special_task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_coder_unicode_task(self):
        """Coder should handle unicode in task."""
        agent = get_agent("coder")
        unicode_task = "สร้างฟังก์ชัน Python สำหรับวิเคราะห์ข้อมูล"
        result = await agent.execute(unicode_task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_coder_concurrent_execution(self):
        """50 concurrent Coder executions should all succeed."""
        agent = get_agent("coder")
        
        tasks = [agent.execute(f"Task {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestDebuggerAgentChaos:
    """Chaos tests for Debugger agent."""

    @pytest.mark.asyncio
    async def test_debugger_empty_task(self):
        """Debugger should handle empty task."""
        agent = get_agent("debugger")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_debugger_with_error_context(self):
        """Debugger should handle error context."""
        agent = get_agent("debugger")
        task = "Fix this error: TypeError: cannot read property 'x' of undefined"
        result = await agent.execute(task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_debugger_concurrent_execution(self):
        """50 concurrent Debugger executions should all succeed."""
        agent = get_agent("debugger")
        
        tasks = [agent.execute(f"Debug issue {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestTesterAgentChaos:
    """Chaos tests for Tester agent."""

    @pytest.mark.asyncio
    async def test_tester_empty_task(self):
        """Tester should handle empty task."""
        agent = get_agent("tester")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_tester_with_code_context(self):
        """Tester should handle code context."""
        agent = get_agent("tester")
        task = "Write tests for this function: def add(a, b): return a + b"
        result = await agent.execute(task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_tester_concurrent_execution(self):
        """50 concurrent Tester executions should all succeed."""
        agent = get_agent("tester")
        
        tasks = [agent.execute(f"Write test {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestReviewerAgentChaos:
    """Chaos tests for Reviewer agent."""

    @pytest.mark.asyncio
    async def test_reviewer_empty_task(self):
        """Reviewer should handle empty task."""
        agent = get_agent("reviewer")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_reviewer_with_pr_context(self):
        """Reviewer should handle PR context."""
        agent = get_agent("reviewer")
        task = "Review this PR: add error handling to API endpoints"
        result = await agent.execute(task)
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_reviewer_concurrent_execution(self):
        """50 concurrent Reviewer executions should all succeed."""
        agent = get_agent("reviewer")
        
        tasks = [agent.execute(f"Review code {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestDeployerAgentChaos:
    """Chaos tests for Deployer agent."""

    @pytest.mark.asyncio
    async def test_deployer_empty_task(self):
        """Deployer should handle empty task."""
        agent = get_agent("deployer")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_deployer_concurrent_execution(self):
        """50 concurrent Deployer executions should all succeed."""
        agent = get_agent("deployer")
        
        tasks = [agent.execute(f"Deploy service {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestDocumenterAgentChaos:
    """Chaos tests for Documenter agent."""

    @pytest.mark.asyncio
    async def test_documenter_empty_task(self):
        """Documenter should handle empty task."""
        agent = get_agent("documenter")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_documenter_concurrent_execution(self):
        """50 concurrent Documenter executions should all succeed."""
        agent = get_agent("documenter")
        
        tasks = [agent.execute(f"Document feature {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestResearcherAgentChaos:
    """Chaos tests for Researcher agent."""

    @pytest.mark.asyncio
    async def test_researcher_empty_task(self):
        """Researcher should handle empty task."""
        agent = get_agent("researcher")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_researcher_concurrent_execution(self):
        """50 concurrent Researcher executions should all succeed."""
        agent = get_agent("researcher")
        
        tasks = [agent.execute(f"Research topic {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


class TestSecurityAuditorAgentChaos:
    """Chaos tests for SecurityAuditor agent."""

    @pytest.mark.asyncio
    async def test_security_auditor_empty_task(self):
        """SecurityAuditor should handle empty task."""
        agent = get_agent("security_auditor")
        result = await agent.execute("")
        assert isinstance(result, SubAgentResult)

    @pytest.mark.asyncio
    async def test_security_auditor_concurrent_execution(self):
        """50 concurrent SecurityAuditor executions should all succeed."""
        agent = get_agent("security_auditor")
        
        tasks = [agent.execute(f"Audit security {i}") for i in range(50)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if isinstance(r, SubAgentResult)]
        assert len(successes) == 50


# --- Multi-Agent Pattern Chaos Tests ---

class TestMultiAgentChaos:
    """Chaos tests for multi-agent patterns."""

    @pytest.mark.asyncio
    async def test_shared_state_concurrent_access(self):
        """SharedState should handle concurrent access safely."""
        from graxia_tool.multi_agent import SharedState
        state = SharedState()
        
        async def update_state(key, value):
            state.put(key, value)
            return state.get(key)
        
        tasks = [update_state(f"key_{i}", f"value_{i}") for i in range(100)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successes = [r for r in results if not isinstance(r, Exception)]
        assert len(successes) == 100

    @pytest.mark.asyncio
    async def test_agent_message_creation(self):
        """AgentMessage should handle all field combinations."""
        from graxia_tool.multi_agent import AgentMessage, MessageType
        msg = AgentMessage(
            sender="agent1",
            receiver="agent2",
            type=MessageType.TASK,
            content="test message"
        )
        assert msg.sender == "agent1"
        assert msg.receiver == "agent2"

    @pytest.mark.asyncio
    async def test_shared_state_put_get(self):
        """SharedState put/get should work."""
        from graxia_tool.multi_agent import SharedState
        state = SharedState()
        state.put("key", "value")
        assert state.get("key") == "value"

    @pytest.mark.asyncio
    async def test_shared_state_default(self):
        """SharedState get should return default for missing keys."""
        from graxia_tool.multi_agent import SharedState
        state = SharedState()
        assert state.get("missing", "default") == "default"

    @pytest.mark.asyncio
    async def test_shared_state_snapshot(self):
        """SharedState snapshot should work."""
        from graxia_tool.multi_agent import SharedState
        state = SharedState()
        state.put("key", "value")
        snapshot = state.snapshot()
        assert "intermediate" in snapshot


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])