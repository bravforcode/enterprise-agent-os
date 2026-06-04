"""Person module — names, gender, bio, job."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


class Person:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _p(self, key: str) -> List[str]:
        """Pick a list, falling back to en if missing."""
        d = self._data.get("person", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("person", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def _one(self, key: str) -> str:
        lst = self._p(key)
        if not lst:
            return ""
        return self._rng.choice(lst)

    def gender(self) -> str:
        return self._one("gender") or "Unknown"

    def first_name(self, gender: Optional[str] = None) -> str:
        if gender is None:
            gender = self.gender()
        g = gender.lower()
        if g in ("male", "m", "ชาย"):
            return self._one("first_name_male")
        if g in ("female", "f", "หญิง"):
            return self._one("first_name_female")
        # neutral: pick from either
        pool = self._p("first_name_male") + self._p("first_name_female")
        return self._rng.choice(pool) if pool else ""

    def first_name_male(self) -> str:
        return self._one("first_name_male")

    def first_name_female(self) -> str:
        return self._one("first_name_female")

    def last_name(self) -> str:
        return self._one("last_name")

    def prefix(self, gender: Optional[str] = None) -> str:
        if gender is None:
            gender = self.gender()
        g = gender.lower()
        if g in ("male", "m", "ชาย"):
            return self._one("prefix_male")
        if g in ("female", "f", "หญิง"):
            return self._one("prefix_female")
        pool = self._p("prefix_male") + self._p("prefix_female")
        return self._rng.choice(pool) if pool else ""

    def full_name(self, gender: Optional[str] = None) -> str:
        return f"{self.first_name(gender)} {self.last_name()}"

    def job(self) -> str:
        return self._one("job_title")

    def bio(self) -> str:
        first = self.first_name()
        last = self.last_name()
        job = self.job()
        interests = self._p("interests")
        if not interests:
            return f"{first} {last} is a {job}."
        picked = [self._rng.choice(interests) for _ in range(3)]
        # Dedupe while preserving order
        seen: List[str] = []
        for i in picked:
            if i not in seen:
                seen.append(i)
        if len(seen) < 2:
            seen = interests[:2]
        if len(seen) == 2:
            return f"{first} {last} is a {job} who enjoys {seen[0]} and {seen[1]}."
        return (
            f"{first} {last} is a {job} who enjoys {seen[0]}, {seen[1]}, and {seen[2]}."
        )
