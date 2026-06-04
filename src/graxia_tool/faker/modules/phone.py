"""Phone module — phone numbers in locale-specific format.

Format string syntax:
    #  -> random digit 0-9
    +  -> literal
    any other char -> literal
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


class Phone:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _l(self, key: str) -> List[str]:
        d = self._data.get("phone", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("phone", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def _format(self, fmt: str) -> str:
        out: List[str] = []
        for ch in fmt:
            if ch == "#":
                out.append(str(self._rng.randint(0, 9)))
            else:
                out.append(ch)
        return "".join(out)

    def phone_number(self) -> str:
        formats = self._l("formats")
        if not formats:
            formats = ["###-###-####"]
        return self._format(self._rng.choice(formats))

    def mobile_number(self) -> str:
        """Return a mobile-style number. For Thai: +66 0[689]...; else generic."""
        formats = self._l("mobile_formats")
        if formats:
            return self._format(self._rng.choice(formats))
        # Fallback: any format starting with mobile prefix from generic list
        return self.phone_number()

    def extension(self, length: int = 4) -> str:
        return "".join(str(self._rng.randint(0, 9)) for _ in range(length))
