"""Graxia Tool — Track T5 Integration Layer.

Wires T1-T4 features into a single, user-facing integration surface:

- T1: Acontext skill memory  -> graxia_tool.acontext
- T2: Ruflo swarm + 100+ agents  -> graxia_tool.swarm
- T3: ANUS autonomous mode  -> graxia_tool.autonomous
- T4: Faker data generators  -> graxia_tool.faker

This module is the *integration glue* between the four parallel tracks
and the rest of the Graxia Tool stack. It is deliberately thin and
defensive: when a track's package is missing (subagent hasn't shipped
yet), a minimal fallback is exercised so the public API still works.

The MCP server (``graxia_tool.mcp``) already wires the real T1-T4
``*_TOOLS`` lists into its default registry, so this module's
:func:`register_all_tools` only needs to add the cross-cutting
``integration_status`` tool and a few fallback entries (used only when
the MCP server is built *without* the real track modules).

Public API:
    register_all_tools(registry)   — one-shot registration of T1-T4 tools
    get_all_agents()               — return all available agent names
    verify_installation()          — sanity check (deps, providers, tracks)
    run_smoke_test()               — exercise 1 tool from each track
    get_track_status()             — track availability + import errors

T1-T4 subagents can register their own tools by either:
1. Adding their ``*_TOOLS`` list to :mod:`graxia_tool.mcp.build_default_registry`
   (preferred — no changes needed here), or
2. Calling :func:`upsert_tool` from this module which replaces existing
   entries by name (handy for late overrides).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import shutil
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("graxia_tool.integrate")

# ---------------------------------------------------------------------------
# Track metadata
# ---------------------------------------------------------------------------

TRACKS: Dict[str, Dict[str, Any]] = {
    "T1": {
        "name": "Acontext skill memory",
        "module": "graxia_tool.acontext",
        "category": "acontext",
        "fast_tool": ("acontext_list_skills", {"space": "default"}),
        "tools": [
            "acontext_learn", "acontext_recall", "acontext_list_skills",
            "acontext_get_skill", "acontext_delete_skill",
        ],
    },
    "T2": {
        "name": "Ruflo swarm + 100+ agents",
        "module": "graxia_tool.swarm",
        "category": "swarm",
        "fast_tool": ("swarm_init", {"topology": "hierarchical", "agents": []}),
        "tools": [
            "swarm_init", "swarm_run", "swarm_status",
            "federation_init", "federation_send", "federation_list_peers",
            "sona_record", "sona_suggest", "sona_stats",
        ],
    },
    "T3": {
        "name": "ANUS autonomous mode",
        "module": "graxia_tool.autonomous",
        "category": "autonomous",
        "fast_tool": ("autonomous_list_runs", {"limit": 5}),
        "tools": [
            "context_load", "context_save", "context_update",
            "autonomous_plan", "autonomous_run", "autonomous_status",
            "autonomous_list_runs",
        ],
    },
    "T4": {
        "name": "Faker data generators",
        "module": "graxia_tool.faker",
        "category": "faker",
        "fast_tool": ("faker_locales", {}),
        "tools": [
            "faker_generate", "faker_schema", "faker_locales",
        ],
    },
}


# ---------------------------------------------------------------------------
# Track import probe
# ---------------------------------------------------------------------------


def _try_import_track(track: str) -> Tuple[bool, Optional[BaseException], Any]:
    """Try to import a track's real module. Returns (ok, error, module)."""
    import importlib
    module_name = TRACKS[track]["module"]
    try:
        mod = importlib.import_module(module_name)
        return True, None, mod
    except Exception as e:
        return False, e, None


def get_track_status() -> Dict[str, Any]:
    """Return availability status for each track."""
    out: Dict[str, Any] = {}
    for tid, meta in TRACKS.items():
        ok, err, mod = _try_import_track(tid)
        out[tid] = {
            "name": meta["name"],
            "module": meta["module"],
            "available": bool(ok),
            "error": (None if ok else f"{type(err).__name__}: {err}") if err else None,
            "tools_expected": list(meta["tools"]),
        }
    return out


# ---------------------------------------------------------------------------
# Tool upsert helper (idempotent registration)
# ---------------------------------------------------------------------------


