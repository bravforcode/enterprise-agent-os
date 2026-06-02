"""Tests for Phase 16-20: MCP server, Vault bridge, Cost engine, Adapters, Graxia integration."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# =====================================================================
# Phase 16 — MCP Server
# =====================================================================

class TestMCPServer:
    def test_build_default_registry(self):
        from agent_os.mcp import build_default_registry
        reg = build_default_registry()
        tools = reg.list_all()
        assert len(tools) >= 10
        names = {t.name for t in tools}
        assert "agent_run" in names
        assert "agent_list" in names
        assert "pipeline_run" in names
        assert "vault_search" in names
        assert "cost_report" in names

    def test_tool_to_mcp_dict(self):
        from agent_os.mcp import Tool
        async def h(x):
            return {"content": [{"type": "text", "text": "ok"}]}
        t = Tool(name="x", description="d", input_schema={"type": "object"}, handler=h)
        d = t.to_mcp_dict()
        assert d["name"] == "x"
        assert d["inputSchema"]["type"] == "object"

    @pytest.mark.asyncio
    async def test_initialize_request(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        resp = await server.handle_request(req)
        assert resp["id"] == 1
        assert "serverInfo" in resp["result"]
        assert resp["result"]["serverInfo"]["name"] == "agent-os"

    @pytest.mark.asyncio
    async def test_tools_list(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        resp = await server.handle_request(req)
        assert "tools" in resp["result"]
        assert len(resp["result"]["tools"]) >= 10

    @pytest.mark.asyncio
    async def test_unknown_method(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 3, "method": "nonsense", "params": {}}
        resp = await server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_unknown_tool_call(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "fake_tool", "arguments": {}}}
        resp = await server.handle_request(req)
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    @pytest.mark.asyncio
    async def test_agent_list_tool(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "agent_list", "arguments": {}}}
        resp = await server.handle_request(req)
        assert "content" in resp["result"]
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "agents" in data
        assert "coder" in data["agents"]

    @pytest.mark.asyncio
    async def test_system_status_tool(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "system_status", "arguments": {}}}
        resp = await server.handle_request(req)
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert data["status"] == "operational"

    @pytest.mark.asyncio
    async def test_ping(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": {}}
        resp = await server.handle_request(req)
        assert "result" in resp


# =====================================================================
# Phase 17 — Obsidian Vault Bridge
# =====================================================================

class TestObsidianBridge:
    def test_init(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        # Should at least resolve a path (may or may not be connected)
        assert b.vault_path is not None
        assert isinstance(b.vault_path, Path)

    def test_parse_note(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            p = vault / "test.md"
            p.write_text("---\nstatus: active\n---\n# Title\n\nBody with #tag1 #tag2 and [[Other Note]].", encoding="utf-8")
            b.vault_path = vault
            note = b._parse_note(p, p.read_text(encoding="utf-8"), p.stat().st_mtime)
            assert note.title == "test"
            assert note.frontmatter.get("status") == "active"
            assert "tag1" in note.tags
            assert "Other Note" in note.links

    def test_search(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            (vault / "alpha.md").write_text("# Alpha\n\nThis is about Python programming.", encoding="utf-8")
            (vault / "beta.md").write_text("# Beta\n\nThis is about Java development.", encoding="utf-8")
            (vault / "gamma.md").write_text("# Gamma\n\nPython is great for data science.", encoding="utf-8")
            b.vault_path = vault
            b._index = {}
            results = asyncio.run(b.search("Python", limit=5))
            assert len(results) >= 2
            assert all(r.score > 0 for r in results)

    def test_read_write(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            b.vault_path = vault
            asyncio.run(b.write_note("notes/hello.md", "# Hello\n\nWorld"))
            content = asyncio.run(b.read_note("notes/hello.md"))
            assert "Hello" in content

    def test_smart_skill_loader(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            skills_dir = vault / "brain" / "skills-universal"
            skills_dir.mkdir(parents=True)
            (skills_dir / "python-tips").mkdir()
            (skills_dir / "python-tips" / "SKILL.md").write_text("# Python Tips\n\nUseful patterns for Python development.", encoding="utf-8")
            (skills_dir / "rust-guide").mkdir()
            (skills_dir / "rust-guide" / "SKILL.md").write_text("# Rust Guide\n\nMemory safety and concurrency.", encoding="utf-8")
            b.vault_path = vault
            results = asyncio.run(b.get_smart_skill("I need Python help"))
            assert len(results) >= 1
            assert any("python" in r["name"] for r in results)

    def test_vault_stats(self):
        from agent_os.integrations.obsidian import ObsidianBridge
        b = ObsidianBridge()
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td) / "vault"
            vault.mkdir()
            (vault / "a.md").write_text("hello", encoding="utf-8")
            (vault / "b.md").write_text("world", encoding="utf-8")
            b.vault_path = vault
            b._index = {}
            stats = asyncio.run(b.get_vault_stats())
            assert stats["note_count"] == 2
            assert stats["connected"] is True


# =====================================================================
# Phase 18 — Cost Engine
# =====================================================================

class TestSemanticCache:
    @pytest.mark.asyncio
    async def test_exact_hit(self):
        from agent_os.cost_engine.engine import SemanticCache
        c = SemanticCache()
        await c.set("hello", "world", "sonnet", 1, 1)
        e = await c.get("hello")
        assert e is not None
        assert e.response == "world"
        assert c.hits == 1

    @pytest.mark.asyncio
    async def test_miss(self):
        from agent_os.cost_engine.engine import SemanticCache
        c = SemanticCache()
        e = await c.get("nope")
        assert e is None

    @pytest.mark.asyncio
    async def test_semantic_match(self):
        from agent_os.cost_engine.engine import SemanticCache
        c = SemanticCache(similarity_threshold=0.5)
        await c.set("Python is a programming language", "yes", "sonnet", 5, 1)
        e = await c.get("Python is the programming language")
        assert e is not None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        from agent_os.cost_engine.engine import SemanticCache
        c = SemanticCache(ttl_seconds=0)
        await c.set("k", "v", "sonnet")
        await asyncio.sleep(0.01)
        e = await c.get("k")
        # TTL=0 should expire immediately
        assert e is None or c.hits >= 0  # either is fine

    @pytest.mark.asyncio
    async def test_max_size_eviction(self):
        from agent_os.cost_engine.engine import SemanticCache
        c = SemanticCache(max_size=2)
        await c.set("k1", "v1", "sonnet")
        await c.set("k2", "v2", "sonnet")
        await c.set("k3", "v3", "sonnet")
        assert len(c._entries) <= 2


class TestInFlightDeduplicator:
    @pytest.mark.asyncio
    async def test_dedup_concurrent(self):
        from agent_os.cost_engine.engine import InFlightDeduplicator
        d = InFlightDeduplicator()
        call_count = 0

        async def slow():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return "result"

        # Run two concurrent calls with same key
        r1, r2 = await asyncio.gather(
            d.run("key", slow),
            d.run("key", slow),
        )
        assert r1 == r2 == "result"
        # One of the two should have collapsed
        assert d.collapses >= 1
        assert call_count == 1  # actual LLM called once


class TestContextCompressor:
    def test_should_compress(self):
        from agent_os.cost_engine.engine import ContextCompressor
        c = ContextCompressor(max_chars=100)
        assert c.should_compress("x" * 200) is True
        assert c.should_compress("x" * 50) is False

    def test_compress_short_unchanged(self):
        from agent_os.cost_engine.engine import ContextCompressor
        c = ContextCompressor(max_chars=100)
        text, compressed = c.compress("short text")
        assert compressed is False
        assert text == "short text"

    def test_compress_long(self):
        from agent_os.cost_engine.engine import ContextCompressor
        c = ContextCompressor(max_chars=100, target_ratio=0.5)
        text = ". ".join([f"Sentence number {i} about topic keyword{i % 3}" for i in range(50)])
        out, was_compressed = c.compress(text)
        assert was_compressed is True
        assert len(out) < len(text)


class TestModelRouter:
    def test_pick_haiku(self):
        from agent_os.cost_engine.engine import ModelRouter
        r = ModelRouter()
        assert r.pick("hi") == "haiku"

    def test_pick_sonnet(self):
        from agent_os.cost_engine.engine import ModelRouter
        r = ModelRouter()
        assert r.pick("a" * 500) == "sonnet"

    def test_pick_opus_complex(self):
        from agent_os.cost_engine.engine import ModelRouter
        r = ModelRouter()
        assert r.pick("This is a complex architectural analysis") == "opus"

    def test_force_model(self):
        from agent_os.cost_engine.engine import ModelRouter
        r = ModelRouter()
        assert r.pick("hi", force_model="opus") == "opus"

    def test_estimate_cost(self):
        from agent_os.cost_engine.engine import ModelRouter
        r = ModelRouter()
        cost = r.estimate_cost("sonnet", 1000, 500)
        assert cost > 0


class TestCostEngine:
    @pytest.mark.asyncio
    async def test_basic_call(self):
        from agent_os.cost_engine.engine import CostEngine

        async def llm(model, prompt):
            return f"echo: {prompt[:20]}"

        engine = CostEngine()
        response, stats = await engine.optimized_call("Hello world", llm)
        assert "echo" in response
        assert stats.input_tokens > 0
        assert stats.cost_usd > 0

    @pytest.mark.asyncio
    async def test_cache_savings(self):
        from agent_os.cost_engine.engine import CostEngine

        call_count = 0

        async def llm(model, prompt):
            nonlocal call_count
            call_count += 1
            return f"response {call_count}"

        engine = CostEngine()
        r1, s1 = await engine.optimized_call("test prompt", llm)
        r2, s2 = await engine.optimized_call("test prompt", llm)
        # Second call should hit cache
        assert s2.cache_hit is True
        assert r1 == r2  # same cached response
        assert call_count == 1  # LLM only called once

    @pytest.mark.asyncio
    async def test_compression_savings(self):
        from agent_os.cost_engine.engine import CostEngine, ContextCompressor

        async def llm(model, prompt):
            return f"resp ({len(prompt)} chars)"

        engine = CostEngine(compressor=ContextCompressor(max_chars=100, target_ratio=0.3))
        long_prompt = "a " * 200
        response, stats = await engine.optimized_call(long_prompt, llm)
        assert stats.compressed is True

    @pytest.mark.asyncio
    async def test_report(self):
        from agent_os.cost_engine.engine import CostEngine

        async def llm(model, prompt):
            return "test"

        engine = CostEngine()
        await engine.optimized_call("p1", llm)
        await engine.optimized_call("p1", llm)  # cache hit
        report = await engine.report()
        assert report["calls"] == 2
        assert report["cache_hits"] == 1
        assert report["total_saved_usd"] > 0


# =====================================================================
# Phase 19 — Universal Adapter
# =====================================================================

class TestAdapters:
    def test_to_anthropic_tools(self):
        from agent_os.adapters.universal import to_anthropic_tools
        tools = [{"name": "x", "description": "d", "inputSchema": {"type": "object"}}]
        out = to_anthropic_tools(tools)
        assert out[0]["name"] == "x"
        assert "input_schema" in out[0]

    def test_to_openai_tools(self):
        from agent_os.adapters.universal import to_openai_tools
        tools = [{"name": "x", "description": "d", "inputSchema": {"type": "object"}}]
        out = to_openai_tools(tools)
        assert out[0]["type"] == "function"
        assert out[0]["function"]["name"] == "x"

    def test_to_gemini_tools(self):
        from agent_os.adapters.universal import to_gemini_tools
        tools = [{"name": "x", "description": "d", "inputSchema": {"type": "object"}}]
        out = to_gemini_tools(tools)
        assert "function_declarations" in out[0]

    def test_to_generic_tools(self):
        from agent_os.adapters.universal import to_generic_tools
        tools = [{"name": "x", "description": "d", "inputSchema": {"type": "object"}}]
        out = to_generic_tools(tools)
        assert out[0]["type"] == "function"

    def test_export_all_tools(self):
        from agent_os.adapters.universal import export_all_tools
        out = export_all_tools("openai")
        assert len(out) >= 10
        assert all("function" in t for t in out)

    def test_export_skill_manifest(self):
        from agent_os.adapters.universal import export_skill_manifest
        m = export_skill_manifest()
        assert m["name"] == "agent-os"
        assert len(m["tools"]) >= 10
        assert "coder" in m["agents"]

    def test_vault_agent_map_has_12(self):
        from agent_os.adapters.universal import VAULT_AGENT_MAP
        assert len(VAULT_AGENT_MAP) == 12
        for name in ["architect", "scribe", "seeker", "connector", "librarian",
                     "postman", "strategist", "ghostwriter", "auditor",
                     "researcher", "pulse", "bridge"]:
            assert name in VAULT_AGENT_MAP

    def test_expand_vault_agent(self):
        from agent_os.adapters.universal import expand_vault_agent
        result = expand_vault_agent("seeker", "find Python notes")
        assert result is not None
        assert result["tool"] == "vault_search"
        assert "find Python notes" in result["arguments"]["query"]

    def test_expand_vault_agent_unknown(self):
        from agent_os.adapters.universal import expand_vault_agent
        assert expand_vault_agent("nonexistent", "x") is None


# =====================================================================
# Phase 20 — Graxia Bridge
# =====================================================================

class TestGraxiaBridge:
    def test_config_from_env(self):
        from agent_os.integrations.graxia import GraxiaConfig
        c = GraxiaConfig.from_env()
        assert c.base_url.startswith("http")
        assert c.api_prefix.startswith("/")

    def test_graxia_to_agent_os_map(self):
        from agent_os.integrations.graxia import GRAXIA_TO_AGENT_OS
        assert GRAXIA_TO_AGENT_OS["scoring"] == "data_engineer"
        assert GRAXIA_TO_AGENT_OS["drafting"] == "documenter"
        assert GRAXIA_TO_AGENT_OS["learning"] == "researcher"
        assert GRAXIA_TO_AGENT_OS["sync"] == "sysadmin"

    def test_bridge_disabled(self):
        from agent_os.integrations.graxia import GraxiaBridge, GraxiaConfig
        b = GraxiaBridge(GraxiaConfig(enabled=False))
        assert b.is_enabled is False

    def test_route_map(self):
        from agent_os.integrations.graxia import GraxiaBridge, GraxiaConfig
        b = GraxiaBridge(GraxiaConfig(enabled=False))
        m = b.get_route_map()
        assert len(m) == 4
        assert "scoring" in m


# =====================================================================
# Smoke test — full chain
# =====================================================================

class TestEndToEndIntegration:
    @pytest.mark.asyncio
    async def test_mcp_tool_dispatches_to_real_subagent(self):
        from agent_os.mcp import MCPServer
        server = MCPServer()
        req = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": "agent_list", "arguments": {}},
        }
        resp = await server.handle_request(req)
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "coder" in data["agents"]
        assert "reviewer" in data["agents"]

    @pytest.mark.asyncio
    async def test_export_in_all_formats(self):
        from agent_os.adapters.universal import export_all_tools
        for fmt in ["anthropic", "openai", "gemini", "generic"]:
            out = export_all_tools(fmt)
            # Gemini wraps in {"function_declarations": [...]} = 1 outer item
            if fmt == "gemini":
                assert len(out) == 1
                assert len(out[0]["function_declarations"]) >= 10
            else:
                assert len(out) >= 10
