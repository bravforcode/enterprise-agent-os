"""Lorem module — words, sentences, paragraphs, text."""
from __future__ import annotations

import random
import string
from typing import Any, Dict, List, Optional


class Lorem:
    def __init__(self, rng: random.Random, data: Dict[str, Any],
                 fallback: Optional[Dict[str, Any]] = None) -> None:
        self._rng = rng
        self._data = data
        self._fallback = fallback

    def _words(self) -> List[str]:
        w = self._data.get("lorem", {}).get("words", [])
        if w:
            return w
        if self._fallback:
            return self._fallback.get("lorem", {}).get("words", [])
        return ["lorem", "ipsum", "dolor", "sit", "amet"]

    def word(self) -> str:
        return self._rng.choice(self._words())

    def words(self, count: int = 3) -> List[str]:
        count = max(1, int(count))
        return [self._rng.choice(self._words()) for _ in range(count)]

    def sentence(self, word_count: Optional[int] = None) -> str:
        wc = word_count or self._rng.randint(6, 12)
        ws = self.words(wc)
        if not ws:
            return ""
        ws[0] = ws[0].capitalize()
        # Add period (Thai uses its own sentence-ending, but ASCII '.' is widely
        # accepted in mixed text and we want schema-friendly output)
        return " ".join(ws) + "."

    def sentences(self, count: int = 3) -> List[str]:
        count = max(1, int(count))
        return [self.sentence() for _ in range(count)]

    def paragraph(self, sentence_count: Optional[int] = None) -> str:
        sc = sentence_count or self._rng.randint(3, 6)
        return " ".join(self.sentences(sc))

    def paragraphs(self, count: int = 3) -> List[str]:
        count = max(1, int(count))
        return [self.paragraph() for _ in range(count)]

    def text(self, max_chars: int = 200) -> str:
        out_parts: List[str] = []
        total = 0
        while total < max_chars:
            s = self.sentence()
            out_parts.append(s)
            total += len(s) + 1
        return " ".join(out_parts)[:max_chars]
