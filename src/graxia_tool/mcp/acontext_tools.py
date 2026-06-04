"""MCP tool handlers for the Acontext-style skill memory module.

Five tools are registered in :func:`build_default_registry`:

* ``acontext_learn``         — distill a session into skill files
* ``acontext_list_skills``   — list all skills in a space
* ``acontext_recall``        — BM25 (+ optional LLM re-rank) search
* ``acontext_get_skill``     — read a full skill by name
* ``acontext_delete_skill``  — remove a skill from a space

All handlers return the standard ``_ok({...})`` / ``_err(...)`` shape
from :mod:`graxia_tool.shared.helpers`. They are async because the
distiller and re-ranker make LLM calls.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..shared.helpers import _ok, _err


# Tools defined in this module. Imported lazily by build_default_registry().
ACONTEXT_TOOLS: List[Dict[str, Any]] = []


def _ensure_selector_loop() -> None:
    """Set the Windows SelectorEventLoop policy (mirrors ``mcp.__main__``)."""
    if sys.platform == "win32":
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LLM client helper
# ---------------------------------------------------------------------------

def _get_llm_client() -> Any:
    """Resolve an LLM client. Uses HybridLLMClient (OpenRouter → Ollama).

    Tests can monkeypatch this function to return a stub or to skip
    the import path.
    """
    from ..llm import HybridLLMClient
    return HybridLLMClient()


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

async def acontext_learn(args: Dict[str, Any]) -> Dict[str, Any]:
    """Distill a session into skill files."""
    from ..acontext import Distiller, SkillStore  # local import to avoid cycles

    space = (args.get("space") or "").strip()
    if not space:
        return _err("space is required")

    session_messages = args.get("session_messages") or []
    if not isinstance(session_messages, list):
        return _err("session_messages must be a list of {role, content} dicts")

    outcome = (args.get("outcome") or "success").strip()
    outcome_note = (args.get("outcome_note") or "").strip()
    source_session = (args.get("source_session") or "").strip()
    save = bool(args.get("save", True))
    base_dir = args.get("base_dir")  # optional override (used in tests)
    dry_run = bool(args.get("dry_run", False))

    try:
        client = _get_llm_client()
        store_factory = (lambda s: SkillStore(s, base_dir=Path(base_dir))) if base_dir else SkillStore
        distiller = Distiller(client, store_factory=store_factory)
        result = await distiller.distill(
            space=space,
            session_messages=session_messages,
            outcome=outcome,
            outcome_note=outcome_note,
            source_session=source_session,
            save=save and not dry_run,
        )
        return _ok({
            "space": result.space,
            "saved": [m.to_dict() for m in result.saved],
            "skill_count": len(result.skills),
            "errors": result.errors,
            "raw_response": result.raw_response[:2000],
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def acontext_list_skills(args: Dict[str, Any]) -> Dict[str, Any]:
    """List all skills in a space."""
    from ..acontext import SkillStore

    space = (args.get("space") or "").strip()
    if not space:
        return _err("space is required")
    base_dir = args.get("base_dir")

    try:
        store = SkillStore(space, base_dir=Path(base_dir)) if base_dir else SkillStore(space)
        metas = store.list_metadata()
        return _ok({
            "space": space,
            "count": len(metas),
            "skills": [
                {
                    "name": m.name,
                    "description": m.description,
                    "tags": m.tags,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                    "version": m.version,
                    "source_session": m.source_session,
                }
                for m in metas
            ],
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def acontext_recall(args: Dict[str, Any]) -> Dict[str, Any]:
    """BM25 (and optional LLM re-rank) over skill files."""
    from ..acontext import recall_skills, SkillStore

    space = (args.get("space") or "").strip()
    query = (args.get("query") or "").strip()
    limit = int(args.get("limit", 5))
    if not space:
        return _err("space is required")
    if not query:
        return _err("query is required")

    rerank = bool(args.get("rerank", False))
    base_dir = args.get("base_dir")

    try:
        store = SkillStore(space, base_dir=Path(base_dir)) if base_dir else SkillStore(space)
        client = _get_llm_client() if rerank else None
        hits = recall_skills(store, query, limit=limit, rerank=rerank, llm_client=client)
        return _ok({
            "space": space,
            "query": query,
            "count": len(hits),
            "rerank": rerank,
            "results": [
                {
                    "name": h.skill.meta.name,
                    "description": h.skill.meta.description,
                    "tags": h.skill.meta.tags,
                    "score": round(h.score, 4),
                    "bm25_rank": h.bm25_rank,
                    "rerank_score": (round(h.rerank_score, 4) if h.rerank_score is not None else None),
                    "body": h.skill.body,
                }
                for h in hits
            ],
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def acontext_get_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read a full skill by name."""
    from ..acontext import SkillStore

    space = (args.get("space") or "").strip()
    name = (args.get("name") or "").strip()
    base_dir = args.get("base_dir")
    if not space:
        return _err("space is required")
    if not name:
        return _err("name is required")

    try:
        store = SkillStore(space, base_dir=Path(base_dir)) if base_dir else SkillStore(space)
        skill = store.get(name)
        if skill is None:
            return _err(f"skill {name!r} not found in space {space!r}")
        return _ok({
            "space": space,
            "name": skill.meta.name,
            "description": skill.meta.description,
            "tags": skill.meta.tags,
            "created_at": skill.meta.created_at,
            "updated_at": skill.meta.updated_at,
            "version": skill.meta.version,
            "source_session": skill.meta.source_session,
            "body": skill.body,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def acontext_delete_skill(args: Dict[str, Any]) -> Dict[str, Any]:
    """Delete a skill by name."""
    from ..acontext import SkillStore

    space = (args.get("space") or "").strip()
    name = (args.get("name") or "").strip()
    base_dir = args.get("base_dir")
    if not space:
        return _err("space is required")
    if not name:
        return _err("name is required")

    try:
        store = SkillStore(space, base_dir=Path(base_dir)) if base_dir else SkillStore(space)
        removed = store.delete(name)
        return _ok({
            "space": space,
            "name": name,
            "removed": removed,
        })
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------

ACONTEXT_TOOLS = [
    {
        "name": "acontext_learn",
        "description": "Distill a completed session into one or more SKILL.md files in the given space. Uses an LLM pass to extract what worked, what failed, and reusable rules.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name (e.g. 'coding', 'support', 'agent-self')."},
                "session_messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "Ordered list of session messages as {role, content} dicts.",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["success", "failure", "partial", "unknown"],
                    "default": "success",
                    "description": "Outcome label of the session.",
                },
                "outcome_note": {
                    "type": "string",
                    "description": "Free-form note about the outcome (e.g. error summary).",
                },
                "source_session": {
                    "type": "string",
                    "description": "Optional id of the source session (e.g. UUID).",
                },
                "save": {
                    "type": "boolean",
                    "default": True,
                    "description": "If False, only return extracted skills without writing to disk.",
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "If True, never write to disk (implies save=False).",
                },
            },
            "required": ["space", "session_messages"],
        },
        "handler": acontext_learn,
        "category": "acontext",
    },
    {
        "name": "acontext_list_skills",
        "description": "List all skills in a space (metadata only, no body).",
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name."},
            },
            "required": ["space"],
        },
        "handler": acontext_list_skills,
        "category": "acontext",
    },
    {
        "name": "acontext_recall",
        "description": "Search a space's skills for a query. Uses BM25 (no embeddings). Set rerank=True to also ask an LLM to re-rank the top hits.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name."},
                "query": {"type": "string", "description": "Free-text query."},
                "limit": {"type": "integer", "default": 5, "description": "Max results."},
                "rerank": {"type": "boolean", "default": False, "description": "LLM re-rank the top hits."},
            },
            "required": ["space", "query"],
        },
        "handler": acontext_recall,
        "category": "acontext",
    },
    {
        "name": "acontext_get_skill",
        "description": "Read a single skill by name (returns full body and metadata).",
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name."},
                "name": {"type": "string", "description": "Skill name (kebab-case)."},
            },
            "required": ["space", "name"],
        },
        "handler": acontext_get_skill,
        "category": "acontext",
    },
    {
        "name": "acontext_delete_skill",
        "description": "Delete a skill by name from a space.",
        "input_schema": {
            "type": "object",
            "properties": {
                "space": {"type": "string", "description": "Space name."},
                "name": {"type": "string", "description": "Skill name (kebab-case)."},
            },
            "required": ["space", "name"],
        },
        "handler": acontext_delete_skill,
        "category": "acontext",
    },
]
