"""Internet module — email, URL, username, IP, user-agent."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional


class Internet:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _l(self, key: str) -> List[str]:
        d = self._data.get("internet", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("internet", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def _one(self, key: str) -> str:
        lst = self._l(key)
        return self._rng.choice(lst) if lst else ""

    def email_domain(self) -> str:
        return self._one("email_domain") or "example.com"

    def tld(self) -> str:
        return self._one("tld") or "com"

    def domain_name(self) -> str:
        words = (
            self._data.get("lorem", {}).get("words", [])
            or (self._fallback or {}).get("lorem", {}).get("words", [])
        )
        # Pick a short clean word for a domain
        pool = [w for w in words if w.isalpha() and 3 <= len(w) <= 10] or words
        base = self._rng.choice(pool) if pool else "example"
        return f"{base.lower()}.{self.tld()}"

    def email(self, first: Optional[str] = None,
              last: Optional[str] = None) -> str:
        """Generate email. If first/last are given, use them; else auto from
        person.locale slug lists (no real person object needed here)."""
        f = (first or "").strip().lower()
        l = (last or "").strip().lower()
        if not f and not l:
            # Auto-pick from locale slug lists when available
            person = self._data.get("person", {})
            male = person.get("first_name_male_slug") or person.get("first_name_male", [])
            fem = person.get("first_name_female_slug") or person.get("first_name_female", [])
            last_names = person.get("last_name_slug") or person.get("last_name", [])
            pool = (male or []) + (fem or [])
            if self._fallback and not pool:
                fb_p = self._fallback.get("person", {})
                male = fb_p.get("first_name_male", [])
                fem = fb_p.get("first_name_female", [])
                last_names = fb_p.get("last_name", [])
                pool = male + fem
            if not pool:
                pool = ["user"]
            if not last_names:
                last_names = ["smith"]
            chosen_first = self._rng.choice(pool).lower()
            chosen_last = self._rng.choice(last_names).lower()
            f, l = chosen_first, chosen_last

        domain = self.email_domain()
        # Add occasional digits
        suffix = str(self._rng.randint(0, 99)) if self._rng.random() < 0.3 else ""
        sep = self._rng.choice([".", "_", ""])
        if f and l:
            local = f"{f}{sep}{l}{suffix}"
        else:
            local = f"{f or l}{suffix}"
        return f"{local}@{domain}"

    def username(self, first: Optional[str] = None,
                 last: Optional[str] = None,
                 min_length: int = 6, max_length: int = 12) -> str:
        f = (first or "").strip().lower()
        l = (last or "").strip().lower()
        if not f and not l:
            person = self._data.get("person", {})
            male = person.get("first_name_male_slug") or person.get("first_name_male", [])
            fem = person.get("first_name_female_slug") or person.get("first_name_female", [])
            last_names = person.get("last_name_slug") or person.get("last_name", [])
            pool = (male or []) + (fem or [])
            if self._fallback and not pool:
                fb_p = self._fallback.get("person", {})
                pool = fb_p.get("first_name_male", []) + fb_p.get("first_name_female", [])
                last_names = fb_p.get("last_name", [])
            if not pool:
                pool = ["user"]
            if not last_names:
                last_names = ["smith"]
            f = self._rng.choice(pool).lower()
            l = self._rng.choice(last_names).lower()

        if f and l:
            base = f"{f}_{l}"
        else:
            base = f or l or "user"
        # Trim or pad to length
        if len(base) > max_length:
            base = base[:max_length]
        if len(base) < min_length:
            base = base + "".join(
                self._rng.choice(string.digits) for _ in range(min_length - len(base))
            )
        # Add random digit suffix
        base += str(self._rng.randint(0, 999))
        return base[:max_length]

    def url(self) -> str:
        proto = self._rng.choice(["http", "https"])
        return f"{proto}://{self.domain_name()}/{self._rng.choice(['about', 'contact', 'blog', 'products', 'news', ''])}"

    def ipv4(self) -> str:
        # Avoid 0.x and 127.x and 255.x for realism
        def octet() -> int:
            o = self._rng.randint(1, 254)
            return o
        return f"{octet()}.{octet()}.{octet()}.{octet()}"

    def ipv6(self) -> str:
        return ":".join(
            "".join(self._rng.choice("0123456789abcdef") for _ in range(4))
            for _ in range(8)
        )

    def mac_address(self) -> str:
        return ":".join(
            "".join(self._rng.choice("0123456789abcdef") for _ in range(2))
            for _ in range(6)
        )

    def user_agent(self) -> str:
        return self._one("user_agents") or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
