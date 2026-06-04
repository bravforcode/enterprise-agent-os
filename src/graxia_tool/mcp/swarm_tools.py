"""MCP tool handlers for the Graxia swarm.

Tools:
- swarm_init(topology, agents, config)
- swarm_run(swarm_id, query, topology_override=None)
- swarm_status(swarm_id)
- federation_init(node_name, port=0) -> starts a FederationServer, returns node_id + port + token
- federation_send(target_node, message_type, payload) -> client.send
- federation_list_peers() -> client.list
- sona_record(intent, agent, success, duration_ms)
- sona_suggest(intent, candidates=None)

All handlers return either _ok({...}) or _err(...) — see mcp.__init__.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import _ok, _err, logger  # type: ignore  # re-use from mcp package


# These globals are populated lazily on first use and shared across calls.
_MANAGER = None
_FED_SERVERS: Dict[str, Any] = {}  # node_id -> FederationServer
_FED_CLIENTS: Dict[str, Any] = {}  # node_id -> FederationClient
_FED_REGISTRY: Optional[Any] = None  # FederationRegistry
_SONA = None  # SONA singleton


def _get_manager():
    global _MANAGER
    if _MANAGER is None:
        from ..swarm.coordinator import MANAGER
        _MANAGER = MANAGER
    return _MANAGER


def _get_sona():
    global _SONA
    if _SONA is None:
        from ..swarm.sona import SONA
        _SONA = SONA()
    return _SONA


def _get_registry():
    global _FED_REGISTRY
    if _FED_REGISTRY is None:
        from ..swarm.federation import FederationRegistry
        _FED_REGISTRY = FederationRegistry()
    return _FED_REGISTRY


# ---------------------------------------------------------------------------
# Swarm
# ---------------------------------------------------------------------------


async def swarm_init(args: Dict[str, Any]) -> Dict[str, Any]:
    """Initialize a swarm and register it in the manager."""
    topology = str(args.get("topology", "hierarchical"))
    agents = args.get("agents") or []
    config = args.get("config") or {}
    auto_register_extended = bool(args.get("auto_register_extended", True))

    if topology not in ("hierarchical", "mesh", "adaptive"):
        return _err(f"Unknown topology: {topology}")

    mgr = _get_manager()
    swarm = mgr.init_swarm(
        topology=topology,
        agents=agents,
        config=config,
        auto_register_extended=auto_register_extended,
    )
    return _ok({
        "swarm_id": swarm.swarm_id,
        "topology": swarm.topology.kind,
        "agent_count": len(swarm.agents_registry),
        "node_count": swarm.topology.node_count(),
    })


async def swarm_run(args: Dict[str, Any]) -> Dict[str, Any]:
    """Run a query through a swarm."""
    swarm_id = str(args.get("swarm_id", ""))
    query = str(args.get("query", ""))
    topology_override = args.get("topology_override")
    preferred_agents = args.get("preferred_agents")
    context = args.get("context") or {}

    if not swarm_id or not query:
        return _err("swarm_id and query are required")

    mgr = _get_manager()
    swarm = mgr.get(swarm_id)
    if swarm is None:
        return _err(f"Unknown swarm_id: {swarm_id}")

    try:
        result = await swarm.run(
            query=query,
            topology_override=topology_override,
            preferred_agents=preferred_agents,
            context=context,
        )
        return _ok({
            "swarm_id": result.swarm_id,
            "intent": result.intent,
            "chosen_agent": result.chosen_agent,
            "worker": result.worker,
            "topology": result.topology,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "duration_ms": result.duration_ms,
            "suggestion_reason": result.suggestion_reason,
        })
    except Exception as e:
        logger.exception("swarm_run failed")
        return _err(f"{type(e).__name__}: {e}")


async def swarm_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get a swarm's status snapshot."""
    swarm_id = str(args.get("swarm_id", ""))
    if not swarm_id:
        return _err("swarm_id is required")
    swarm = _get_manager().get(swarm_id)
    if swarm is None:
        return _err(f"Unknown swarm_id: {swarm_id}")
    return _ok(swarm.status())


