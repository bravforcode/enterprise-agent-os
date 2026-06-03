"""Unified memory — sync between SessionMemory and Obsidian vault.

Bidirectional bridge:
- SessionMemory (SQLite) → fast BM25 recall, lightweight
- Obsidian vault → rich markdown notes, wiki-links, human-readable

Sync direction: SessionMemory is source of truth for task outcomes.
Vault gets enriched markdown notes for human browsing.
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("graxia_tool.memory.vault_sync")

VAULT_PATH = Path(os.environ.get(
    "AGENT_OS_VAULT_PATH",
    r"C:\Users\menum\Documents\ObsidianVault\Second Brain",
))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SyncResult:
    """Result of a vault sync operation."""
    success: bool = True
    vault_path: str = ""
    task_id: str = ""
    action: str = ""  # synced, skipped, error
    message: str = ""
    note_count: int = 0


# ---------------------------------------------------------------------------
# VaultMemorySync
# ---------------------------------------------------------------------------

class VaultMemorySync:
    """Sync task outcomes between SessionMemory (SQLite) and Obsidian vault.

    The vault gets rich markdown notes under:
        03-Resources/Graxia Tasks/

    SessionMemory remains the fast-recall engine.
    Vault provides human-readable, linkable, browsable knowledge.

    Usage:
        sync = VaultMemorySync()
        result = sync.sync_task(task_id, prompt, success, agent_type, outcome)
        results = sync.search_vault("auth bug")
        tasks = sync.list_synced_tasks(days=7)
    """

    def __init__(
        self,
        vault_path: Optional[str | Path] = None,
        memory_db_path: Optional[str] = None,
    ):
        self.vault_path = Path(vault_path or VAULT_PATH)
        self.tasks_dir = self.vault_path / "03-Resources" / "Graxia Tasks"
        self._memory_db_path = memory_db_path

    # ------------------------------------------------------------------
    # Core sync: SessionMemory → Vault
    # ------------------------------------------------------------------

    def sync_task(
        self,
        task_id: str,
        prompt: str,
        success: bool,
        agent_type: str = "",
        outcome: str = "",
        intent: str = "",
        domain: str = "",
        duration_ms: float = 0.0,
        tokens_used: int = 0,
        routing_decision: Optional[Dict[str, Any]] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> SyncResult:
        """Sync a single task outcome to the vault as a markdown note.

        Creates a note at: 03-Resources/Graxia Tasks/{date}-{task_id[:8]}.md
        With YAML frontmatter, wiki-links, and structured content.

        Returns:
            SyncResult with vault path and status.
        """
        if not task_id:
            return SyncResult(success=False, action="error", message="task_id is required")

        try:
            self.tasks_dir.mkdir(parents=True, exist_ok=True)

            date = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H:%M:%S")
            short_id = task_id[:8]
            filename = f"{date}-{short_id}.md"
            note_path = self.tasks_dir / filename

            # Build tags
            tags = ["agent-os", "task"]
            if agent_type:
                tags.append(agent_type)
            if success:
                tags.append("success")
            else:
                tags.append("failed")
            if intent:
                tags.append(intent)

            # Build frontmatter
            fm_lines = [
                "---",
                f'task_id: "{task_id}"',
                f'created_at: "{datetime.now().isoformat()}"',
                f'date: "{date}"',
                f'agent_type: "{agent_type}"',
                f"success: {str(success).lower()}",
                f"duration_ms: {duration_ms}",
                f"tokens_used: {tokens_used}",
                f"intent: \"{intent}\"",
                f"domain: \"{domain}\"",
                "tags: [" + ", ".join(tags) + "]",
            ]

            if routing_decision:
                fm_lines.append(f'routing_decision: "{json.dumps(routing_decision, default=str)}"')
            if extra:
                fm_lines.append(f'extra: "{json.dumps(extra, default=str)}"')

            fm_lines.append("---")
            frontmatter = "\n".join(fm_lines)

            # Build body
            status_emoji = "PASS" if success else "FAIL"
            body_lines = [
                "",
                f"# Task {status_emoji}: {prompt[:80]}",
                "",
                f"**Agent:** `{agent_type or 'unknown'}`  ",
                f"**Time:** {time_str}  ",
                f"**Duration:** {duration_ms:.0f}ms  ",
                f"**Tokens:** {tokens_used:,}",
                "",
            ]

            if intent:
                body_lines.append(f"**Intent:** `{intent}`  ")
            if domain:
                body_lines.append(f"**Domain:** `{domain}`  ")
            if routing_decision:
                body_lines.append("")
                body_lines.append("## Routing Decision")
                body_lines.append(f"```json")
                body_lines.append(json.dumps(routing_decision, indent=2, default=str))
                body_lines.append(f"```")

            if outcome:
                body_lines.append("")
                body_lines.append("## Outcome")
                body_lines.append(outcome)

            # Wiki-link to task ID for cross-referencing
            body_lines.append("")
            body_lines.append(f"---")
            body_lines.append(f"Back to [[Graxia Tasks]] | Task ID: `{task_id}`")

            content = frontmatter + "\n" + "\n".join(body_lines) + "\n"
            note_path.write_text(content, encoding="utf-8")

            rel_path = str(note_path.relative_to(self.vault_path)).replace("\\", "/")
            logger.info("synced task %s → %s", task_id[:8], rel_path)

            return SyncResult(
                success=True,
                vault_path=rel_path,
                task_id=task_id,
                action="synced",
                message=f"Note created at {rel_path}",
            )

        except Exception as e:
            logger.exception("sync_task failed for %s", task_id[:8])
            return SyncResult(
                success=False,
                task_id=task_id,
                action="error",
                message=f"{type(e).__name__}: {e}",
            )

    # ------------------------------------------------------------------
    # Sync from SessionMemory records
    # ------------------------------------------------------------------

    def sync_task_record(self, record: Any) -> SyncResult:
        """Sync a TaskRecord (from session_memory) to the vault.

        Args:
            record: A TaskRecord dataclass instance.

        Returns:
            SyncResult.
        """
        return self.sync_task(
            task_id=getattr(record, "task_id", ""),
            prompt=getattr(record, "prompt", ""),
            success=getattr(record, "success", True),
            agent_type=getattr(record, "agent_type", ""),
            outcome=getattr(record, "outcome", ""),
            intent=getattr(record, "intent", ""),
            domain=getattr(record, "domain", ""),
            duration_ms=getattr(record, "duration_ms", 0.0),
            tokens_used=getattr(record, "tokens_used", 0),
            routing_decision=getattr(record, "routing_decision", None),
            extra=getattr(record, "extra", None),
        )

    def sync_all_tasks(self, limit: int = 50) -> List[SyncResult]:
        """Sync all recent tasks from SessionMemory to vault.

        Args:
            limit: Max tasks to sync.

        Returns:
            List of SyncResult.
        """
        from ..session_memory import SessionMemory

        mem = SessionMemory(db_path=self._memory_db_path)
        try:
            # Get recent tasks from SQLite
            assert mem._conn is not None
            rows = mem._conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

            results = []
            for row in rows:
                # Check if already synced
                short_id = row["id"][:8]
                date = row["created_at"][:10] if row["created_at"] else datetime.now().strftime("%Y-%m-%d")
                expected_filename = f"{date}-{short_id}.md"
                expected_path = self.tasks_dir / expected_filename

                if expected_path.exists():
                    results.append(SyncResult(
                        success=True,
                        task_id=row["id"],
                        action="skipped",
                        message=f"Already synced: {expected_filename}",
                    ))
                    continue

                result = self.sync_task(
                    task_id=row["id"],
                    prompt=row["prompt"],
                    success=bool(row["success"]),
                    agent_type=row["agent_type"],
                    outcome=row["outcome"],
                    intent=row["intent"],
                    domain=row.get("domain", ""),
                    duration_ms=row["duration_ms"],
                    tokens_used=row["tokens_used"],
                    routing_decision=json.loads(row["routing_decision"]) if row["routing_decision"] else None,
                    extra=json.loads(row["extra"]) if row["extra"] else None,
                )
                results.append(result)

            return results
        finally:
            mem.close()

    # ------------------------------------------------------------------
    # Vault → SessionMemory (pull)
    # ------------------------------------------------------------------

    def pull_task_from_vault(self, vault_path: str) -> Optional[Dict[str, Any]]:
        """Read a task note from vault and return as a dict.

        Useful for importing vault notes back into SessionMemory.
        """
        full = self.vault_path / vault_path
        if not full.exists():
            return None

        content = full.read_text(encoding="utf-8", errors="ignore")

        # Parse frontmatter
        fm: Dict[str, Any] = {}
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                raw = content[3:end].strip()
                for line in raw.splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if v.lower() == "true":
                            v = True
                        elif v.lower() == "false":
                            v = False
                        elif v.replace(".", "", 1).isdigit():
                            v = float(v) if "." in v else int(v)
                        fm[k] = v

        return {
            "task_id": fm.get("task_id", ""),
            "prompt": full.stem,
            "success": fm.get("success", True),
            "agent_type": fm.get("agent_type", ""),
            "intent": fm.get("intent", ""),
            "domain": fm.get("domain", ""),
            "duration_ms": fm.get("duration_ms", 0),
            "tokens_used": fm.get("tokens_used", 0),
            "created_at": fm.get("created_at", ""),
            "vault_path": vault_path,
        }

    # ------------------------------------------------------------------
    # Search vault for knowledge
    # ------------------------------------------------------------------

    def search_vault(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search vault task notes for knowledge.

        Args:
            query: Search query.
            limit: Max results.

        Returns:
            List of {path, content, score, title, tags}.
        """
        results: List[Dict[str, Any]] = []
        query_lower = query.lower()
        query_terms = [t for t in re.split(r"\s+", query_lower) if len(t) > 1]

        if not query_terms:
            return results

        for note_file in self.vault_path.rglob("*.md"):
            if "Graxia Tasks" not in str(note_file):
                continue

            try:
                content = note_file.read_text(encoding="utf-8", errors="ignore")
                content_lower = content.lower()

                # Score by term overlap
                score = 0.0
                for term in query_terms:
                    count = content_lower.count(term)
                    if count > 0:
                        # Title matches worth more
                        if term in note_file.stem.lower():
                            score += 5.0
                        score += min(count, 10) * 0.5

                if score > 0:
                    rel_path = str(note_file.relative_to(self.vault_path)).replace("\\", "/")
                    # Extract title from first heading
                    title = note_file.stem
                    for line in content.splitlines():
                        if line.startswith("# "):
                            title = line[2:].strip()
                            break

                    # Extract tags from frontmatter
                    tags = []
                    if content.startswith("---"):
                        end = content.find("---", 3)
                        if end > 0:
                            raw = content[3:end].strip()
                            tags_match = re.search(r"tags:\s*\[([^\]]+)\]", raw)
                            if tags_match:
                                tags = [t.strip().strip('"') for t in tags_match.group(1).split(",")]

                    results.append({
                        "path": rel_path,
                        "title": title,
                        "content": content[:300],
                        "score": round(score, 2),
                        "tags": tags,
                    })

            except Exception as e:
                logger.debug("Skipping %s: %s", note_file, e)

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # List synced tasks
    # ------------------------------------------------------------------

    def list_synced_tasks(self, days: int = 30) -> List[Dict[str, Any]]:
        """List recently synced task notes.

        Args:
            days: Only list tasks from the last N days.

        Returns:
            List of {path, title, date, success, agent_type}.
        """
        if not self.tasks_dir.exists():
            return []

        tasks = []
        cutoff = datetime.now().timestamp() - (days * 86400)

        for note_file in sorted(self.tasks_dir.glob("*.md"), reverse=True):
            try:
                stat = note_file.stat()
                if stat.st_mtime < cutoff:
                    continue

                content = note_file.read_text(encoding="utf-8", errors="ignore")

                # Parse frontmatter
                success = True
                agent_type = ""
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        raw = content[3:end].strip()
                        for line in raw.splitlines():
                            if line.strip().startswith("success:"):
                                val = line.split(":", 1)[1].strip()
                                success = val.lower() == "true"
                            elif line.strip().startswith("agent_type:"):
                                agent_type = line.split(":", 1)[1].strip().strip('"')

                rel_path = str(note_file.relative_to(self.vault_path)).replace("\\", "/")
                tasks.append({
                    "path": rel_path,
                    "title": note_file.stem,
                    "date": note_file.stem[:10],
                    "success": success,
                    "agent_type": agent_type,
                })
            except Exception as e:
                logger.debug("Skipping %s: %s", note_file, e)

        return tasks

    # ------------------------------------------------------------------
    # Bi-directional sync
    # ------------------------------------------------------------------

    def full_sync(self, limit: int = 50) -> Dict[str, Any]:
        """Run full bidirectional sync.

        1. Push all unsynced tasks from SessionMemory → vault
        2. Return summary

        Returns:
            {synced, skipped, errors, total}
        """
        results = self.sync_all_tasks(limit=limit)

        synced = sum(1 for r in results if r.action == "synced")
        skipped = sum(1 for r in results if r.action == "skipped")
        errors = sum(1 for r in results if r.action == "error")

        return {
            "synced": synced,
            "skipped": skipped,
            "errors": errors,
            "total": len(results),
            "details": [
                {"task_id": r.task_id[:8], "action": r.action, "path": r.vault_path}
                for r in results
            ],
        }

    # ------------------------------------------------------------------
    # Generate MOC for tasks
    # ------------------------------------------------------------------

    def generate_tasks_moc(self) -> SyncResult:
        """Generate a Map of Content note linking all synced tasks."""
        tasks = self.list_synced_tasks(days=365)

        lines = [
            "---",
            "tags: [MOC, agent-os, tasks]",
            "---",
            "# Graxia Tasks",
            "",
            "Map of all tasks executed by Agent OS.",
            f"*Auto-generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            f"## Stats: {len(tasks)} tasks total",
            "",
            "- Successful: " + str(sum(1 for t in tasks if t["success"])),
            "- Failed: " + str(sum(1 for t in tasks if not t["success"])),
            "",
            "## Recent Tasks",
            "",
        ]

        # Group by date
        by_date: Dict[str, List[Dict]] = {}
        for t in tasks:
            by_date.setdefault(t["date"], []).append(t)

        for date in sorted(by_date.keys(), reverse=True)[:30]:
            lines.append(f"### {date}")
            for t in by_date[date]:
                status = "PASS" if t["success"] else "FAIL"
                link = t["path"].replace("03-Resources/Graxia Tasks/", "").rstrip(".md")
                lines.append(f"- {status} [[{link}]] ({t['agent_type'] or 'unknown'})")
            lines.append("")

        content = "\n".join(lines)
        moc_path = self.tasks_dir / "Graxia Tasks.md"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        moc_path.write_text(content, encoding="utf-8")

        rel = str(moc_path.relative_to(self.vault_path)).replace("\\", "/")
        return SyncResult(
            success=True,
            vault_path=rel,
            action="synced",
            message=f"MOC generated: {rel}",
            note_count=len(tasks),
        )
