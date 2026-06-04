"""MCP tools for Faker — synthetic data generation exposed to MCP clients.

Tools:
  - faker_generate:  generate data by category/field
  - faker_schema:    generate complex object from schema dict
  - faker_locales:   list available locales

All tools return _ok({...}) or _err(...). No external deps.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from ..shared.helpers import _ok, _err
from ..faker import Faker
from ..faker.locales import available_locales


def _make_faker(locale: str = "en", seed: Optional[int] = None) -> Faker:
    if seed is not None:
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = None
    return Faker(locale=locale or "en", seed=seed)


# ---------------------------------------------------------------------------
# faker_generate
# ---------------------------------------------------------------------------

VALID_CATEGORIES = {
    "person", "location", "finance", "date", "lorem", "commerce",
    "internet", "phone",
}


async def faker_generate(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate synthetic data.

    Args:
        category: person|location|finance|date|lorem|commerce|internet|phone
        field:    method name within the category (e.g. "first_name"). If None,
                  a sensible default per category is used.
        count:    number of items to generate (default 1, max 1000).
        locale:   locale code (default "en"). Falls back to en if unknown.
        seed:     optional int for reproducibility.
    """
    category = (args.get("category") or "").strip().lower()
    field = args.get("field")
    count = int(args.get("count", 1) or 1)
    locale = args.get("locale") or "en"
    seed = args.get("seed")

    if not category:
        return _err("category is required")
    if category not in VALID_CATEGORIES:
        return _err(
            f"Unknown category '{category}'. "
            f"Valid: {sorted(VALID_CATEGORIES)}"
        )
    if count < 1 or count > 1000:
        return _err("count must be 1..1000")

    # Resolve default field up-front (closure-safe)
    if not field:
        field = {
            "person": "full_name",
            "location": "city",
            "finance": "amount",
            "date": "recent",
            "lorem": "sentence",
            "commerce": "product_name",
            "internet": "email",
            "phone": "phone_number",
        }.get(category, "first_name")

    def _do():
        f = _make_faker(locale, seed)
        module = getattr(f, category)
        method = getattr(module, field, None)
        if method is None or not callable(method):
            return None, (
                f"Unknown field '{category}.{field}'. "
                f"Available: {sorted(n for n in dir(module) if not n.startswith('_'))}"
            )
        try:
            results = [method() for _ in range(count)]
        except TypeError as e:
            return None, f"Field '{category}.{field}' requires arguments: {e}"
        return results, None

    try:
        results, err = await asyncio.to_thread(_do)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")

    if err:
        return _err(err)

    payload: Dict[str, Any] = {
        "category": category,
        "field": field,
        "locale": locale,
        "count": count,
        "results": results,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    return _ok(payload)


# ---------------------------------------------------------------------------
# faker_schema
# ---------------------------------------------------------------------------

async def faker_schema(args: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a complex object from a schema dict.

    Args:
        schema:   dict mapping field name -> generator spec
                   (str like "internet.email", tuple like ("int", 18, 65),
                    or "string.uuid" / "bool" / "int" / "float" / "choice")
        locale:   locale code (default "en")
        seed:     optional int for reproducibility
        count:    optional — if >1, returns a list of N objects
    """
    schema = args.get("schema")
    locale = args.get("locale") or "en"
    seed = args.get("seed")
    count = int(args.get("count", 1) or 1)

    if schema is None:
        return _err("schema is required")
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError as e:
            return _err(f"schema must be dict (or JSON string): {e}")
    if not isinstance(schema, dict):
        return _err("schema must be a dict (field name -> generator spec)")
    if count < 1 or count > 1000:
        return _err("count must be 1..1000")

    def _do():
        f = _make_faker(locale, seed)
        try:
            if count == 1:
                return f.schema(schema), None
            return [f.schema(schema) for _ in range(count)], None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    try:
        result, err = await asyncio.to_thread(_do)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")

    if err:
        return _err(err)

    payload: Dict[str, Any] = {
        "locale": locale,
        "count": count,
        "result": result,
    }
    if seed is not None:
        payload["seed"] = int(seed)
    return _ok(payload)


# ---------------------------------------------------------------------------
# faker_locales
# ---------------------------------------------------------------------------

async def faker_locales(args: Dict[str, Any]) -> Dict[str, Any]:
    """List available locales."""
    locales = available_locales()
    return _ok({"locales": locales, "count": len(locales)})


# ---------------------------------------------------------------------------
# MCP tool definitions
# ---------------------------------------------------------------------------

FAKER_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "faker_generate",
        "description": (
            "Generate synthetic data from a category/field. "
            "Categories: person, location, finance, date, lorem, commerce, "
            "internet, phone. Supports Thai locale (locale='th' or 'th_TH')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": sorted(VALID_CATEGORIES),
                    "description": "Data category",
                },
                "field": {
                    "type": "string",
                    "description": "Method name within the category (optional)",
                },
                "count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 1000},
                "locale": {"type": "string", "default": "en", "description": "Locale code (en, th)"},
                "seed": {"type": "integer", "description": "Optional seed for reproducibility"},
            },
            "required": ["category"],
        },
        "handler": faker_generate,
        "category": "faker",
    },
    {
        "name": "faker_schema",
        "description": (
            "Generate a complex object from a schema dict. "
            "Spec types: 'category.field', 'string.uuid', 'bool', "
            "('int', min, max), ('float', min, max), ('choice', [list])."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "schema": {
                    "type": "object",
                    "description": "Dict mapping field -> generator spec",
                },
                "locale": {"type": "string", "default": "en"},
                "seed": {"type": "integer"},
                "count": {"type": "integer", "default": 1, "minimum": 1, "maximum": 1000},
            },
            "required": ["schema"],
        },
        "handler": faker_schema,
        "category": "faker",
    },
    {
        "name": "faker_locales",
        "description": "List available Faker locales.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": faker_locales,
        "category": "faker",
    },
]
