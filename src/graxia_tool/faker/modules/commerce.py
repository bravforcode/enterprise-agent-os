"""Commerce module — product names, prices, departments, SKUs."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional


class Commerce:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _l(self, key: str) -> List[str]:
        d = self._data.get("commerce", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("commerce", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def _one(self, key: str) -> str:
        lst = self._l(key)
        return self._rng.choice(lst) if lst else ""

    def product_name(self) -> str:
        adj = self._one("product_adj") or "Generic"
        mat = self._one("product_material")
        noun = self._one("product_noun") or "Item"
        if mat:
            return f"{adj} {mat} {noun}"
        return f"{adj} {noun}"

    def product_adjective(self) -> str:
        return self._one("product_adj")

    def product_material(self) -> str:
        return self._one("product_material")

    def product_noun(self) -> str:
        return self._one("product_noun")

    def department(self) -> str:
        return self._one("department")

    def category(self) -> str:
        return self.department()

    def price(self, min_value: float = 1.0, max_value: float = 1000.0) -> float:
        return round(self._rng.uniform(min_value, max_value), 2)

    def price_formatted(self, min_value: float = 1.0,
                        max_value: float = 1000.0) -> str:
        return f"{self.price(min_value, max_value):.2f}"

    def sku(self, length: int = 8) -> str:
        """3 letters + digits up to length."""
        letters = "".join(self._rng.choice(string.ascii_uppercase) for _ in range(3))
        digits_needed = max(0, length - 3)
        digits = "".join(str(self._rng.randint(0, 9)) for _ in range(digits_needed))
        return letters + digits

    def barcode(self, length: int = 13) -> str:
        return "".join(str(self._rng.randint(0, 9)) for _ in range(length))
