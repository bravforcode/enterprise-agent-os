"""Enterprise Agent OS — Session Memory.

Persistent memory for task outcomes, codebase knowledge, and user preferences.
SQLite-backed for simplicity — no Redis/Postgres needed.

Features:
- Task memory: store prompt, routing decision, outcome, duration, tokens
- Codebase knowledge: file understanding, patterns, architecture decisions
- Preference memory: user preferences (terse mode, language, etc.)
- BM25 recall: keyword-based relevance scoring
- Recency boost: recent memories ranked higher
- Auto-cleanup: old memories decay over time
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Any, Optional


# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TaskRecord:
    """A completed task with its outcome."""

    task_id: str = ""
    prompt: str = ""
    routing_decision: dict[str, Any] = field(default_factory=dict)
    outcome: str = ""
    success: bool = True
    duration_ms: float = 0.0
    tokens_used: int = 0
    agent_type: str = ""
    intent: str = ""
    domain: str = ""
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = uuid.uuid4().hex[:12]
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()


@dataclass
class CodebaseKnowledge:
    """Codebase understanding (files, patterns, architecture decisions)."""

    path: str = ""
    file_type: str = ""
    summary: str = ""
    patterns: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    architecture_notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        now = datetime.utcnow().isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now


@dataclass
class MemoryRecord:
    """A recalled memory entry."""

    memory_id: str = ""
    content: str = ""
    memory_type: str = ""  # task, codebase, preference
    score: float = 0.0
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionSummary:
    """Summary of the current session."""

    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_tokens: int = 0
    total_duration_ms: float = 0.0
    top_intents: list[tuple[str, int]] = field(default_factory=list)
    top_agents: list[tuple[str, int]] = field(default_factory=list)
    preferences_stored: int = 0
    codebase_entries: int = 0


# ─────────────────────────────────────────────────────────────────────────────
# Session Memory
# ─────────────────────────────────────────────────────────────────────────────

class SessionMemory:
    """Persistent memory for task outcomes, codebase knowledge, user preferences.

    SQLite-backed. BM25 keyword recall with recency boost.

    Usage:
        mem = SessionMemory()
        mem.remember_task(TaskRecord(prompt="Fix auth bug", success=True))
        results = mem.recall("auth bug")
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize with optional SQLite path.

        Args:
            db_path: Path to SQLite database. None = in-memory.
        """
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()
        self._init_schema()

    def _connect(self) -> None:
        """Open SQLite connection."""
        if self._db_path:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        else:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        assert self._conn is not None
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                routing_decision TEXT DEFAULT '{}',
                outcome TEXT DEFAULT '',
                success INTEGER DEFAULT 1,
                duration_ms REAL DEFAULT 0,
                tokens_used INTEGER DEFAULT 0,
                agent_type TEXT DEFAULT '',
                intent TEXT DEFAULT '',
                domain TEXT DEFAULT '',
                extra TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS codebase (
                id TEXT PRIMARY KEY,
                path TEXT NOT NULL,
                file_type TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                patterns TEXT DEFAULT '[]',
                dependencies TEXT DEFAULT '[]',
                architecture_notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_intent ON tasks(intent);
            CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(agent_type);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
            CREATE INDEX IF NOT EXISTS idx_codebase_path ON codebase(path);
        """)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Task memory ──────────────────────────────────────────────────────

    def remember_task(self, task: TaskRecord) -> str:
        """Store a completed task with its outcome.

        Args:
            task: TaskRecord to store.

        Returns:
            Task ID.
        """
        assert self._conn is not None
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO tasks
               (id, prompt, routing_decision, outcome, success,
                duration_ms, tokens_used, agent_type, intent, domain,
                extra, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task.task_id,
                task.prompt,
                json.dumps(task.routing_decision, default=str),
                task.outcome,
                1 if task.success else 0,
                task.duration_ms,
                task.tokens_used,
                task.agent_type,
                task.intent,
                task.domain,
                json.dumps(task.extra, default=str),
                task.created_at or now,
                now,
            ),
        )
        self._conn.commit()
        return task.task_id

    # ── Codebase knowledge ───────────────────────────────────────────────

    def remember_codebase(self, knowledge: CodebaseKnowledge) -> str:
        """Store codebase understanding.

        Args:
            knowledge: CodebaseKnowledge to store.

        Returns:
            Entry ID.
        """
        assert self._conn is not None
        entry_id = hashlib.md5(knowledge.path.encode()).hexdigest()[:12]
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO codebase
               (id, path, file_type, summary, patterns, dependencies,
                architecture_notes, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry_id,
                knowledge.path,
                knowledge.file_type,
                knowledge.summary,
                json.dumps(knowledge.patterns),
                json.dumps(knowledge.dependencies),
                knowledge.architecture_notes,
                knowledge.created_at or now,
                now,
            ),
        )
        self._conn.commit()
        return entry_id

    def recall_codebase(self, query: str) -> list[CodebaseKnowledge]:
        """Recall relevant codebase knowledge.

        Args:
            query: Search query.

        Returns:
            List of matching CodebaseKnowledge, ranked by relevance.
        """
        assert self._conn is not None
        rows = self._conn.execute(
            "SELECT * FROM codebase ORDER BY updated_at DESC LIMIT 50"
        ).fetchall()

        query_words = set(query.lower().split())
        scored: list[tuple[float, Any]] = []

        for row in rows:
            text = f"{row['path']} {row['summary']} {row['architecture_notes']}".lower()
            words = set(text.split())
            overlap = len(query_words & words)
            # Recency boost
            try:
                updated = datetime.fromisoformat(row["updated_at"])
                age_hours = (datetime.utcnow() - updated).total_seconds() / 3600
                recency = 1.0 / (1.0 + age_hours / 24)
            except Exception:
                recency = 0.5

            score = overlap * 0.7 + recency * 0.3
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda x: -x[0])
        results = []
        for _, row in scored[:5]:
            results.append(CodebaseKnowledge(
                path=row["path"],
                file_type=row["file_type"],
                summary=row["summary"],
                patterns=json.loads(row["patterns"]) if row["patterns"] else [],
                dependencies=json.loads(row["dependencies"]) if row["dependencies"] else [],
                architecture_notes=row["architecture_notes"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            ))
        return results

    # ── Preference memory ────────────────────────────────────────────────

    def remember_preference(self, key: str, value: str) -> None:
        """Store a user preference.

        Args:
            key: Preference key (e.g., 'terse_mode', 'language').
            value: Preference value.
        """
        assert self._conn is not None
        now = datetime.utcnow().isoformat()
        self._conn.execute(
            """INSERT OR REPLACE INTO preferences (key, value, created_at, updated_at)
               VALUES (?, ?, ?, ?)""",
            (key, value, now, now),
        )
        self._conn.commit()

    def get_preference(self, key: str, default: str = "") -> str:
        """Get a user preference by key.

        Args:
            key: Preference key.
            default: Default value if not found.

        Returns:
            Preference value or default.
        """
        assert self._conn is not None
        row = self._conn.execute(
            "SELECT value FROM preferences WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def get_all_preferences(self) -> dict[str, str]:
        """Get all stored preferences.

        Returns:
            Dict of key → value.
        """
        assert self._conn is not None
        rows = self._conn.execute("SELECT key, value FROM preferences").fetchall()
        return {row["key"]: row["value"] for row in rows}

    # ── BM25 Recall ──────────────────────────────────────────────────────

    def recall(
        self,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """Recall relevant memories for a query using BM25-style scoring.

        Args:
            query: Search query.
            limit: Max results to return.
            memory_type: Filter by type ('task', 'codebase', 'preference').

        Returns:
            List of MemoryRecord, scored by relevance.
        """
        assert self._conn is not None
        query_words = query.lower().split()
        results: list[MemoryRecord] = []

        # Search tasks
        if memory_type is None or memory_type == "task":
            rows = self._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            for row in rows:
                score = self._bm25_score(query_words, row["prompt"] + " " + row["outcome"])
                if score > 0:
                    results.append(MemoryRecord(
                        memory_id=row["id"],
                        content=row["prompt"],
                        memory_type="task",
                        score=score,
                        created_at=row["created_at"],
                        extra={
                            "outcome": row["outcome"],
                            "success": bool(row["success"]),
                            "agent_type": row["agent_type"],
                            "intent": row["intent"],
                        },
                    ))

        # Search codebase
        if memory_type is None or memory_type == "codebase":
            rows = self._conn.execute(
                "SELECT * FROM codebase ORDER BY updated_at DESC LIMIT 100"
            ).fetchall()
            for row in rows:
                text = f"{row['path']} {row['summary']} {row['architecture_notes']}"
                score = self._bm25_score(query_words, text)
                if score > 0:
                    results.append(MemoryRecord(
                        memory_id=row["id"],
                        content=row["summary"],
                        memory_type="codebase",
                        score=score,
                        created_at=row["created_at"],
                        extra={
                            "path": row["path"],
                            "file_type": row["file_type"],
                        },
                    ))

        # Search preferences
        if memory_type is None or memory_type == "preference":
            rows = self._conn.execute(
                "SELECT * FROM preferences"
            ).fetchall()
            for row in rows:
                score = self._bm25_score(query_words, f"{row['key']} {row['value']}")
                if score > 0:
                    results.append(MemoryRecord(
                        memory_id=row["key"],
                        content=f"{row['key']}: {row['value']}",
                        memory_type="preference",
                        score=score,
                        created_at=row.get("created_at", ""),
                    ))

        # Sort by score descending, then by recency
        results.sort(key=lambda r: -r.score)

        # Apply recency boost
        for r in results:
            try:
                created = datetime.fromisoformat(r.created_at)
                age_hours = (datetime.utcnow() - created).total_seconds() / 3600
                recency_boost = 1.0 / (1.0 + age_hours / 24)
                r.score = r.score * 0.7 + recency_boost * 0.3
            except Exception:
                pass

        results.sort(key=lambda r: -r.score)
        return results[:limit]

    def _bm25_score(self, query_words: list[str], text: str) -> float:
        """Simple BM25-inspired scoring.

        Uses keyword overlap with length normalization.
        No IDF weighting (keeps it simple without a corpus).
        """
        if not query_words or not text:
            return 0.0

        text_lower = text.lower()
        text_words = text_lower.split()
        text_len = max(len(text_words), 1)

        # Term frequency with saturation
        score = 0.0
        for word in query_words:
            tf = text_lower.count(word)
            if tf > 0:
                # BM25 saturation: tf / (tf + k1)
                saturated = tf / (tf + 1.5)
                # Length penalty
                length_penalty = 1.0 / (1.0 + 0.5 * (text_len / 100))
                score += saturated * length_penalty

        return score / max(len(query_words), 1)

    # ── Session summary ──────────────────────────────────────────────────

    def get_session_summary(self) -> SessionSummary:
        """Get summary of all stored data.

        Returns:
            SessionSummary with aggregate stats.
        """
        assert self._conn is not None

        # Task stats
        task_rows = self._conn.execute(
            "SELECT intent, agent_type, success, tokens_used, duration_ms FROM tasks"
        ).fetchall()

        total = len(task_rows)
        successful = sum(1 for r in task_rows if r["success"])
        failed = total - successful
        total_tokens = sum(r["tokens_used"] for r in task_rows)
        total_duration = sum(r["duration_ms"] for r in task_rows)

        # Top intents
        intent_counts: dict[str, int] = {}
        for r in task_rows:
            intent_counts[r["intent"]] = intent_counts.get(r["intent"], 0) + 1
        top_intents = sorted(intent_counts.items(), key=lambda x: -x[1])[:5]

        # Top agents
        agent_counts: dict[str, int] = {}
        for r in task_rows:
            agent_counts[r["agent_type"]] = agent_counts.get(r["agent_type"], 0) + 1
        top_agents = sorted(agent_counts.items(), key=lambda x: -x[1])[:5]

        # Other counts
        pref_count = self._conn.execute("SELECT COUNT(*) as c FROM preferences").fetchone()["c"]
        codebase_count = self._conn.execute("SELECT COUNT(*) as c FROM codebase").fetchone()["c"]

        return SessionSummary(
            total_tasks=total,
            successful_tasks=successful,
            failed_tasks=failed,
            total_tokens=total_tokens,
            total_duration_ms=total_duration,
            top_intents=top_intents,
            top_agents=top_agents,
            preferences_stored=pref_count,
            codebase_entries=codebase_count,
        )

    # ── Auto-cleanup ─────────────────────────────────────────────────────

    def cleanup(self, max_age_days: int = 30, max_tasks: int = 500) -> int:
        """Remove old memories beyond age or count limits.

        Args:
            max_age_days: Remove tasks older than this.
            max_tasks: Keep at most this many tasks.

        Returns:
            Number of entries removed.
        """
        assert self._conn is not None
        cutoff = (datetime.utcnow() - timedelta(days=max_age_days)).isoformat()

        # Remove old tasks
        result = self._conn.execute(
            "DELETE FROM tasks WHERE created_at < ?", (cutoff,)
        )
        removed = result.rowcount

        # Remove excess tasks (keep newest)
        total = self._conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"]
        if total > max_tasks:
            excess = total - max_tasks
            result = self._conn.execute(
                """DELETE FROM tasks WHERE id IN
                   (SELECT id FROM tasks ORDER BY created_at ASC LIMIT ?)""",
                (excess,),
            )
            removed += result.rowcount

        # Remove old codebase entries
        result = self._conn.execute(
            "DELETE FROM codebase WHERE updated_at < ?", (cutoff,)
        )
        removed += result.rowcount

        self._conn.commit()
        return removed

    def get_stats(self) -> dict[str, int]:
        """Get memory statistics."""
        assert self._conn is not None
        return {
            "tasks": self._conn.execute("SELECT COUNT(*) as c FROM tasks").fetchone()["c"],
            "codebase": self._conn.execute("SELECT COUNT(*) as c FROM codebase").fetchone()["c"],
            "preferences": self._conn.execute("SELECT COUNT(*) as c FROM preferences").fetchone()["c"],
        }
