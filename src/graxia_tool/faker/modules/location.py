"""Location module — city, country, address, zip."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


class Location:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _l(self, key: str) -> List[str]:
        d = self._data.get("location", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("location", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def _one(self, key: str) -> str:
        lst = self._l(key)
        return self._rng.choice(lst) if lst else ""

    def city(self) -> str:
        return self._one("city")

    def country(self) -> str:
        return self._one("country")

    def state(self) -> str:
        return self._one("state")

    def street_suffix(self) -> str:
        return self._one("street_suffix")

    def street_name(self) -> str:
        """Random street name: a name + a suffix (e.g. 'Main St')."""
        # Use surnames as street base name; works for both locales
        surnames = (
            self._data.get("person", {}).get("last_name", [])
            or (self._fallback or {}).get("person", {}).get("last_name", [])
        )
        base = self._rng.choice(surnames) if surnames else "Main"
        suffix = self.street_suffix() or "St"
        return f"{base} {suffix}"

    def street_address(self) -> str:
        number = self._rng.randint(1, 9999)
        return f"{number} {self.street_name()}"

    def full_address(self) -> str:
        return (
            f"{self.street_address()}, {self.city()}, "
            f"{self.state()} {self.zip_code()}, {self.country()}"
        )

    def zip_code(self) -> str:
        """Generate a zip/postal code using the locale's format string."""
        fmt = self._data.get("location", {}).get(
            "zip_code_format",
            (self._fallback or {}).get("location", {}).get("zip_code_format", "#####"),
        )
        # If locale provides real samples (e.g. Thai), prefer those
        samples = self._data.get("location", {}).get("zip_code_samples")
        if samples:
            return self._rng.choice(samples)
        out: List[str] = []
        for ch in fmt:
            if ch == "#":
                out.append(str(self._rng.randint(0, 9)))
            else:
                out.append(ch)
        return "".join(out)

    def latitude(self) -> float:
        return round(self._rng.uniform(-90.0, 90.0), 6)

    def longitude(self) -> float:
        return round(self._rng.uniform(-180.0, 180.0), 6)