def upsert_tool(registry: Any, tool: Any) -> None:
    """Register ``tool`` in ``registry``, replacing any existing entry.

    Falls back to direct dictionary assignment so callers don't have to
    know whether ``registry`` exposes a public upsert.
    """
    name = getattr(tool, "name", None)
    if name is None:
        raise ValueError("Tool must have a .name attribute")
    if hasattr(registry, "upsert"):
        registry.upsert(tool)
        return
    tools = getattr(registry, "_tools", None)
    if isinstance(tools, dict):
        tools[name] = tool
        return
    try:
        registry.register(tool)
    except ValueError:
        tools = getattr(registry, "_tools", None)
        if isinstance(tools, dict):
            tools[name] = tool
        else:
            raise


# ---------------------------------------------------------------------------
# Fallback tool implementations (only used when MCP server is built
# without the real T1-T4 packages — normally the MCP registry already
# contains the real tools).
# ---------------------------------------------------------------------------


async def _fallback_acontext_recall(args: Dict[str, Any]) -> Dict[str, Any]:
    from .shared.helpers import _ok, _err
    from .session_memory import SessionMemory
    query = args.get("query", "")
    limit = int(args.get("limit", 5))
    if not query:
        return _err("query is required")
    try:
        mem = SessionMemory()
        results = mem.recall(query, limit=limit)
        return _ok({
            "results": [
                {"id": r.memory_id, "content": r.content, "type": r.memory_type,
                 "score": round(r.score, 3), "created_at": r.created_at}
                for r in results
            ],
            "count": len(results),
            "track": "T1",
            "fallback": True,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def _fallback_swarm_status(args: Dict[str, Any]) -> Dict[str, Any]:
    from .shared.helpers import _ok, _err
    from .agents import list_agents
    try:
        real = list_agents()
        return _ok({
            "track": "T2",
            "status": "fallback",
            "real_agents": len(real),
            "fallback": True,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def _fallback_autonomous_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    from .shared.helpers import _ok, _err
    goal = args.get("goal", "")
    if not goal:
        return _err("goal is required")
    return _ok({
        "track": "T3",
        "goal": goal,
        "steps": [
            f"1. Analyze: {goal}",
            "2. Gather context (memory_recall)",
            "3. Execute (agent_run)",
            "4. Verify (learning_record)",
        ],
        "fallback": True,
    })


async def _fallback_faker_generate(args: Dict[str, Any]) -> Dict[str, Any]:
    from .shared.helpers import _ok, _err
    category = args.get("category", "person")
    count = max(1, min(int(args.get("count", 1)), 100))
    if not category:
        return _err("category is required")
    items = [f"{category}-{i + 1}" for i in range(count)]
    return _ok({"track": "T4", "category": category, "count": count, "results": items, "fallback": True})


def _fallback_tool_defs() -> List[Dict[str, Any]]:
    from .mcp import Tool
    return [
        Tool(
            name="acontext_recall",
            description="T1 fallback: recall memories by query (uses SessionMemory).",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 5}},
                "required": ["query"],
            },
            handler=_fallback_acontext_recall,
            category="acontext",
        ),
        Tool(
            name="swarm_status",
            description="T2 fallback: minimal swarm status (real agents only).",
            input_schema={"type": "object", "properties": {}},
            handler=_fallback_swarm_status,
            category="swarm",
        ),
        Tool(
            name="autonomous_plan",
            description="T3 fallback: build a 4-step plan for a goal (no LLM).",
            input_schema={
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
            handler=_fallback_autonomous_plan,
            category="autonomous",
        ),
        Tool(
            name="faker_generate",
            description="T4 fallback: generate synthetic placeholders.",
            input_schema={
                "type": "object",
                "properties": {
                    "category": {"type": "string", "default": "person"},
                    "count": {"type": "integer", "default": 1},
                },
            },
            handler=_fallback_faker_generate,
            category="faker",
        ),
    ]


# ---------------------------------------------------------------------------
# Integration status tool (cross-cutting)
# ---------------------------------------------------------------------------


async def _integration_status(args: Dict[str, Any]) -> Dict[str, Any]:
    from .shared.helpers import _ok
    return _ok({
        "tracks": get_track_status(),
        "version": "0.3.0",
        "started_at": _INTEGRATE_START_TIME,
        "uptime_s": int(time.time() - _INTEGRATE_START_TIME),
    })


_INTEGRATE_START_TIME = time.time()


# ---------------------------------------------------------------------------
# Public API: register_all_tools
# ---------------------------------------------------------------------------


def register_all_tools(registry: Any, replace: bool = True) -> Dict[str, int]:
    """One-shot registration of T1-T4 tools into ``registry``.

    The MCP server's :func:`build_default_registry` already imports the
    real T1-T4 ``*_TOOLS`` lists. This function therefore only needs to:

    1. Add the cross-cutting ``integration_status`` tool.
    2. If a real track module is *missing*, register its fallback tool
       so the registry always exposes a tool named ``acontext_recall``,
       ``swarm_status``, ``autonomous_plan`` and ``faker_generate``.

    ``replace=True`` ensures we never raise on duplicate names.
    """
    counts: Dict[str, int] = {"integration_status": 0}
    from .mcp import Tool

    # Cross-cutting integration status
    upsert_tool(registry, Tool(
        name="integration_status",
        description="T5: Return availability of T1-T4 tracks and integration uptime.",
        input_schema={"type": "object", "properties": {}},
        handler=_integration_status,
        category="integration",
    ))
    counts["integration_status"] = 1

    # Add fallbacks only for tracks whose real module is absent
    for track, meta in TRACKS.items():
        ok, _err, _mod = _try_import_track(track)
        if ok:
            counts[track] = 0
            continue
        for tool in _fallback_tool_defs():
            if tool.category == meta["category"]:
                if replace:
                    upsert_tool(registry, tool)
                else:
                    try:
                        registry.register(tool)
                    except ValueError:
                        pass
                counts[track] = counts.get(track, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Public API: get_all_agents
# ---------------------------------------------------------------------------


def get_all_agents() -> Dict[str, Any]:
    """Return all available agents (real + T2 extended pool)."""
    out: Dict[str, Any] = {"real": [], "real_classes": [], "pool": []}
    try:
        from .agents import list_agents, AGENT_REGISTRY
        out["real"] = list_agents()
        out["real_classes"] = list(AGENT_REGISTRY.keys())
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    try:
        from .swarm.agents_extended import list_extended_agents  # type: ignore
        out["extended"] = list_extended_agents()
    except Exception:
        out["extended"] = []
    try:
        from .swarm.sona import SONA  # type: ignore
        sona = SONA()
        out["sona_known"] = len(getattr(sona, "_stats", {}) or {})
    except Exception:
        out["sona_known"] = 0
    out["pool_size"] = len(out["extended"])
    out["total"] = len(out["real"]) + len(out["extended"])
    return out


# ---------------------------------------------------------------------------
# Public API: verify_installation
# ---------------------------------------------------------------------------


def verify_installation() -> Dict[str, Any]:
    """Sanity-check core dependencies, providers, and T1-T4 tracks."""
    info: Dict[str, Any] = {
        "ok": True,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "version": "0.3.0",
        "checks": {},
    }

    # Ollama presence
    ollama_installed = bool(shutil.which("ollama"))
    info["checks"]["ollama_installed"] = ollama_installed

    # Ollama /api/tags probe (sync, short timeout)
    ollama_running = False
    ollama_models = 0
    if ollama_installed:
        try:
            import httpx  # type: ignore
            r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.5)
            if r.status_code == 200:
                ollama_running = True
                ollama_models = len(r.json().get("models", []))
        except Exception:
            ollama_running = False
    info["checks"]["ollama_running"] = ollama_running
    info["checks"]["ollama_models"] = ollama_models

    # OpenRouter key (optional)
    info["checks"]["openrouter_key"] = bool(os.environ.get("OPENROUTER_API_KEY"))

    # Required Python packages
    required = ["pydantic", "httpx", "sqlalchemy", "redis", "fastapi"]
    missing: List[str] = []
    for mod_name in required:
        try:
            __import__(mod_name)
        except Exception:
            missing.append(mod_name)
    info["checks"]["missing_packages"] = missing

    # Tracks
    info["tracks"] = get_track_status()

    # Agent counts
    try:
        from .agents import AGENT_REGISTRY
        info["checks"]["agents_loaded"] = len(AGENT_REGISTRY)
    except Exception as e:
        info["checks"]["agents_loaded"] = 0
        info["checks"]["agents_error"] = f"{type(e).__name__}: {e}"

    # MCP tool count
    try:
        from .mcp import build_default_registry
        reg = build_default_registry()
        register_all_tools(reg)
        info["checks"]["mcp_tool_count"] = len(reg.list_all())
        tool_names = sorted(t.name for t in reg.list_all())
        info["checks"]["mcp_tool_names"] = tool_names
    except Exception as e:
        info["checks"]["mcp_tool_count"] = 0
        info["checks"]["mcp_error"] = f"{type(e).__name__}: {e}"

    info["ok"] = (
        not missing
        and info["checks"]["agents_loaded"] >= 1
        and info["checks"]["mcp_tool_count"] >= 50
    )
    return info


# ---------------------------------------------------------------------------
# Public API: run_smoke_test
# ---------------------------------------------------------------------------


async def run_smoke_test(verbose: bool = True) -> Dict[str, Any]:
    """Exercise one *fast* tool from each track and return a report."""
    from .mcp import build_default_registry

    started = time.time()
    reg = build_default_registry()
    register_all_tools(reg)
    report: Dict[str, Any] = {
        "tracks": {},
        "tool_count": len(reg.list_all()),
        "duration_ms": 0,
        "ok": True,
    }
    for track, meta in TRACKS.items():
        tool_name, args = meta["fast_tool"]
        t0 = time.time()
        tool = reg.get(tool_name)
        if not tool:
            report["tracks"][track] = {"ok": False, "error": "tool_missing",
                                        "tool": tool_name}
            report["ok"] = False
            continue
        try:
            res = await tool.handler(args)
            ok = (
                isinstance(res, dict)
                and "content" in res
                and not res.get("isError")
            )
            preview = ""
            if isinstance(res, dict) and res.get("content"):
                first = res["content"][0]
                if isinstance(first, dict) and "text" in first:
                    preview = str(first["text"])[:160]
            report["tracks"][track] = {
                "ok": ok,
                "tool": tool_name,
                "duration_ms": int((time.time() - t0) * 1000),
                "preview": preview,
            }
            if not ok:
                report["ok"] = False
        except Exception as e:
            report["tracks"][track] = {
                "ok": False,
                "tool": tool_name,
                "error": f"{type(e).__name__}: {e}",
                "duration_ms": int((time.time() - t0) * 1000),
            }
            report["ok"] = False
    report["duration_ms"] = int((time.time() - started) * 1000)
    if verbose:
        _print_smoke_report(report)
    return report


def _print_smoke_report(report: Dict[str, Any]) -> None:
    print("=" * 64)
    print("  Graxia Tool — Track T5 Integration Smoke Test")
    print("=" * 64)
    print(f"  Tool count: {report['tool_count']}")
    print(f"  Total time: {report['duration_ms']} ms")
    print()
    for tid, tr in report["tracks"].items():
        status = "OK  " if tr.get("ok") else "FAIL"
        meta = TRACKS.get(tid, {})
        name = meta.get("name", tid)
        print(f"  [{status}] {tid} {name}")
        if tr.get("tool"):
            print(f"          tool:     {tr['tool']}")
        if tr.get("duration_ms") is not None:
            print(f"          duration: {tr['duration_ms']} ms")
        if tr.get("error"):
            print(f"          error:    {tr['error']}")
        elif tr.get("preview"):
            preview = tr["preview"].replace("\n", " ")[:90]
            print(f"          preview:  {preview}...")
    print()
    print("=" * 64)
    print("  RESULT:", "ALL TRACKS OK" if report["ok"] else "SOME TRACKS FAILED")
    print("=" * 64)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="graxia-integration",
        description="Graxia Tool — Track T5 integration glue",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("verify", help="Check installation (deps, providers, tracks)")
    sub.add_parser("smoke", help="Run a one-tool-per-track smoke test")
    sub.add_parser("status", help="Show T1-T4 track availability")

    agents_cmd = sub.add_parser("agents", help="List all available agents")
    agents_cmd.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()

    if args.cmd == "verify":
        info = verify_installation()
        print(json.dumps(info, indent=2, default=str))
        return 0 if info["ok"] else 1

    if args.cmd == "smoke":
        report = asyncio.run(run_smoke_test(verbose=True))
        return 0 if report["ok"] else 2

    if args.cmd == "status":
        print(json.dumps(get_track_status(), indent=2, default=str))
        return 0

    if args.cmd == "agents":
        agents = get_all_agents()
        if args.limit > 0 and "extended" in agents:
            agents["extended"] = agents["extended"][: args.limit]
        print(json.dumps(agents, indent=2, default=str))
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
