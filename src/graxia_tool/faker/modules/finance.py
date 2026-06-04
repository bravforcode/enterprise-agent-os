"""Finance module — account numbers, amounts, currency, crypto."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional


class Finance:
    _BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _l(self, key: str) -> List[str]:
        d = self._data.get("finance", {})
        if key in d and d[key]:
            return d[key]
        if self._fallback:
            fd = self._fallback.get("finance", {})
            if key in fd and fd[key]:
                return fd[key]
        return []

    def currency_code(self) -> str:
        lst = self._l("currency_code")
        return self._rng.choice(lst) if lst else "USD"

    def currency_name(self) -> str:
        lst = self._l("currency_name")
        return self._rng.choice(lst) if lst else "US Dollar"

    def currency_symbol(self) -> str:
        lst = self._l("currency_symbol")
        return self._rng.choice(lst) if lst else "$"

    def amount(self, min_value: float = 0.0, max_value: float = 10000.0,
               decimals: int = 2) -> float:
        return round(self._rng.uniform(min_value, max_value), decimals)

    def price(self, min_value: float = 1.0, max_value: float = 1000.0) -> float:
        return self.amount(min_value=min_value, max_value=max_value, decimals=2)

    def account_number(self, length: int = 10) -> str:
        return "".join(str(self._rng.randint(0, 9)) for _ in range(length))

    def routing_number(self) -> str:
        return self.account_number(9)

    def iban(self) -> str:
        countries = self._l("iban_country") or ["US"]
        country = self._rng.choice(countries)
        check = self.account_number(2)
        bban = self.account_number(self._rng.randint(14, 30))
        return f"{country}{check}{bban}"

    def credit_card_number(self) -> str:
        types = self._l("credit_card_type") or ["visa"]
        t = self._rng.choice(types)
        # Simple — not Luhn-valid, just pattern-shaped
        if t == "amex":
            return f"3{self._rng.randint(4, 7)} " \
                   f"{self.account_number(6)} " \
                   f"{self.account_number(5)}"
        if t == "discover":
            return f"6011 {self.account_number(4)} {self.account_number(4)} {self.account_number(4)}"
        if t == "jcb":
            return f"35{self._rng.randint(0, 9)} {self.account_number(4)} {self.account_number(4)} {self.account_number(4)}"
        # visa / mastercard default
        prefix = "4" if t == "visa" else f"{self._rng.randint(51, 55)}"
        return f"{prefix} {self.account_number(4)} {self.account_number(4)} {self.account_number(4)}"

    def credit_card_type(self) -> str:
        lst = self._l("credit_card_type")
        return self._rng.choice(lst) if lst else "visa"

    def crypto_code(self) -> str:
        lst = self._l("crypto_code")
        return self._rng.choice(lst) if lst else "BTC"

    def crypto_name(self) -> str:
        lst = self._l("crypto_name")
        return self._rng.choice(lst) if lst else "Bitcoin"

    def bitcoin_address(self) -> str:
        # 1... (P2PKH) style
        chars = "".join(self._rng.choice(self._BASE58) for _ in range(33))
        return f"1{chars}"

    def ethereum_address(self) -> str:
        return "0x" + "".join(
            self._rng.choice("0123456789abcdef") for _ in range(40)
        )

    def crypto_amount(self) -> float:
        return round(self._rng.uniform(0.0001, 100.0), 6)
