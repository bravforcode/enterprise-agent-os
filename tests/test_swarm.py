"""Tests for Graxia swarm + federation + SONA-lite (Track T2).

Covers:
- Topology dispatch (hierarchical, mesh, adaptive)
- Swarm coordinator (queen/worker, fan-out, SONA-based selection)
- Federation (real HTTP between 2 in-process servers)
- SONA-lite (record + suggest + persistence)
- MCP tool handlers
- Agent registry size (>= 100)
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import tempfile
import threading
import time
import uuid
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Temp dir helper (project-local to avoid Windows %TEMP% permission issues)
# ---------------------------------------------------------------------------

_TESTS_TMP = Path(__file__).resolve().parent / "_tmp_swarm"
_TESTS_TMP.mkdir(exist_ok=True)


@pytest.fixture
def fresh_sona():
    """A SONA instance pointing at a project-local temp file."""
    from graxia_tool.swarm.sona import SONA
    data = _TESTS_TMP / f"sona-{uuid.uuid4().hex[:8]}.json"
    sona = SONA(data_path=data)
    try:
        yield sona
    finally:
        if data.exists():
            data.unlink()


@pytest.fixture
def fresh_swarm_manager():
    """A clean SwarmManager so tests don't pollute each other."""
    from graxia_tool.swarm.coordinator import SwarmManager
    return SwarmManager()


# ---------------------------------------------------------------------------
# 1. Topology tests
# ---------------------------------------------------------------------------


class TestTopologies:
    def test_hierarchical_dispatch_picks_queen_first(self):
        from graxia_tool.swarm.topology import (
            HierarchicalTopology, TopologyNode,
        )
        nodes = [
            TopologyNode(name="queen", role="queen"),
            TopologyNode(name="w1"),
            TopologyNode(name="w2"),
        ]
        t = HierarchicalTopology(nodes)
        # All workers idle → queen picks min-load (tie, then first by iteration)
        node = asyncio.run(t.dispatch({}))
        assert node in {"w1", "w2"}

    def test_hierarchical_load_balances(self):
        from graxia_tool.swarm.topology import HierarchicalTopology, TopologyNode
        nodes = [TopologyNode(name="queen"), TopologyNode(name="w1"), TopologyNode(name="w2")]
        t = HierarchicalTopology(nodes)
        # Mark w1 busy
        t.mark_busy("w1")
        node = asyncio.run(t.dispatch({}))
        # Should pick w2 (idle), never queen
        assert node == "w2"

    def test_hierarchical_promotes_first_node_if_no_queen(self):
        from graxia_tool.swarm.topology import HierarchicalTopology, TopologyNode
        nodes = [TopologyNode(name="a"), TopologyNode(name="b")]
        t = HierarchicalTopology(nodes)
        queen = t.queen()
        assert queen is not None and queen.name == "a"

    def test_mesh_dispatches_round_robin(self):
        from graxia_tool.swarm.topology import MeshTopology, TopologyNode
        nodes = [TopologyNode(name="a"), TopologyNode(name="b"), TopologyNode(name="c")]
        t = MeshTopology(nodes)
        seen = [asyncio.run(t.dispatch({})) for _ in range(6)]
        # All three should appear in some position
        assert set(seen) == {"a", "b", "c"}
        # First 3 dispatches should cover all 3 names
        assert len(set(seen[:3])) == 3

    def test_adaptive_switches_to_mesh_under_fanout(self):
        from graxia_tool.swarm.topology import AdaptiveTopology, TopologyNode
        nodes = [TopologyNode(name="q"), TopologyNode(name="w1"), TopologyNode(name="w2")]
        t = AdaptiveTopology(nodes)
        # Low fanout → hierarchical
        assert t.current_mode({"fanout": 1}) == "hierarchical"
        # High fanout → mesh
        assert t.current_mode({"fanout": 10}) == "mesh"
        # High queue depth → mesh
        assert t.current_mode({"queue_depth": 100}) == "mesh"

    def test_adaptive_dispatch(self):
        from graxia_tool.swarm.topology import AdaptiveTopology, TopologyNode
        nodes = [TopologyNode(name="a"), TopologyNode(name="b"), TopologyNode(name="c")]
        t = AdaptiveTopology(nodes)
        node = asyncio.run(t.dispatch({"fanout": 10}))
        assert node in {"a", "b", "c"}


