"""Tests for the token optimization stack (RTK + lean-ctx + TTO)."""
from __future__ import annotations

import shutil
import pytest

from graxia_tool.optimization.token_optimizer import TokenOptimizer, get_optimizer


class TestTokenOptimizerRTK:
    """Tests for RTK command prefix optimization."""

    def test_prefix_added(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        # Mock rtk as available
        opt._rtk_available = True
        result = opt.optimize_command("git status")
        assert result == "rtk git status"

    def test_no_double_prefix(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("rtk git status")
        assert result == "rtk git status"

    def test_skip_echo(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("echo hello")
        assert result == "echo hello"

    def test_skip_cd(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("cd /tmp")
        assert result == "cd /tmp"

    def test_pipe_not_prefixed(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("cat file | grep foo")
        assert result == "cat file | grep foo"

    def test_and_chain_prefixes_first(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("cargo build && cargo test")
        assert result == "rtk cargo build && cargo test"

    def test_empty_command(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        result = opt.optimize_command("")
        assert result == ""

    def test_rtk_disabled(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=False)
        result = opt.optimize_command("git status")
        assert result == "git status"

    def test_stats_increment(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        opt.optimize_command("git status")
        opt.optimize_command("cargo build")
        assert opt.stats.rtk_commands_optimized == 2


class TestTokenOptimizerLeanCtx:
    """Tests for lean-ctx file read optimization."""

    def test_file_read_with_ctx(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=True, enable_tto=False)
        opt._lean_ctx_available = True
        result = opt.optimize_file_read("/path/to/file.py")
        assert result == "ctx_read --mode auto /path/to/file.py"

    def test_file_read_without_ctx(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=False)
        result = opt.optimize_file_read("/path/to/file.py")
        assert result == "cat /path/to/file.py"

    def test_code_read_with_ctx(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=True, enable_tto=False)
        opt._lean_ctx_available = True
        result = opt.optimize_code_read("/path/to/file.py", language="python", max_lines=100)
        assert result == "ctx_read --mode code --lang python --max-lines 100 /path/to/file.py"

    def test_stats_increment(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=True, enable_tto=False)
        opt._lean_ctx_available = True
        opt.optimize_file_read("/a.py")
        opt.optimize_file_read("/b.py")
        assert opt.stats.lean_ctx_reads_optimized == 2


class TestTokenOptimizerTTO:
    """Tests for Thai Token Optimizer."""

    def test_remove_redundant_particles(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("สวัสดีครับค่ะ")
        # Should collapse to one particle
        assert "ครับค่ะ" not in result

    def test_compress_verbose_phrase(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("ขอบคุณมากครับ")
        assert result == "ขอบคุณ"

    def test_compress_greeting(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("สวัสดีครับ")
        assert result == "สวัสดี"

    def test_compress_ok_phrase(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("ได้เลยค่ะ")
        assert result == "ได้เลย"

    def test_remove_extra_spaces(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("สวัสดี ครับ")
        assert "สวัสดีครับ" in result

    def test_empty_text(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("")
        assert result == ""

    def test_non_thai_unchanged(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        result = opt.optimize_thai("Hello world")
        assert result == "Hello world"

    def test_tto_disabled(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=False)
        result = opt.optimize_thai("ขอบคุณมากครับ")
        assert result == "ขอบคุณมากครับ"

    def test_stats_increment(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=False, enable_tto=True)
        opt.optimize_thai("ขอบคุณมากครับ")
        assert opt.stats.tto_texts_optimized == 1


class TestTokenOptimizerCombined:
    """Tests for combined optimization and reporting."""

    def test_optimize_general(self):
        opt = TokenOptimizer()
        opt._rtk_available = True
        result = opt.optimize("git status", context="command")
        assert result == "rtk git status"

    def test_optimize_auto_detect(self):
        opt = TokenOptimizer()
        result = opt.optimize("some text", context="general")
        assert result == "some text"

    def test_savings_report(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=True, enable_tto=True)
        opt._rtk_available = True
        opt._lean_ctx_available = True
        opt.optimize_command("git status")
        opt.optimize_file_read("/test.py")
        opt.optimize_thai("ขอบคุณมากครับ")

        report = opt.get_savings_report()
        assert report["rtk_commands_optimized"] == 1
        assert report["lean_ctx_reads_optimized"] == 1
        assert report["tto_texts_optimized"] == 1
        assert report["rtk_available"] is True
        assert report["lean_ctx_available"] is True
        assert report["tto_enabled"] is True

    def test_reset_stats(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        opt.optimize_command("git status")
        assert opt.stats.rtk_commands_optimized == 1
        opt.reset_stats()
        assert opt.stats.rtk_commands_optimized == 0

    def test_batch_commands(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        opt._rtk_available = True
        results = opt.optimize_commands(["git status", "echo hi", "cargo test"])
        assert results[0] == "rtk git status"
        assert results[1] == "echo hi"  # echo is skipped
        assert results[2] == "rtk cargo test"

    def test_singleton(self):
        opt1 = get_optimizer()
        opt2 = get_optimizer()
        assert opt1 is opt2


class TestTokenOptimizerAvailabilty:
    """Tests for availability detection."""

    def test_rtk_unavailable(self):
        opt = TokenOptimizer(enable_rtk=True, enable_lean_ctx=False, enable_tto=False)
        # Mock rtk as not found
        opt._rtk_available = False
        result = opt.optimize_command("git status")
        assert result == "git status"  # No prefix

    def test_lean_ctx_unavailable(self):
        opt = TokenOptimizer(enable_rtk=False, enable_lean_ctx=True, enable_tto=False)
        opt._lean_ctx_available = False
        result = opt.optimize_file_read("/test.py")
        assert result == "cat /test.py"  # Falls back to cat
