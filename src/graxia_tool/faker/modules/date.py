"""Date module — past, future, recent, birthdate, between."""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


class DateModule:
    _MAX_YEARS = 50

    def __init__(self, rng: random.Random, data: Dict[str, Any]) -> None:
        self._rng = rng
        self._data = data

    def _now(self) -> datetime:
        return datetime.now()

    def past(self, years: int = 1) -> datetime:
        if years <= 0:
            return self._now()
        days = self._rng.randint(1, int(years * 365))
        seconds = self._rng.randint(0, 86399)
        return self._now() - timedelta(days=days, seconds=seconds)

    def future(self, years: int = 1) -> datetime:
        if years <= 0:
            return self._now()
        days = self._rng.randint(1, int(years * 365))
        seconds = self._rng.randint(0, 86399)
        return self._now() + timedelta(days=days, seconds=seconds)

    def recent(self, days: int = 30) -> datetime:
        days = max(1, int(days))
        d = self._rng.randint(0, days)
        seconds = self._rng.randint(0, 86399)
        return self._now() - timedelta(days=d, seconds=seconds)

    def soon(self, days: int = 30) -> datetime:
        days = max(1, int(days))
        d = self._rng.randint(0, days)
        seconds = self._rng.randint(0, 86399)
        return self._now() + timedelta(days=d, seconds=seconds)

    def birthdate(self, min_age: int = 18, max_age: int = 65) -> datetime:
        lo = min(min_age, max_age)
        hi = max(min_age, max_age)
        age = self._rng.randint(lo, hi)
        # Random day of that age in years
        days = self._rng.randint(0, 364)
        seconds = self._rng.randint(0, 86399)
        return self._now() - timedelta(days=age * 365 + days, seconds=seconds)

    def between(self, start: datetime, end: datetime) -> datetime:
        if end <= start:
            return start
        delta = (end - start).total_seconds()
        offset = self._rng.uniform(0, delta)
        return start + timedelta(seconds=offset)

    def month_name(self) -> str:
        months = self._data.get("date", {}).get("month", [])
        if not months:
            return "January"
        return self._rng.choice(months)
