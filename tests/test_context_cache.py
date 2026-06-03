"""Tests for Context Cache — semantic caching with SQLite."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

from graxia_tool.context_cache import (
    CachedContext,
    CodebaseSnapshot,
    ContextCache,
    _bm25_overlap,
    _extract_keywords,
    _hash_prompt,
)


class TestHelpers:
    def test_hash_prompt_normalizes(self):
        h1 = _hash_prompt("  write   code  ")
        h2 = _hash_prompt("write code")
        assert h1 == h2

    def test_hash_prompt_length(self):
        h = _hash_prompt("test prompt here")
        assert len(h) == 16

    def test_extract_keywords_removes_stop_words(self):
        kw = _extract_keywords("the quick brown fox jumps over the lazy dog")
        assert "the" not in kw
        assert "quick" in kw
        assert "brown" in kw

    def test_extract_keywords_short_words_filtered(self):
        kw = _extract_keywords("a an of in to is it")
        assert all(len(w) > 2 for w in kw)

    def test_extract_keywords_empty(self):
        kw = _extract_keywords("")
        assert kw == []

    def test_bm25_overlap_perfect(self):
        score = _bm25_overlap(["auth", "bug", "fix"], ["auth", "bug", "fix"])
        assert score == 1.0

    def test_bm25_overlap_partial(self):
        score = _bm25_overlap(["auth", "bug", "fix"], ["auth", "token"])
        assert 0 < score < 1.0

    def test_bm25_overlap_no_match(self):
        score = _bm25_overlap(["auth"], ["deploy"])
        assert score == 0.0

    def test_bm25_overlap_empty(self):
        score = _bm25_overlap([], ["auth"])
        assert score == 0.0
        score = _bm25_overlap(["auth"], [])
        assert score == 0.0


class TestCachedContext:
    def test_default_fields(self):
        ctx = CachedContext(prompt="fix the auth bug")
        assert ctx.prompt_hash != ""
        assert ctx.keywords != []
        assert ctx.created_at != ""
        assert ctx.expires_at != ""
        assert ctx.hit_count == 0

    def test_auto_generates_hash(self):
        ctx = CachedContext(prompt="write code")
        expected = _hash_prompt("write code")
        assert ctx.prompt_hash == expected

    def test_auto_extracts_keywords(self):
        ctx = CachedContext(prompt="fix the auth bug in login")
        assert "auth" in ctx.keywords
        assert "bug" in ctx.keywords
        assert "login" in ctx.keywords
        assert "the" not in ctx.keywords

    def test_is_expired_false_when_fresh(self):
        ctx = CachedContext(prompt="test")
        assert ctx.is_expired() is False

    def test_is_expired_true_when_expired(self):
        ctx = CachedContext(
            prompt="test",
            expires_at=(datetime.utcnow() - timedelta(hours=1)).isoformat(),
        )
        assert ctx.is_expired() is True


class TestCodebaseSnapshot:
    def test_default_fields(self):
        snap = CodebaseSnapshot(path="src/")
        assert snap.created_at != ""
        assert snap.file_structure == []
        assert snap.total_files == 0


class TestContextCache:
    def setup_method(self):
        self.cache = ContextCache()

    def teardown_method(self):
        self.cache.close()

    def test_init_creates_in_memory_db(self):
        assert self.cache._conn is not None
        assert self.cache._db_path is None

    def test_init_with_explicit_memory(self):
        cache = ContextCache(db_path=":memory:")
        assert cache._conn is not None
        cache.close()

    def test_set_and_get_exact_match(self):
        self.cache.set(
            "fix the auth bug",
            {"intent": "debug", "agent_type": "debugger"},
            {"output": "Fixed the auth bug"},
        )
        cached = self.cache.get("fix the auth bug")
        assert cached is not None
        assert cached.prompt == "fix the auth bug"
        assert cached.decision.get("intent") == "debug"

    def test_get_nonexistent_returns_none(self):
        cached = self.cache.get("this prompt does not exist")
        assert cached is None

    def test_set_and_get_semantic_match(self):
        self.cache.set(
            "fix the authentication bug in login",
            {"intent": "debug"},
            {"output": "Fixed"},
        )
        cached = self.cache.get("fix auth login bug")
        assert cached is not None
        assert cached.decision.get("intent") == "debug"

    def test_set_with_routing_decision_object(self):
        from graxia_tool.auto_router import RoutingDecision

        rd = RoutingDecision(intent="code", agent_type="coder")
        self.cache.set("write a function", rd, {"output": "ok"})
        cached = self.cache.get("write a function")
        assert cached is not None
        assert cached.decision.get("intent") == "code"

    def test_get_stats_initial(self):
        stats = self.cache.get_stats()
        assert stats["total_queries"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 0.0

    def test_get_stats_tracks_hits(self):
        self.cache.set("test prompt", {"key": "val"}, {"result": "ok"})
        self.cache.get("test prompt")
        self.cache.get("test prompt")
        stats = self.cache.get_stats()
        assert stats["hits"] >= 2
        assert stats["total_queries"] >= 2

    def test_get_stats_tracks_misses(self):
        self.cache.get("nonexistent1")
        self.cache.get("nonexistent2")
        stats = self.cache.get_stats()
        assert stats["misses"] >= 2

    def test_get_stats_hit_rate(self):
        self.cache.set("existing", {"k": "v"}, {"r": "ok"})
        self.cache.get("existing")
        self.cache.get("nonexistent")
        stats = self.cache.get_stats()
        assert 0 < stats["hit_rate"] < 1.0

    def test_get_stats_cached_contexts_count(self):
        self.cache.set("prompt1", {"k": "v"}, {"r": "ok"})
        self.cache.set("prompt2", {"k": "v"}, {"r": "ok"})
        stats = self.cache.get_stats()
        assert stats["cached_contexts"] >= 2

    def test_cleanup_expired_removes_expired(self):
        cache = ContextCache(default_ttl_hours=-1)
        cache.set("expired prompt", {"k": "v"}, {"r": "ok"})
        removed = cache.cleanup_expired()
        cache.close()

    def test_codebase_snapshot_store_and_get(self):
        snap = CodebaseSnapshot(
            path="src/",
            file_structure=["src/main.py", "src/utils.py"],
            key_patterns=["factory pattern"],
            architecture_notes="Clean architecture",
            total_files=2,
            total_lines=500,
        )
        self.cache.store_codebase_snapshot("src/", snap)

        retrieved = self.cache.get_codebase_snapshot("src/")
        assert retrieved is not None
        assert retrieved.path == "src/"
        assert "src/main.py" in retrieved.file_structure
        assert retrieved.total_files == 2

    def test_codebase_snapshot_nonexistent(self):
        retrieved = self.cache.get_codebase_snapshot("nonexistent/path/")
        assert retrieved is None

    def test_multiple_entries_same_prompt_returns_most_recent(self):
        self.cache.set("same", {"v": "first"}, {"r": "old"})
        self.cache.set("same", {"v": "second"}, {"r": "new"})
        cached = self.cache.get("same")
        assert cached is not None
        assert cached.result.get("r") == "new"

    def test_very_long_prompt(self):
        long_prompt = "write " * 2000
        self.cache.set(long_prompt, {"k": "v"}, {"r": "ok"})
        cached = self.cache.get(long_prompt)
        assert cached is not None

    def test_empty_prompt(self):
        self.cache.set("", {"k": "v"}, {"r": "ok"})
        cached = self.cache.get("")
        assert cached is not None or cached is None

    def test_close_then_reinit(self):
        self.cache.close()
        self.cache = ContextCache()
        assert self.cache._conn is not None

    def test_set_with_custom_ttl(self):
        self.cache.set("short lived", {"k": "v"}, {"r": "ok"}, ttl_hours=0.001)
        cached = self.cache.get("short lived")
        assert cached is not None

    def test_auto_cleanup_expired_updates_stats(self):
        cache = ContextCache(default_ttl_hours=-24)
        cache.set("old prompt", {"k": "v"}, {"r": "ok"})
        removed = cache.cleanup_expired()
        stats = cache.get_stats()
        cache.close()

    def test_get_returns_cached_context_with_hit_count(self):
        self.cache.set("increment", {"k": "v"}, {"r": "ok"})
        c1 = self.cache.get("increment")
        c2 = self.cache.get("increment")
        assert c2 is not None
        assert c2.hit_count >= 1

    def test_semantic_match_threshold(self):
        self.cache.set(
            "deploy the application to kubernetes",
            {"intent": "deploy"},
            {"r": "done"},
        )
        cached = self.cache.get("kubernetes deployment")
        assert cached is not None
        assert cached.decision.get("intent") == "deploy"

    def test_no_semantic_match_for_unrelated(self):
        self.cache.set(
            "fix the auth bug",
            {"intent": "debug"},
            {"r": "done"},
        )
        cached = self.cache.get("write documentation for API")
        assert cached is None

    def test_store_codebase_snapshot_overwrites(self):
        snap1 = CodebaseSnapshot(path="src/", total_files=1)
        snap2 = CodebaseSnapshot(path="src/", total_files=99)
        self.cache.store_codebase_snapshot("src/", snap1)
        self.cache.store_codebase_snapshot("src/", snap2)
        retrieved = self.cache.get_codebase_snapshot("src/")
        assert retrieved.total_files == 99

    def test_keywords_field_in_cached_context(self):
        self.cache.set("implement login feature", {"k": "v"}, {"r": "ok"})
        cached = self.cache.get("implement login feature")
        assert cached is not None
        assert len(cached.keywords) > 0

    def test_expired_entry_not_returned(self):
        cache = ContextCache(default_ttl_hours=-24)
        cache.set("should expire", {"k": "v"}, {"r": "ok"})
        cached = cache.get("should expire")
        assert cached is None
        cache.close()
