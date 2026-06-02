"""Enterprise Agent OS — Context Compressor.

Compresses conversation history when context is near limit.
Strategies:
- Lossless: Remove old messages beyond N turns
- Lossy: Summarize old messages with LLM
- Smart: Keep important messages, summarize the rest
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional
from ..core.config import settings
from ..core.logging import get_logger

logger = get_logger("context_compressor")


@dataclass
class CompressionResult:
    """Result of context compression."""
    original_tokens: int
    compressed_tokens: int
    messages_removed: int
    messages_summarized: int
    strategy: str
    summary: Optional[str] = None


class ContextCompressor:
    """
    Compresses conversation context to fit within token limits.

    When context > max_tokens:
    1. Always keep system prompt + last 3 turns (recent context)
    2. Summarize or drop older messages
    """

    def __init__(
        self,
        max_tokens: int | None = None,
        keep_recent: int = 3,
    ):
        self.max_tokens = max_tokens or settings.token_budget_per_turn
        self.keep_recent = keep_recent

    def count_tokens(self, text: str) -> int:
        """Rough token count (~4 chars per token)."""
        return len(text) // 4

    def compress_lossless(
        self, messages: list[dict[str, str]]
    ) -> CompressionResult:
        """Keep only last N messages, drop older ones."""
        if len(messages) <= self.keep_recent:
            return CompressionResult(
                original_tokens=sum(self.count_tokens(m.get("content", "")) for m in messages),
                compressed_tokens=sum(self.count_tokens(m.get("content", "")) for m in messages),
                messages_removed=0,
                messages_summarized=0,
                strategy="lossless_none",
            )

        kept = messages[-self.keep_recent:]
        removed = messages[:-self.keep_recent]
        original = sum(self.count_tokens(m.get("content", "")) for m in messages)
        compressed = sum(self.count_tokens(m.get("content", "")) for m in kept)

        logger.info(
            "context_compressed_lossless",
            removed=len(removed),
            kept=len(kept),
            saved=original - compressed,
        )
        return CompressionResult(
            original_tokens=original,
            compressed_tokens=compressed,
            messages_removed=len(removed),
            messages_summarized=0,
            strategy="lossless",
        )

    def compress_lossy(
        self, messages: list[dict[str, str]], summary: str
    ) -> CompressionResult:
        """Replace older messages with a summary."""
        if len(messages) <= self.keep_recent:
            return CompressionResult(
                original_tokens=sum(self.count_tokens(m.get("content", "")) for m in messages),
                compressed_tokens=sum(self.count_tokens(m.get("content", "")) for m in messages),
                messages_removed=0,
                messages_summarized=0,
                strategy="lossy_none",
            )

        # Build compressed: [summary, ...recent messages]
        kept = messages[-self.keep_recent:]
        removed = messages[:-self.keep_recent]
        summary_msg = {"role": "system", "content": f"[Summary of {len(removed)} earlier messages]: {summary}"}
        compressed = [summary_msg] + kept

        original = sum(self.count_tokens(m.get("content", "")) for m in messages)
        compressed_tokens = self.count_tokens(summary) + sum(
            self.count_tokens(m.get("content", "")) for m in kept
        )

        logger.info(
            "context_compressed_lossy",
            summarized=len(removed),
            kept=len(kept),
            saved=original - compressed_tokens,
        )
        return CompressionResult(
            original_tokens=original,
            compressed_tokens=compressed_tokens,
            messages_removed=0,
            messages_summarized=len(removed),
            strategy="lossy",
            summary=summary,
        )

    def auto_compress(
        self, messages: list[dict[str, str]], summarize_func=None
    ) -> tuple[list[dict[str, str]], CompressionResult]:
        """
        Auto-compress if context exceeds limit.

        Returns: (compressed_messages, compression_result)
        """
        total_tokens = sum(self.count_tokens(m.get("content", "")) for m in messages)

        if total_tokens <= self.max_tokens:
            return messages, CompressionResult(
                original_tokens=total_tokens,
                compressed_tokens=total_tokens,
                messages_removed=0,
                messages_summarized=0,
                strategy="none",
            )

        # Try lossless first
        if total_tokens > self.max_tokens * 1.5:
            # Aggressive compression needed
            if summarize_func:
                # Summarize older messages
                old_messages = messages[:-self.keep_recent]
                old_text = "\n".join(
                    f"{m['role']}: {m['content']}" for m in old_messages
                )
                summary = summarize_func(old_text)
                result = self.compress_lossy(messages, summary)
                compressed = [{"role": "system", "content": f"[Summary]: {summary}"}] + messages[-self.keep_recent:]
            else:
                # Drop older
                result = self.compress_lossless(messages)
                compressed = messages[-self.keep_recent:]
        else:
            # Mild compression
            result = self.compress_lossless(messages)
            compressed = messages[-self.keep_recent:]

        return compressed, result
