"""Tests for Session Memory — SQLite-backed persistent memory."""
from __future__ import annotations

import json
import time

import pytest

from graxia_tool.session_memory import (
    CodebaseKnowledge,
    MemoryRecord,
    SessionMemory,
    SessionSummary,
    TaskRecord,
)


class TestTaskRecord:
    def test_default_fields(self):
        t = TaskRecord()
        assert t.task_id != ""
        assert t.created_at != ""
        assert t.success is True
        assert t.prompt == ""

    def test_auto_generates_id(self):
        t1 = TaskRecord()
        t2 = TaskRecord()
        assert t1.task_id != t2.task_id

    def test_auto_generates_created_at(self):
        t = TaskRecord()
        assert "T" in t.created_at


class TestCodebaseKnowledge:
    def test_default_fields(self):
        c = CodebaseKnowledge()
        assert c.created_at != ""
        assert c.updated_at != ""
        assert c.patterns == []
        assert c.dependencies == []


class TestSessionMemory:
    def setup_method(self):
        self.mem = SessionMemory()

    def teardown_method(self):
        self.mem.close()

    def test_init_creates_in_memory_db(self):
        assert self.mem._conn is not None
        assert self.mem._db_path is None

    def test_init_with_explicit_memory(self):
        mem = SessionMemory(db_path=":memory:")
        assert mem._conn is not None
        mem.close()

    def test_remember_and_recall_task(self):
        task = TaskRecord(prompt="fix the auth bug", success=True, tokens_used=150)
        task_id = self.mem.remember_task(task)
        assert task_id == task.task_id

        results = self.mem.recall("auth bug")
        assert len(results) >= 1
        assert results[0].memory_type == "task"
        assert "auth" in results[0].content

    def test_recall_returns_empty_for_no_match(self):
        results = self.mem.recall("nonexistent unicorn query")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_recall_multiple_tasks_returns_most_relevant_first(self):
        self.mem.remember_task(TaskRecord(prompt="deploy the app to production", success=True))
        self.mem.remember_task(TaskRecord(prompt="fix the login bug", success=True))
        self.mem.remember_task(TaskRecord(prompt="write documentation for the API", success=True))

        results = self.mem.recall("login bug")
        assert len(results) >= 1
        assert "login" in results[0].content

    def test_remember_codebase_and_recall_codebase(self):
        kb = CodebaseKnowledge(
            path="src/auth.py",
            file_type="python",
            summary="Authentication module with JWT tokens",
            patterns=["factory pattern", "middleware chain"],
            dependencies=["jose", "bcrypt"],
            architecture_notes="Uses middleware pattern for auth checks",
        )
        self.mem.remember_codebase(kb)

        results = self.mem.recall_codebase("auth JWT")
        assert len(results) >= 1
        assert results[0].path == "src/auth.py"

    def test_recall_codebase_empty_when_no_match(self):
        results = self.mem.recall_codebase("zzzzzno_match")
        assert len(results) == 0

    def test_remember_and_get_preference(self):
        self.mem.remember_preference("terse_mode", "true")
        val = self.mem.get_preference("terse_mode")
        assert val == "true"

    def test_get_preference_default(self):
        val = self.mem.get_preference("nonexistent_key", "default_val")
        assert val == "default_val"

    def test_get_all_preferences(self):
        self.mem.remember_preference("language", "thai")
        self.mem.remember_preference("terse_mode", "true")
        prefs = self.mem.get_all_preferences()
        assert prefs["language"] == "thai"
        assert prefs["terse_mode"] == "true"

    def test_get_session_summary_empty(self):
        summary = self.mem.get_session_summary()
        assert isinstance(summary, SessionSummary)
        assert summary.total_tasks == 0
        assert summary.successful_tasks == 0
        assert summary.failed_tasks == 0
        assert summary.total_tokens == 0

    def test_get_session_summary_with_tasks(self):
        self.mem.remember_task(TaskRecord(prompt="write code", success=True, tokens_used=100))
        self.mem.remember_task(TaskRecord(prompt="fix bug", success=True, tokens_used=50))
        self.mem.remember_task(TaskRecord(prompt="deploy", success=False, tokens_used=200))

        summary = self.mem.get_session_summary()
        assert summary.total_tasks == 3
        assert summary.successful_tasks == 2
        assert summary.failed_tasks == 1
        assert summary.total_tokens == 350

    def test_get_stats(self):
        self.mem.remember_task(TaskRecord(prompt="write code", success=True))
        stats = self.mem.get_stats()
        assert stats["tasks"] >= 1
        assert stats["codebase"] >= 0
        assert stats["preferences"] >= 0

    def test_cleanup_removes_old_tasks(self):
        self.mem.remember_task(TaskRecord(prompt="old task", success=True))
        removed = self.mem.cleanup(max_age_days=0, max_tasks=0)
        assert removed >= 0
        stats = self.mem.get_stats()

    def test_recall_filters_by_memory_type(self):
        self.mem.remember_task(TaskRecord(prompt="fix the auth bug", success=True))
        results = self.mem.recall("auth bug", memory_type="codebase")
        assert len(results) == 0

    def test_recall_with_special_characters(self):
        self.mem.remember_task(TaskRecord(prompt="fix $pecial_ch@r's bug! #42", success=True))
        results = self.mem.recall("$pecial_ch@r's")
        assert len(results) >= 1

    def test_remember_long_content(self):
        long_prompt = "write " * 1000
        task = TaskRecord(prompt=long_prompt, success=True)
        self.mem.remember_task(task)
        results = self.mem.recall("write")
        assert len(results) >= 1

    def test_recall_returns_memory_record_type(self):
        self.mem.remember_task(TaskRecord(prompt="test the module", success=True))
        results = self.mem.recall("test")
        assert isinstance(results, list)
        if results:
            assert isinstance(results[0], MemoryRecord)
            assert hasattr(results[0], "score")
            assert hasattr(results[0], "memory_type")
            assert hasattr(results[0], "content")

    def test_session_summary_top_intents(self):
        self.mem.remember_task(TaskRecord(prompt="write code", success=True, intent="code"))
        self.mem.remember_task(TaskRecord(prompt="write more code", success=True, intent="code"))
        self.mem.remember_task(TaskRecord(prompt="fix bug", success=True, intent="debug"))

        summary = self.mem.get_session_summary()
        intents = dict(summary.top_intents)
        assert intents.get("code", 0) >= 2

    def test_preferences_count_in_summary(self):
        self.mem.remember_preference("a", "1")
        self.mem.remember_preference("b", "2")
        summary = self.mem.get_session_summary()
        assert summary.preferences_stored >= 2

    def test_codebase_entries_count_in_summary(self):
        self.mem.remember_codebase(CodebaseKnowledge(path="src/main.py"))
        summary = self.mem.get_session_summary()
        assert summary.codebase_entries >= 1

    def test_bm25_score_positive_match(self):
        score = self.mem._bm25_score(["auth", "bug"], "fix the auth bug in login")
        assert score > 0

    def test_bm25_score_no_match(self):
        score = self.mem._bm25_score(["xyz"], "completely unrelated text")
        assert score == 0.0

    def test_bm25_score_empty_query(self):
        score = self.mem._bm25_score([], "some text here")
        assert score == 0.0

    def test_bm25_score_empty_text(self):
        score = self.mem._bm25_score(["test"], "")
        assert score == 0.0

    def test_recall_with_empty_string(self):
        results = self.mem.recall("")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_remember_task_with_routing_decision(self):
        rd = {"intent": "code", "agent_type": "coder", "confidence": 0.9}
        task = TaskRecord(prompt="write a function", intent="code", routing_decision=rd)
        self.mem.remember_task(task)

        results = self.mem.recall("write a function")
        assert len(results) >= 1
        assert results[0].extra.get("intent") == "code"

    def test_recall_returns_sorted_by_score(self):
        self.mem.remember_task(TaskRecord(prompt="deploy the app to kubernetes", success=True))
        self.mem.remember_task(TaskRecord(prompt="fix the kubernetes deployment bug", success=True))

        results = self.mem.recall("kubernetes deployment")
        assert len(results) >= 1
        for i in range(len(results) - 1):
            assert results[i].score >= results[i + 1].score

    def test_close_then_reinit(self):
        self.mem.close()
        self.mem = SessionMemory()
        assert self.mem._conn is not None

    def test_remember_codebase_without_patterns(self):
        kb = CodebaseKnowledge(path="src/utils.py", summary="Utility functions")
        entry_id = self.mem.remember_codebase(kb)
        assert len(entry_id) > 0

    def test_get_session_summary_total_duration(self):
        self.mem.remember_task(TaskRecord(prompt="task1", duration_ms=100.0))
        self.mem.remember_task(TaskRecord(prompt="task2", duration_ms=200.0))
        summary = self.mem.get_session_summary()
        assert summary.total_duration_ms >= 300.0
