"""Locale registry. Falls back to English if requested locale is missing."""
from __future__ import annotations

from typing import Any, Dict, Optional

_LOCALES: Dict[str, Dict[str, Any]] = {}


def register(code: str, data: Dict[str, Any]) -> None:
    """Register a locale."""
    _LOCALES[code.lower()] = data


def get_locale(code: str) -> Optional[Dict[str, Any]]:
    """Get a locale by code (e.g. 'en', 'th', 'th-th')."""
    if not code:
        return None
    key = code.lower().replace("_", "-").split("-")[0]
    return _LOCALES.get(key)


def available_locales() -> list[str]:
    """Return list of available locale codes."""
    return sorted(_LOCALES.keys())


# Auto-register built-in locales
from . import en  # noqa: E402,F401
from . import th  # noqa: E402,F401

register("en", en.EN)
register("th", th.TH)
