"""Base Faker class — seedable, locale-aware, no external deps.

API mirrors faker-js style:
    f = Faker(locale="th_TH")
    f.seed(42)
    f.person.first_name()  # "สมชาย"
    f.location.city()      # "กรุงเทพมหานคร"
    f.schema({...})        # generate complex object
"""
from __future__ import annotations

import random
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .locales import get_locale

from .modules.person import Person
from .modules.location import Location
from .modules.finance import Finance
from .modules.date import DateModule
from .modules.lorem import Lorem
from .modules.commerce import Commerce
from .modules.internet import Internet
from .modules.phone import Phone


# Schema value types
SchemaValue = Union[
    str,                    # "category.field" or "string.uuid" or "bool" or "int"
    Tuple[Any, ...],        # ("int", 18, 65) or ("category.field", {args})
    Callable[[], Any],      # any callable returning a value
    Any,                    # literal value
]


class Faker:
    """Faker-js inspired synthetic data generator.

    Args:
        locale: Locale code (e.g. "en", "th", "th_TH", "en_US"). Falls back to "en"
                for unknown locales (per faker-js locale-fallback pattern).
        seed: Optional int seed for reproducibility.
    """

    def __init__(self, locale: str = "en", seed: Optional[int] = None) -> None:
        self._requested_locale = locale
        self._locale_code = self._normalize_locale(locale)
        self._rng = random.Random()

        # Load primary locale (fallback to en)
        self._data = get_locale(self._locale_code) or get_locale("en") or {}
        self._has_fallback = self._locale_code != "en"
        self._fallback = get_locale("en") if self._has_fallback else None

        # Init modules
        self.person = Person(self._rng, self._data, self._fallback)
        self.location = Location(self._rng, self._data, self._fallback)
        self.finance = Finance(self._rng, self._data, self._fallback)
        self.date = DateModule(self._rng, self._data)
        self.lorem = Lorem(self._rng, self._data, self._fallback)
        self.commerce = Commerce(self._rng, self._data, self._fallback)
        self.internet = Internet(self._rng, self._data, self._fallback)
        self.phone = Phone(self._rng, self._data, self._fallback)

        if seed is not None:
            self.seed(seed)

    @staticmethod
    def _normalize_locale(locale: str) -> str:
        if not locale:
            return "en"
        return locale.replace("_", "-").split("-")[0].lower()

    def seed(self, seed: int) -> "Faker":
        """Seed the underlying RNG for reproducible output."""
        if not isinstance(seed, (int, float)):
            raise TypeError("seed must be int")
        self._rng.seed(int(seed))
        return self

    @property
    def locale(self) -> str:
        return self._locale_code

    # ------------------------------------------------------------------
    # Schema generation
    # ------------------------------------------------------------------

    def schema(self, schema: Dict[str, SchemaValue]) -> Dict[str, Any]:
        """Generate a complex object from a schema dict.

        Schema value types:
            str: "category.field" calls f.<category>.<field>()
                 "string.uuid" -> uuid4
                 "bool" -> True/False
                 "int" -> 0..1000
                 "float" -> 0.0..1.0
            tuple: ("int", 10, 100) -> random int in range
                   ("float", 0.0, 100.0) -> random float
                   ("choice", [a, b, c]) -> random.choice
                   ("category.field", {"kwarg": val}) -> call with kwargs
            callable: invoked with no args
            other: returned as-is
        """
        if not isinstance(schema, dict):
            raise TypeError("schema must be a dict")
        return {k: self._resolve(v) for k, v in schema.items()}

    def _resolve(self, v: SchemaValue) -> Any:
        if callable(v):
            return v()

        if isinstance(v, str):
            if v == "string.uuid":
                return str(uuid.uuid4())
            if v == "bool":
                return self._rng.choice([True, False])
            if v == "int":
                return self._rng.randint(0, 1000)
            if v == "float":
                return self._rng.random()
            if v.startswith("string.uuid") or v == "uuid":
                return str(uuid.uuid4())

            if "." in v:
                # category.field
                return self._call_path(v, {})

            return v

        if isinstance(v, tuple):
            if len(v) == 0:
                return None
            head = v[0]
            if head == "int" and len(v) == 3:
                lo, hi = int(v[1]), int(v[2])
                return self._rng.randint(lo, hi)
            if head == "float" and len(v) == 3:
                lo, hi = float(v[1]), float(v[2])
                return self._rng.uniform(lo, hi)
            if head == "choice" and len(v) == 2:
                return self._rng.choice(list(v[1]))
            if head == "uuid":
                return str(uuid.uuid4())
            if isinstance(head, str) and "." in head:
                # ("category.field", {kwargs})
                kwargs = v[1] if len(v) >= 2 and isinstance(v[1], dict) else {}
                return self._call_path(head, kwargs)
            return v

        if isinstance(v, list):
            return [self._resolve(item) for item in v]

        return v

    def _call_path(self, path: str, kwargs: Dict[str, Any]) -> Any:
        """Call f.<category>.<field>(**kwargs)."""
        parts = path.split(".", 1)
        if len(parts) != 2:
            raise ValueError(f"Invalid path: {path}")
        cat, field = parts
        module = getattr(self, cat, None)
        if module is None:
            raise AttributeError(f"No category '{cat}' (path={path})")
        method = getattr(module, field, None)
        if method is None or not callable(method):
            raise AttributeError(f"No method '{cat}.{field}'")
        return method(**kwargs)