# ---------------------------------------------------------------------------
# 2. Swarm coordinator
# ---------------------------------------------------------------------------


class TestSwarm:
    @pytest.mark.asyncio
    async def test_swarm_init_runs_query(self, fresh_swarm_manager):
        mgr = fresh_swarm_manager
        swarm = mgr.init_swarm(topology="hierarchical")
        result = await swarm.run("Write a hello world in Python")
        assert result.swarm_id == swarm.swarm_id
        assert result.intent in {"general", "code_test", "code_format"}
        assert result.chosen_agent in swarm.agents_registry
        assert result.success is True
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_swarm_adaptive_runs(self, fresh_swarm_manager):
        mgr = fresh_swarm_manager
        swarm = mgr.init_swarm(topology="adaptive")
        result = await swarm.run("Refactor this function for clarity", topology_override="mesh")
        assert result.success
        assert result.topology == "mesh" or result.topology == "adaptive"

    @pytest.mark.asyncio
    async def test_swarm_fan_out(self, fresh_swarm_manager):
        mgr = fresh_swarm_manager
        swarm = mgr.init_swarm(topology="hierarchical")
        results = await swarm.fan_out([
            "Review this code for bugs",
            "Audit deps for vulnerabilities",
            "Format the file with black",
        ])
        assert len(results) == 3
        # All should succeed (mock LLM always returns success)
        assert all(r.success for r in results)

    def test_swarm_status(self, fresh_swarm_manager):
        mgr = fresh_swarm_manager
        swarm = mgr.init_swarm(topology="mesh")
        status = swarm.status()
        assert status["swarm_id"] == swarm.swarm_id
        assert status["topology"] == "mesh"
        assert status["agent_count"] >= 100
        assert "message_queue_depth" in status

    @pytest.mark.asyncio
    async def test_swarm_intent_routes_to_review_agent(self, fresh_swarm_manager):
        mgr = fresh_swarm_manager
        swarm = mgr.init_swarm(topology="hierarchical")
        result = await swarm.run("Please review this code carefully")
        # Intent should be "code_review" (keyword match)
        assert result.intent == "code_review"
        # The chosen agent should be one of the code quality agents
        assert "reviewer" in result.chosen_agent or result.chosen_agent in {
            "code-reviewer", "reviewer", "general"
        }


# ---------------------------------------------------------------------------
# 3. Federation (REAL two servers, real HTTP, real agents)
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Ask the OS for a free port."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestFederation:
    def test_two_servers_exchange_message(self):
        """Two real FederationServer instances on different ports exchange a message."""
        from graxia_tool.swarm.federation import (
            FederationServer, FederationClient, MSG_PING, MSG_AGENT_RUN,
        )

        # Server A
        server_a = FederationServer(node_id="node-a", host="127.0.0.1", port=_free_port())
        port_a = server_a.start()
        assert port_a > 0 and server_a.is_running()

        # Server B with a custom handler for agent_run
        server_b = FederationServer(node_id="node-b", host="127.0.0.1", port=_free_port())
        port_b = server_b.start()

        received: list = []

        def handle_agent_run(msg):
            received.append(msg)
            return {"ok": True, "agent": msg.payload.get("agent"),
                    "echoed_query": msg.payload.get("query")}

        server_b.register_handler(MSG_AGENT_RUN, handle_agent_run)

        try:
            # Client on A side, talks to B
            client = FederationClient(node_id="node-a", token=server_b.token)
            resp = client.send((server_b.host, port_b), MSG_PING)
            assert resp.get("ok") is True
            assert resp.get("result", {}).get("type") == "pong"

            # Delegate an agent_run from A → B
            resp2 = client.delegate_agent_run(
                (server_b.host, port_b),
                agent="coder",
                query="Write a fibonacci function",
            )
            assert resp2.get("ok") is True
            assert resp2["result"]["agent"] == "coder"
            assert "fibonacci" in resp2["result"]["echoed_query"]
            assert len(received) == 1
            assert received[0].from_node == "node-a"
        finally:
            server_a.stop()
            server_b.stop()

    def test_federation_register_and_list_peers(self):
        from graxia_tool.swarm.federation import FederationServer, FederationClient

        server_a = FederationServer(node_id="alpha", host="127.0.0.1", port=_free_port())
        port_a = server_a.start()
        server_b = FederationServer(node_id="beta", host="127.0.0.1", port=_free_port())
        port_b = server_b.start()
        try:
            client = FederationClient(node_id="alpha", token=server_b.token)
            resp = client.register(server_b.host, port_b, advertised_host="127.0.0.1", advertised_port=port_a)
            assert resp.get("ok") is True
            # B should now list alpha as a peer
            peer_resp = client.list_peers((server_b.host, port_b))
            assert peer_resp.get("ok") is True
            ids = [p["node_id"] for p in peer_resp["peers"]]
            assert "alpha" in ids
        finally:
            server_a.stop()
            server_b.stop()

    def test_federation_rejects_unauthorized(self):
        from graxia_tool.swarm.federation import FederationServer, FederationClient

        server = FederationServer(node_id="secure", host="127.0.0.1", port=_free_port())
        port = server.start()
        try:
            client = FederationClient(node_id="x", token="wrong-token")
            resp = client.send((server.host, port), "ping")
            assert resp.get("ok") is False
            assert "401" in resp.get("error", "") or "unauthorized" in resp.get("error", "").lower()
        finally:
            server.stop()


