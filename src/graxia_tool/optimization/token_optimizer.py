"""Unified token optimization — RTK + lean-ctx + Thai Token Optimizer.

Three complementary strategies:
- RTK (Rust Token Killer): prefix shell commands with `rtk` for 60-90% savings
- lean-ctx: compress file reads and code context (60-99% savings)
- Thai Token Optimizer: compact Thai text for 60-75% savings
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class OptimizationStats:
    """Track optimization statistics."""
    rtk_commands_optimized: int = 0
    lean_ctx_reads_optimized: int = 0
    tto_texts_optimized: int = 0
    estimated_tokens_saved: int = 0
    original_tokens: int = 0
    optimized_tokens: int = 0

    @property
    def savings_pct(self) -> float:
        if self.original_tokens == 0:
            return 0.0
        return (1 - self.optimized_tokens / self.original_tokens) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rtk_commands_optimized": self.rtk_commands_optimized,
            "lean_ctx_reads_optimized": self.lean_ctx_reads_optimized,
            "tto_texts_optimized": self.tto_texts_optimized,
            "estimated_tokens_saved": self.estimated_tokens_saved,
            "original_tokens": self.original_tokens,
            "optimized_tokens": self.optimized_tokens,
            "savings_pct": round(self.savings_pct, 1),
        }


class TokenOptimizer:
    """Optimize token usage across all operations.

    Usage:
        optimizer = TokenOptimizer()
        cmd = optimizer.optimize_command("git status")  # → "rtk git status"
        read_cmd = optimizer.optimize_file_read("/path/to/file")  # → "ctx_read ..."
        thai = optimizer.optimize_thai("สวัสดีครับ ขอบคุณมาก")  # → compact Thai
    """

    def __init__(self, enable_rtk: bool = True, enable_lean_ctx: bool = True, enable_tto: bool = True) -> None:
        self.enable_rtk = enable_rtk
        self.enable_lean_ctx = enable_lean_ctx
        self.enable_tto = enable_tto
        self.stats = OptimizationStats()
        self._rtk_available: bool | None = None
        self._lean_ctx_available: bool | None = None

    # ── Availability checks (cached) ──────────────────────────────────

    def _check_rtk(self) -> bool:
        if self._rtk_available is not None:
            return self._rtk_available
        self._rtk_available = shutil.which("rtk") is not None
        return self._rtk_available

    def _check_lean_ctx(self) -> bool:
        if self._lean_ctx_available is not None:
            return self._lean_ctx_available
        self._lean_ctx_available = shutil.which("ctx_read") is not None
        return self._lean_ctx_available

    @property
    def rtk_available(self) -> bool:
        return self.enable_rtk and self._check_rtk()

    @property
    def lean_ctx_available(self) -> bool:
        return self.enable_lean_ctx and self._check_lean_ctx()

    @property
    def tto_enabled(self) -> bool:
        return self.enable_tto

    # ── Command optimization (RTK) ────────────────────────────────────

    def optimize_command(self, command: str) -> str:
        """Add rtk prefix to shell commands for token savings.

        RTK filters output to show only errors/warnings/summary,
        cutting 60-90% of token usage on verbose commands.
        """
        if not self.rtk_available:
            return command

        stripped = command.strip()
        if not stripped:
            return command

        # Don't double-prefix
        if stripped.startswith("rtk "):
            return command

        # Skip commands that don't benefit from RTK
        skip_prefixes = ("rtk ", "echo ", "cd ", "exit ", "export ", "source ")
        if any(stripped.startswith(p) for p in skip_prefixes):
            return command

        # Skip piped commands (RTK only works on first command)
        # But handle simple chains like "cmd1 && cmd2" by prefixing first
        if "&&" in stripped:
            parts = stripped.split("&&", 1)
            first = parts[0].strip()
            if first and not first.startswith("rtk "):
                self.stats.rtk_commands_optimized += 1
                return f"rtk {first} &&{parts[1]}"
            return command

        if "|" in stripped:
            # Don't prefix piped commands
            return command

        self.stats.rtk_commands_optimized += 1
        return f"rtk {stripped}"

    def optimize_commands(self, commands: list[str]) -> list[str]:
        """Optimize a batch of commands."""
        return [self.optimize_command(cmd) for cmd in commands]

    # ── File read optimization (lean-ctx) ─────────────────────────────

    def optimize_file_read(self, path: str, mode: str = "auto") -> str:
        """Use lean-ctx for file reads when available.

        lean-ctx compresses file content by stripping comments, empty lines,
        and using AST-aware truncation (60-99% savings).
        """
        if self.lean_ctx_available:
            self.stats.lean_ctx_reads_optimized += 1
            return f"ctx_read --mode {mode} {path}"
        return f"cat {path}"

    def optimize_code_read(self, path: str, language: str = "auto", max_lines: int = 200) -> str:
        """Optimized code reading with lean-ctx."""
        if self.lean_ctx_available:
            self.stats.lean_ctx_reads_optimized += 1
            return f"ctx_read --mode code --lang {language} --max-lines {max_lines} {path}"
        return f"cat {path}"

    # ── Thai text optimization (TTO) ──────────────────────────────────

    def optimize_thai(self, text: str) -> str:
        """Optimize Thai text for token savings.

        Thai Token Optimizer rules:
        - Remove redundant particles (ครับ/ค่ะ → keep one or remove)
        - Compress common phrases
        - Remove unnecessary spaces between Thai words
        - Simplify polite endings
        """
        if not self.tto_enabled or not text:
            return text

        original_len = len(text)
        optimized = self._apply_tto(text)

        if optimized != text:
            self.stats.tto_texts_optimized += 1
            # Rough token estimate: Thai ~1.5 tokens per char
            saved_chars = original_len - len(optimized)
            self.stats.estimated_tokens_saved += int(saved_chars * 1.5)
            self.stats.original_tokens += int(original_len * 1.5)
            self.stats.optimized_tokens += int(len(optimized) * 1.5)

        return optimized

    def _apply_tto(self, text: str) -> str:
        """Apply Thai Token Optimization rules."""
        result = text

        # Remove redundant polite particles at end of sentence
        # Keep one if multiple stacked
        result = re.sub(r'(ครับค่ะ|ค่ะครับ|ครับครับ|ค่ะค่ะ|นะครับครับ|นะค่ะค่ะ)+$', 'ครับ', result)
        result = re.sub(r'(ครับค่ะ|ค่ะครับ|ครับครับ|ค่ะค่ะ)+$', 'ค่ะ', result)

        # Compress common verbose phrases → shorter equivalents
        phrase_map = {
            "ไม่เป็นไรครับ": "ไม่เป็นไร",
            "ไม่เป็นไรค่ะ": "ไม่เป็นไร",
            "ขอบคุณมากครับ": "ขอบคุณ",
            "ขอบคุณมากค่ะ": "ขอบคุณ",
            "สวัสดีครับ": "สวัสดี",
            "สวัสดีค่ะ": "สวัสดี",
            "ได้เลยครับ": "ได้เลย",
            "ได้เลยค่ะ": "ได้เลย",
            "แน่นอนครับ": "แน่นอน",
            "แน่นอนค่ะ": "แน่นอน",
            "เข้าใจแล้วครับ": "เข้าใจ",
            "เข้าใจแล้วค่ะ": "เข้าใจ",
            "ทำได้ครับ": "ทำได้",
            "ทำได้ค่ะ": "ทำได้",
            "ลองดูครับ": "ลองดู",
            "ลองดูค่ะ": "ลองดู",
            "เรียบร้อยครับ": "เรียบร้อย",
            "เรียบร้อยค่ะ": "เรียบร้อย",
            "สำเร็จแล้วครับ": "สำเร็จ",
            "สำเร็จแล้วค่ะ": "สำเร็จ",
        }
        for verbose, compact in phrase_map.items():
            result = result.replace(verbose, compact)

        # Remove extra spaces between Thai characters
        result = re.sub(r'([\u0E00-\u0E7F])\s+([\u0E00-\u0E7F])', r'\1\2', result)

        # Collapse multiple spaces
        result = re.sub(r' {2,}', ' ', result)

        return result.strip()

    # ── Combined optimization ─────────────────────────────────────────

    def optimize(self, text: str, context: str = "general") -> str:
        """Apply appropriate optimization based on context.

        Contexts: 'command', 'file_read', 'thai', 'general'
        """
        if context == "command":
            return self.optimize_command(text)
        elif context == "file_read":
            return self.optimize_file_read(text)
        elif context == "thai":
            return self.optimize_thai(text)
        return text

    # ── Reporting ─────────────────────────────────────────────────────

    def get_savings_report(self) -> Dict[str, Any]:
        """Get token savings statistics."""
        return {
            **self.stats.to_dict(),
            "rtk_available": self.rtk_available,
            "lean_ctx_available": self.lean_ctx_available,
            "tto_enabled": self.tto_enabled,
            "capabilities": {
                "rtk": self.enable_rtk,
                "lean_ctx": self.enable_lean_ctx,
                "tto": self.enable_tto,
            },
        }

    def reset_stats(self) -> None:
        """Reset optimization statistics."""
        self.stats = OptimizationStats()


# ── Singleton for convenience ──────────────────────────────────────────

_default_optimizer: TokenOptimizer | None = None


def get_optimizer() -> TokenOptimizer:
    """Get or create the default TokenOptimizer instance."""
    global _default_optimizer
    if _default_optimizer is None:
        _default_optimizer = TokenOptimizer()
    return _default_optimizer