# ---------------------------------------------------------------------------
# Federation
# ---------------------------------------------------------------------------


async def federation_init(args: Dict[str, Any]) -> Dict[str, Any]:
    """Start a FederationServer on a port and return its node_id + token."""
    node_name = str(args.get("node_name", ""))
    port = int(args.get("port", 0) or 0)
    host = str(args.get("host", "127.0.0.1"))
    token = args.get("token")  # optional; auto-generated if missing

    from ..swarm.federation import FederationServer

    server = FederationServer(node_id=node_name or None, host=host, port=port, token=token)
    bound_port = server.start()
    _FED_SERVERS[server.node_id] = server
    return _ok({
        "node_id": server.node_id,
        "host": server.host,
        "port": bound_port,
        "token": server.token,
        "is_running": server.is_running(),
    })


async def federation_send(args: Dict[str, Any]) -> Dict[str, Any]:
    """Send a federation message to a peer (host+port or known node_id)."""
    target_node = args.get("target_node")
    target_host = args.get("target_host")
    target_port = args.get("target_port")
    message_type = str(args.get("message_type", ""))
    payload = args.get("payload") or {}
    source_token = args.get("source_token")  # peer authentication token

    if not message_type:
        return _err("message_type is required")

    # Resolve target: explicit host/port or look up by node_id
    if target_node and (not target_host or not target_port):
        server = _FED_SERVERS.get(target_node)
        if server is None:
            return _err(f"Unknown target_node: {target_node}")
        target_host = server.host
        target_port = server.port
        # Use the same token as the target server expects
        if not source_token:
            source_token = server.token
    if not target_host or not target_port:
        return _err("target_host and target_port are required (or known target_node)")

    # Client: reuse one client per token, otherwise create ephemeral
    from ..swarm.federation import FederationClient

    source_node = str(args.get("source_node", "external-client"))
    client = FederationClient(node_id=source_node, token=source_token or "")
    response = client.send((str(target_host), int(target_port)), message_type, payload)
    return _ok({
        "target": {"host": target_host, "port": target_port},
        "message_type": message_type,
        "response": response,
    })


async def federation_list_peers(args: Dict[str, Any]) -> Dict[str, Any]:
    """List known peers across the local federation servers + registry."""
    servers: List[Dict[str, Any]] = []
    for s in _FED_SERVERS.values():
        servers.append({
            "node_id": s.node_id,
            "host": s.host,
            "port": s.port,
            "peer_count": len(s.peers),
            "stats": s.stats(),
        })
    reg = _get_registry()
    return _ok({
        "servers": servers,
        "known_peers": reg.list(),
    })


# ---------------------------------------------------------------------------
# SONA
# ---------------------------------------------------------------------------


async def sona_record(args: Dict[str, Any]) -> Dict[str, Any]:
    """Record an (intent, agent, success, duration_ms) outcome."""
    intent = str(args.get("intent", ""))
    agent = str(args.get("agent", ""))
    success = bool(args.get("success", True))
    duration_ms = float(args.get("duration_ms", 0) or 0)
    if not intent or not agent:
        return _err("intent and agent are required")
    stats = _get_sona().record(intent, agent, success, duration_ms)
    return _ok({
        "intent": intent,
        "agent": agent,
        "stats": stats,
    })