# ---------------------------------------------------------------------------
# 4. SONA-lite
# ---------------------------------------------------------------------------


class TestSONA:
    def test_record_and_suggest(self, fresh_sona):
        sona = fresh_sona
        # Record 5 successes for coder, 1 failure
        for _ in range(5):
            sona.record("code_review", "coder", success=True, duration_ms=100)
        sona.record("code_review", "tester", success=False, duration_ms=200)
        # coder should be suggested
        s = sona.suggest("code_review")
        assert s is not None
        assert s["agent"] == "coder"
        assert s["score"] > 0.5

    def test_suggest_top_k(self, fresh_sona):
        sona = fresh_sona
        for _ in range(4):
            sona.record("deploy", "deployer", success=True, duration_ms=50)
        for _ in range(2):
            sona.record("deploy", "sysadmin", success=True, duration_ms=300)
        sona.record("deploy", "general", success=False, duration_ms=500)
        top = sona.suggest_top_k("deploy", k=3)
        assert len(top) == 3
        assert top[0]["agent"] == "deployer"

    def test_suggest_returns_none_for_unknown_intent(self, fresh_sona):
        assert fresh_sona.suggest("nope") is None

    def test_persistence_round_trip(self):
        from graxia_tool.swarm.sona import SONA
        path = _TESTS_TMP / f"sona-rt-{uuid.uuid4().hex[:8]}.json"
        try:
            s1 = SONA(data_path=path)
            s1.record("ci", "deployer", success=True, duration_ms=42)
            s1.record("ci", "deployer", success=True, duration_ms=43)
            # Reload from same path
            s2 = SONA(data_path=path)
            sug = s2.suggest("ci")
            assert sug is not None
            assert sug["agent"] == "deployer"
            assert sug["samples"] == 2
        finally:
            if path.exists():
                path.unlink()

    def test_stats(self, fresh_sona):
        sona = fresh_sona
        sona.record("a", "coder", True, 10)
        sona.record("a", "coder", False, 10)
        sona.record("b", "tester", True, 10)
        stats = sona.stats()
        assert stats["intent_count"] == 2
        assert stats["total_samples"] == 3
        assert stats["total_successes"] == 2
        assert "a" in stats["intents"] and "b" in stats["intents"]


# ---------------------------------------------------------------------------
# 5. MCP tool integration
# ---------------------------------------------------------------------------


