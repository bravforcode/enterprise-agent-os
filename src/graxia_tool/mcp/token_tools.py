"""MCP tool handlers for token optimization."""
from __future__ import annotations
from typing import Any, Dict
from ..shared.helpers import _ok, _err
from ..optimization.token_optimizer import get_optimizer


async def token_optimize(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args.get("text", "")
    context = args.get("context", "general")
    if not text:
        return _err("text is required")
    optimizer = get_optimizer()
    optimized = optimizer.optimize(text, context=context)
    return _ok({"original": text, "optimized": optimized, "context": context,
                "changed": text != optimized, "stats": optimizer.get_savings_report()})


async def token_report(args: Dict[str, Any]) -> Dict[str, Any]:
    return _ok(get_optimizer().get_savings_report())


async def token_thai(args: Dict[str, Any]) -> Dict[str, Any]:
    text = args.get("text", "")
    if not text:
        return _err("text is required")
    optimizer = get_optimizer()
    optimized = optimizer.optimize_thai(text)
    return _ok({"original": text, "optimized": optimized,
                "saved_chars": len(text) - len(optimized), "stats": optimizer.get_savings_report()})
