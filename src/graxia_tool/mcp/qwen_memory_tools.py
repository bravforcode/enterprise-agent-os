"""MCP tools for Qwen-powered memory operations."""
from __future__ import annotations

import json
from typing import Any, Dict

from ..memory.qwen_memory import QwenMemory, QwenClient


def _ok(content: Any) -> Dict[str, Any]:
    text = content if isinstance(content, str) else json.dumps(content, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}]}


def _err(message: str) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": f"ERROR: {message}"}], "isError": True}


QWEN_MEMORY_TOOLS = [
    {
        "name": "qwen_summarize",
        "description": "Summarize a conversation into a compact memory entry using qwen3.5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "messages": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}},
                    "description": "List of message objects with role and content",
                },
            },
            "required": ["messages"],
        },
        "handler": "qwen_summarize",
    },
    {
        "name": "qwen_rerank",
        "description": "Re-rank search results by semantic relevance using qwen3.5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query"},
                "candidates": {"type": "array", "items": {"type": "string"}, "description": "Candidate results to rank"},
            },
            "required": ["query", "candidates"],
        },
        "handler": "qwen_rerank",
    },
    {
        "name": "qwen_categorize",
        "description": "Categorize a memory into task/codebase/preference/learning using qwen3.5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory content to categorize"},
            },
            "required": ["content"],
        },
        "handler": "qwen_categorize",
    },
    {
        "name": "qwen_compress",
        "description": "Compress content to 1 sentence using qwen3.5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Content to compress"},
            },
            "required": ["content"],
        },
        "handler": "qwen_compress",
    },
    {
        "name": "qwen_merge",
        "description": "Merge duplicate memories into one using qwen3.5.",
        "input_schema": {
            "type": "object",
            "properties": {
                "memories": {"type": "array", "items": {"type": "string"}, "description": "Memories to merge"},
            },
            "required": ["memories"],
        },
        "handler": "qwen_merge",
    },
    {
        "name": "qwen_status",
        "description": "Check if qwen3.5 is available for memory operations.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": "qwen_status",
    },
]


async def _qwen_summarize(args: Dict[str, Any]) -> Dict[str, Any]:
    messages = args.get("messages", [])
    if not messages:
        return _err("messages is required")
    qwen = QwenMemory()
    result = qwen.summarize_session(messages)
    return _ok({"summary": result.output, "latency_s": round(result.latency_s, 1), "success": result.success})


async def _qwen_rerank(args: Dict[str, Any]) -> Dict[str, Any]:
    query = args.get("query", "")
    candidates = args.get("candidates", [])
    if not query or not candidates:
        return _err("query and candidates are required")
    qwen = QwenMemory()
    result = qwen.rerank(query, candidates)
    # Parse ranking
    try:
        ranks = [int(x.strip()) - 1 for x in result.output.split(",")]
        reranked = [candidates[i] for i in ranks if 0 <= i < len(candidates)]
    except (ValueError, IndexError):
        reranked = candidates
    return _ok({"ranking": result.output, "reranked": reranked, "latency_s": round(result.latency_s, 1)})


async def _qwen_categorize(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args.get("content", "")
    if not content:
        return _err("content is required")
    qwen = QwenMemory()
    result = qwen.categorize(content)
    return _ok({"category": result.output, "latency_s": round(result.latency_s, 1)})


async def _qwen_compress(args: Dict[str, Any]) -> Dict[str, Any]:
    content = args.get("content", "")
    if not content:
        return _err("content is required")
    qwen = QwenMemory()
    result = qwen.compress(content)
    return _ok({"compressed": result.output, "latency_s": round(result.latency_s, 1)})


async def _qwen_merge(args: Dict[str, Any]) -> Dict[str, Any]:
    memories = args.get("memories", [])
    if not memories or len(memories) < 2:
        return _err("at least 2 memories required")
    qwen = QwenMemory()
    result = qwen.merge_memories(memories)
    return _ok({"merged": result.output, "latency_s": round(result.latency_s, 1)})


async def _qwen_status(args: Dict[str, Any]) -> Dict[str, Any]:
    client = QwenClient()
    available = client.is_available()
    return _ok({"available": available, "model": client.model, "base_url": client.base_url})


QWEN_MEMORY_HANDLERS = {
    "qwen_summarize": _qwen_summarize,
    "qwen_rerank": _qwen_rerank,
    "qwen_categorize": _qwen_categorize,
    "qwen_compress": _qwen_compress,
    "qwen_merge": _qwen_merge,
    "qwen_status": _qwen_status,
}