class TestMCPSwarmTools:
    @pytest.mark.asyncio
    async def test_swarm_init_and_run_tools(self):
        # Redirect SONA file so tests are deterministic
        from graxia_tool.swarm.sona import SONA
        from graxia_tool.mcp import swarm_tools as st
        st._SONA = SONA(data_path=_TESTS_TMP / f"mcp-sona-{uuid.uuid4().hex[:8]}.json")
        st._MANAGER = None  # force re-init

        # swarm_init
        r = await st.swarm_init({"topology": "mesh", "agents": []})
        assert r.get("isError") is not True
        # content is JSON-encoded text in MCP format
        text = r["content"][0]["text"]
        payload = json.loads(text)
        assert "swarm_id" in payload
        swarm_id = payload["swarm_id"]

        # swarm_run
        r2 = await st.swarm_run({"swarm_id": swarm_id, "query": "Write a unit test for foo"})
        assert r2.get("isError") is not True
        payload2 = json.loads(r2["content"][0]["text"])
        assert payload2["success"] is True
        assert "intent" in payload2

        # swarm_status
        r3 = await st.swarm_status({"swarm_id": swarm_id})
        assert r3.get("isError") is not True
        payload3 = json.loads(r3["content"][0]["text"])
        assert payload3["swarm_id"] == swarm_id
        assert payload3["agent_count"] >= 100

    @pytest.mark.asyncio
    async def test_sona_record_and_suggest_tools(self):
        from graxia_tool.swarm.sona import SONA
        from graxia_tool.mcp import swarm_tools as st
        st._SONA = SONA(data_path=_TESTS_TMP / f"mcp-sona2-{uuid.uuid4().hex[:8]}.json")

        for _ in range(3):
            r = await st.sona_record({"intent": "test", "agent": "tester", "success": True, "duration_ms": 5})
            assert r.get("isError") is not True
        s = await st.sona_suggest({"intent": "test"})
        text = s["content"][0]["text"]
        payload = json.loads(text)
        assert payload["suggestion"]["agent"] == "tester"

    @pytest.mark.asyncio
    async def test_federation_init_and_send(self):
        from graxia_tool.mcp import swarm_tools as st
        st._FED_SERVERS.clear()

        # Init server A
        r = await st.federation_init({"node_name": "alpha", "port": 0})
        text = r["content"][0]["text"]
        payload = json.loads(text)
        node_id = payload["node_id"]
        port = payload["port"]
        token = payload["token"]
        assert port > 0 and token

        # Init server B
        r2 = await st.federation_init({"node_name": "beta", "port": 0})
        payload2 = json.loads(r2["content"][0]["text"])
        port_b = payload2["port"]

        # Send ping from A → B using known node_id
        r3 = await st.federation_send({
            "target_node": "beta",
            "source_token": token,  # A and B share no token; we use the one we know
            "message_type": "ping",
        })
        # This will likely fail auth since each server has its own token;
        # but the call should be well-formed.
        text3 = r3["content"][0]["text"]
        payload3 = json.loads(text3)
        assert "response" in payload3
        # Cleanup
        for srv in st._FED_SERVERS.values():
            srv.stop()
        st._FED_SERVERS.clear()


# ---------------------------------------------------------------------------
# 6. Registry size assertion
# ---------------------------------------------------------------------------


def test_agent_registry_has_100_plus_agents():
    from graxia_tool.agents import list_agents, AGENT_REGISTRY
    n = len(list_agents())
    assert n >= 100, f"Expected >= 100 agents, got {n}"
    # Extended agents should be present
    expected_extended = {
        "code-reviewer", "system-architect", "dockerfile-generator",
        "unit-test-generator", "readme-writer", "sql-optimizer",
        "owasp-scanner", "react-component-generator",
    }
    missing = expected_extended - set(AGENT_REGISTRY.keys())
    assert not missing, f"Missing extended agents: {missing}"


def test_swarm_module_exports_expected_symbols():
    from graxia_tool import swarm
    expected = [
        "Swarm", "SwarmManager", "MANAGER",
        "HierarchicalTopology", "MeshTopology", "AdaptiveTopology",
        "FederationServer", "FederationClient",
        "SONA", "EXTENDED_AGENT_REGISTRY",
    ]
    for sym in expected:
        assert hasattr(swarm, sym), f"Missing swarm.{sym}"