async def sona_suggest(args: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest the best agent for an intent (optionally constrained)."""
    intent = str(args.get("intent", ""))
    candidates = args.get("candidates")
    top_k = int(args.get("top_k", 1) or 1)
    if not intent:
        return _err("intent is required")
    sona = _get_sona()
    if top_k > 1:
        return _ok({"intent": intent, "suggestions": sona.suggest_top_k(intent, k=top_k, candidates=candidates)})
    return _ok({
        "intent": intent,
        "suggestion": sona.suggest(intent, candidates=candidates),
    })


async def sona_stats(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get aggregate SONA stats (helper, not in the spec but useful)."""
    return _ok(_get_sona().stats())


# ---------------------------------------------------------------------------
# Tool specs (used by build_default_registry)
# ---------------------------------------------------------------------------

SWARM_TOOL_SPECS = [
    {
        "name": "swarm_init",
        "description": "Initialize a swarm with a topology and set of agents.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topology": {"type": "string", "enum": ["hierarchical", "mesh", "adaptive"], "default": "hierarchical"},
                "agents": {"type": "array", "items": {"type": "string"}, "description": "Optional list of agent names to expose (default: all)"},
                "config": {"type": "object", "description": "Optional topology config (capacity, fanout, etc.)"},
                "auto_register_extended": {"type": "boolean", "default": True},
            },
        },
        "handler": swarm_init,
        "category": "swarm",
    },
    {
        "name": "swarm_run",
        "description": "Run a query through a swarm. Picks an agent via SONA, dispatches via topology.",
        "input_schema": {
            "type": "object",
            "properties": {
                "swarm_id": {"type": "string"},
                "query": {"type": "string"},
                "topology_override": {"type": "string", "enum": ["hierarchical", "mesh", "adaptive"]},
                "preferred_agents": {"type": "array", "items": {"type": "string"}},
                "context": {"type": "object"},
            },
            "required": ["swarm_id", "query"],
        },
        "handler": swarm_run,
        "category": "swarm",
    },
    {
        "name": "swarm_status",
        "description": "Get a swarm's status: topology, agent statuses, queue depth, SONA intents.",
        "input_schema": {
            "type": "object",
            "properties": {"swarm_id": {"type": "string"}},
            "required": ["swarm_id"],
        },
        "handler": swarm_status,
        "category": "swarm",
    },
    {
        "name": "federation_init",
        "description": "Start a federation server. Returns node_id, host, port, and auth token.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_name": {"type": "string"},
                "port": {"type": "integer", "default": 0, "description": "0 = pick free port"},
                "host": {"type": "string", "default": "127.0.0.1"},
                "token": {"type": "string", "description": "Optional pre-shared token; auto-generated if missing"},
            },
        },
        "handler": federation_init,
        "category": "federation",
    },
    {
        "name": "federation_send",
        "description": "Send a federation message to a peer (host/port or known node_id).",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_node": {"type": "string", "description": "Optional known node_id; resolves to host/port"},
                "target_host": {"type": "string"},
                "target_port": {"type": "integer"},
                "source_node": {"type": "string", "default": "external-client"},
                "source_token": {"type": "string"},
                "message_type": {"type": "string", "description": "e.g. ping, agent_run, swarm_query"},
                "payload": {"type": "object"},
            },
            "required": ["message_type"],
        },
        "handler": federation_send,
        "category": "federation",
    },
    {
        "name": "federation_list_peers",
        "description": "List known federation servers and discovered peers.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": federation_list_peers,
        "category": "federation",
    },
    {
        "name": "sona_record",
        "description": "Record a (intent, agent, success, duration_ms) outcome into SONA-lite.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "agent": {"type": "string"},
                "success": {"type": "boolean", "default": True},
                "duration_ms": {"type": "number", "default": 0},
            },
            "required": ["intent", "agent"],
        },
        "handler": sona_record,
        "category": "learning",
    },
    {
        "name": "sona_suggest",
        "description": "Suggest the best agent for an intent based on rolling success rate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "candidates": {"type": "array", "items": {"type": "string"}},
                "top_k": {"type": "integer", "default": 1, "description": "If > 1 returns a ranked list"},
            },
            "required": ["intent"],
        },
        "handler": sona_suggest,
        "category": "learning",
    },
    {
        "name": "sona_stats",
        "description": "Aggregate SONA stats: per-intent success rate, sample counts.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": sona_stats,
        "category": "learning",
    },
]
