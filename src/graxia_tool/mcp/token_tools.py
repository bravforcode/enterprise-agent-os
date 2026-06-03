"""MCP tool handlers for token optimization."""
from __future__ import annotations

import json
from typing import Any, Dict

from ..optimization.token_optimizer import get_optimizer


async def token_optimize(args: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize a command or text for token savings."""
    from ..mcp import _ok, _err

    text = args.get("text", "")
    context = args.get("context", "general")

    if not text:
        return _err("text is required")

    optimizer = get_optimizer()
    optimized = optimizer.optimize(text, context=context)

    return _ok({
        "original": text,
        "optimized": optimized,
        "context": context,
        "changed": text != optimized,
        "stats": optimizer.get_savings_report(),
    })


async def token_report(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get token savings statistics."""
    from ..mcp import _ok

    optimizer = get_optimizer()
    return _ok(optimizer.get_savings_report())


async def token_thai(args: Dict[str, Any]) -> Dict[str, Any]:
    """Optimize Thai text for token savings."""
    from ..mcp import _ok, _err

    text = args.get("text", "")
    if not text:
        return _err("text is required")

    optimizer = get_optimizer()
    optimized = optimizer.optimize_thai(text)

    return _ok({
        "original": text,
        "optimized": optimized,
        "saved_chars": len(text) - len(optimized),
        "stats": optimizer.get_savings_report(),
    })
