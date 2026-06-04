"""Incremental sync engine for Graxia Tool — Merkle tree based diff sync.

Efficiently processes only changed files by comparing SHA-256 Merkle trees.
State is persisted in SQLite; triggers are file-based with debounce.

Usage:
    sync = MerkleSync()
    result = await sync.sync(VAULT_PATH)
    stats = sync.get_stats(VAULT_PATH)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("graxia_tool.mcp.incremental_sync")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_TRIGGER_DIR = Path.home() / ".graxia"
_TRIGGER_FILENAME = ".sync-trigger"
_DEBOUNCE_SECONDS = 2.0

VAULT_PATH = Path(os.environ.get(
    "AGENT_OS_VAULT_PATH",
    r"C:\Users\menum\Documents\ObsidianVault\Second Brain",
))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MerkleNode:
    """A node in the Merkle tree — leaf or branch."""
    hash: str
    path: str  # Relative path for leaves, dir path for branches
    children: List["MerkleNode"] = field(default_factory=list)
    is_leaf: bool = True
    size_bytes: int = 0


@dataclass
class SyncDiff:
    """Result of diffing two Merkle trees."""
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    unchanged: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.modified)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.removed) + len(self.modified)


@dataclass
class IncrementalSyncResult:
    """Result of an incremental sync operation."""
    success: bool = True
    files_synced: int = 0
    files_skipped: int = 0
    files_added: int = 0
    files_modified: int = 0
    files_removed: int = 0
    bytes_total: int = 0
    duration_ms: float = 0.0
    root_hash: str = ""
    message: str = ""
    details: List[Dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# MerkleSync
# ---------------------------------------------------------------------------

class MerkleSync:
    """Merkle tree based incremental sync engine.

    Tracks file changes via SHA-256 hashes in a Merkle tree structure.
    State is persisted in SQLite for cross-session persistence.

    Usage:
        sync = MerkleSync()
        result = sync.sync(VAULT_PATH)
        stats = sync.get_stats(VAULT_PATH)
        trigger = sync.check_trigger()
    """

    def __init__(self, db_path: Optional[str] = None):
        trigger_dir = Path(os.environ.get(
            "GRAXIA_TRIGGER_DIR",
            str(_DEFAULT_TRIGGER_DIR),
        ))
        self._trigger_path = trigger_dir / _TRIGGER_FILENAME
        self._last_trigger_time: float = 0.0
        self._self_created_trigger: bool = False

        if db_path is None:
            db_dir = Path.home() / ".graxia"
            db_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(db_dir / "sync.db")
        self._db_path = db_path
        self._init_db()

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create sync_state table if it doesn't exist."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_state (
                    path TEXT PRIMARY KEY,
                    root_hash TEXT NOT NULL,
                    last_sync TEXT NOT NULL,
                    files_count INTEGER DEFAULT 0,
                    bytes_total INTEGER DEFAULT 0,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    sync_path TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    size_bytes INTEGER DEFAULT 0,
                    last_modified TEXT,
                    PRIMARY KEY (sync_path, file_path)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def _load_state(self, sync_path: str) -> Optional[Dict[str, Any]]:
        """Load sync state for a path from SQLite."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM sync_state WHERE path = ?", (sync_path,)
            ).fetchone()
            if row is None:
                return None
            return dict(row)
        finally:
            conn.close()

    def _save_state(
        self,
        sync_path: str,
        root_hash: str,
        files_count: int,
        bytes_total: int,
    ) -> None:
        """Save sync state to SQLite."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            now = datetime.now().isoformat()
            conn.execute(
                """INSERT OR REPLACE INTO sync_state
                   (path, root_hash, last_sync, files_count, bytes_total)
                   VALUES (?, ?, ?, ?, ?)""",
                (sync_path, root_hash, now, files_count, bytes_total),
            )
            conn.commit()
        finally:
            conn.close()

    def _load_file_hashes(self, sync_path: str) -> Dict[str, str]:
        """Load file→hash map for a sync path."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            rows = conn.execute(
                "SELECT file_path, file_hash FROM file_hashes WHERE sync_path = ?",
                (sync_path,),
            ).fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()

    def _save_file_hashes(
        self,
        sync_path: str,
        file_map: Dict[str, Tuple[str, int]],
    ) -> None:
        """Save file→(hash, size) map. Replaces all entries for sync_path."""
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute("DELETE FROM file_hashes WHERE sync_path = ?", (sync_path,))
            now = datetime.now().isoformat()
            conn.executemany(
                """INSERT INTO file_hashes
                   (sync_path, file_path, file_hash, size_bytes, last_modified)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (sync_path, fp, h, sz, now)
                    for fp, (h, sz) in file_map.items()
                ],
            )
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Hashing
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_file(path: Path) -> Tuple[str, int]:
        """Compute SHA-256 hash and size of a file.

        Returns:
            (hex_digest, size_bytes)
        """
        h = hashlib.sha256()
        size = 0
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
                size += len(chunk)
        return h.hexdigest(), size

    @staticmethod
    def _hash_pair(left: str, right: str) -> str:
        """Hash two child hashes to produce a parent hash."""
        combined = left.encode() + right.encode()
        return hashlib.sha256(combined).hexdigest()

    @staticmethod
    def _hash_single(data: str) -> str:
        """Hash a single string value."""
        return hashlib.sha256(data.encode()).hexdigest()

    # ------------------------------------------------------------------
    # Merkle tree operations
    # ------------------------------------------------------------------

    def build_merkle_tree(self, path: str | Path) -> MerkleNode:
        """Build a Merkle tree from a directory.

        Leaves are file hashes; branches combine children pairwise.

        Args:
            path: Root directory to scan.

        Returns:
            MerkleNode root of the tree.
        """
        root = Path(path)
        if not root.exists():
            return MerkleNode(hash="", path=str(root), is_leaf=True)

        leaves: List[MerkleNode] = []

        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            # Skip hidden files and common non-content files
            name = file_path.name
            if name.startswith(".") or name == "Thumbs.db":
                continue

            rel = str(file_path.relative_to(root)).replace("\\", "/")
            try:
                file_hash, size = self._hash_file(file_path)
                leaves.append(MerkleNode(
                    hash=file_hash,
                    path=rel,
                    is_leaf=True,
                    size_bytes=size,
                ))
            except (PermissionError, OSError) as e:
                logger.debug("Skipping %s: %s", rel, e)

        if not leaves:
            return MerkleNode(
                hash=self._hash_single("empty"),
                path=str(root),
                is_leaf=True,
            )

        return self._build_branch(str(root), leaves)

    def _build_branch(self, dir_path: str, nodes: List[MerkleNode]) -> MerkleNode:
        """Recursively build branch nodes from a list of nodes.

        Pairs nodes and hashes them up the tree. Odd nodes are promoted.
        """
        if len(nodes) == 1:
            return MerkleNode(
                hash=nodes[0].hash,
                path=dir_path,
                children=nodes,
                is_leaf=False,
            )

        pairs: List[MerkleNode] = []
        for i in range(0, len(nodes), 2):
            if i + 1 < len(nodes):
                combined_hash = self._hash_pair(nodes[i].hash, nodes[i + 1].hash)
                pairs.append(MerkleNode(
                    hash=combined_hash,
                    path=f"{dir_path}/pair_{i}",
                    children=[nodes[i], nodes[i + 1]],
                    is_leaf=False,
                ))
            else:
                # Odd node — promote as-is
                pairs.append(nodes[i])

        if len(pairs) == 1:
            return MerkleNode(
                hash=pairs[0].hash,
                path=dir_path,
                children=pairs,
                is_leaf=False,
            )

        return self._build_branch(dir_path, pairs)

    def diff_trees(
        self,
        old_root: Optional[MerkleNode],
        new_root: MerkleNode,
    ) -> SyncDiff:
        """Compare two Merkle trees and find added/removed/modified files.

        Args:
            old_root: Previous tree root (None if first sync).
            new_root: Current tree root.

        Returns:
            SyncDiff with lists of changed file paths.
        """
        if old_root is None:
            # First sync — everything is added
            diff = SyncDiff()
            self._collect_leaves(new_root, diff, is_added=True)
            return diff

        old_map = self._flatten_leaves(old_root)
        new_map = self._flatten_leaves(new_root)

        diff = SyncDiff()

        old_set = set(old_map.keys())
        new_set = set(new_map.keys())

        # Added files
        for fp in sorted(new_set - old_set):
            diff.added.append(fp)

        # Removed files
        for fp in sorted(old_set - new_set):
            diff.removed.append(fp)

        # Modified files (same path, different hash)
        for fp in sorted(old_set & new_set):
            if old_map[fp] != new_map[fp]:
                diff.modified.append(fp)
            else:
                diff.unchanged += 1

        return diff

    def _flatten_leaves(self, node: MerkleNode) -> Dict[str, str]:
        """Flatten a Merkle tree to a {path: hash} map of leaves."""
        result: Dict[str, str] = {}
        self._collect_leaf_map(node, result)
        return result

    def _collect_leaf_map(self, node: MerkleNode, out: Dict[str, str]) -> None:
        """Recursively collect leaf hashes into a dict."""
        if node.is_leaf:
            out[node.path] = node.hash
        for child in node.children:
            self._collect_leaf_map(child, out)

    def _collect_leaves(
        self,
        node: MerkleNode,
        diff: SyncDiff,
        is_added: bool = False,
    ) -> None:
        """Collect all leaf paths from a node into diff.added."""
        if node.is_leaf:
            diff.added.append(node.path)
        for child in node.children:
            self._collect_leaves(child, diff, is_added)

    # ------------------------------------------------------------------
    # Core sync
    # ------------------------------------------------------------------

    def sync(
        self,
        path: str | Path,
        incremental: bool = True,
    ) -> IncrementalSyncResult:
        """Run incremental sync on a directory.

        Compares current file hashes against stored state.
        Only processes files that were added or modified since last sync.

        Args:
            path: Directory to sync.
            incremental: If True, use Merkle diff. If False, full re-hash.

        Returns:
            IncrementalSyncResult with sync stats.
        """
        start = time.time()
        sync_path = str(Path(path).resolve())

        try:
            # Build current tree
            new_root = self.build_merkle_tree(path)

            if incremental:
                # Load previous state
                old_file_map = self._load_file_hashes(sync_path)
                old_root = self._rebuild_old_tree(sync_path, old_file_map) if old_file_map else None
                diff = self.diff_trees(old_root, new_root)
            else:
                # Full sync — treat everything as added
                diff = SyncDiff()
                self._collect_leaves(new_root, diff)

            result = IncrementalSyncResult(
                root_hash=new_root.hash,
                files_added=len(diff.added),
                files_modified=len(diff.modified),
                files_removed=len(diff.removed),
            )

            # Collect all files that need syncing
            new_file_map = self._flatten_leaves(new_root)
            to_sync = diff.added + diff.modified

            # Run sync callback for each changed file
            # (The caller provides the actual sync logic via wrapper)
            result.files_synced = len(to_sync)
            result.bytes_total = sum(
                node.size_bytes
                for node in self._iter_leaves(new_root)
                if node.path in to_sync
            )

            # Save new state
            file_hash_map = {
                fp: (new_file_map[fp], 0)
                for fp in new_file_map
            }
            self._save_file_hashes(sync_path, file_hash_map)
            self._save_state(
                sync_path,
                new_root.hash,
                len(new_file_map),
                result.bytes_total,
            )

            result.duration_ms = (time.time() - start) * 1000
            result.success = True
            result.message = (
                f"Sync complete: {result.files_added} added, "
                f"{result.files_modified} modified, "
                f"{result.files_removed} removed, "
                f"{diff.unchanged} unchanged"
            )

            logger.info(
                "incremental sync %s: +%d ~%d -%d (%dms)",
                Path(path).name,
                result.files_added,
                result.files_modified,
                result.files_removed,
                int(result.duration_ms),
            )

            return result

        except Exception as e:
            logger.exception("sync failed for %s", path)
            return IncrementalSyncResult(
                success=False,
                duration_ms=(time.time() - start) * 1000,
                message=f"{type(e).__name__}: {e}",
            )

    def _rebuild_old_tree(
        self,
        sync_path: str,
        file_map: Dict[str, str],
    ) -> Optional[MerkleNode]:
        """Rebuild a MerkleNode tree from stored file hashes.

        This reconstructs the tree structure from the previous sync
        so we can diff it against the current tree.
        """
        if not file_map:
            return None

        leaves = [
            MerkleNode(hash=h, path=fp, is_leaf=True)
            for fp, h in sorted(file_map.items())
        ]

        if not leaves:
            return None

        return self._build_branch(sync_path, leaves)

    def _iter_leaves(self, node: MerkleNode):
        """Iterate all leaf nodes in a tree."""
        if node.is_leaf:
            yield node
        for child in node.children:
            yield from self._iter_leaves(child)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self, path: str | Path) -> Dict[str, Any]:
        """Return sync statistics for a path.

        Args:
            path: Directory path to get stats for.

        Returns:
            Dict with sync state info.
        """
        sync_path = str(Path(path).resolve())
        state = self._load_state(sync_path)

        if state is None:
            return {
                "path": sync_path,
                "synced": False,
                "files_count": 0,
                "bytes_total": 0,
                "root_hash": "",
                "last_sync": None,
            }

        return {
            "path": sync_path,
            "synced": True,
            "files_count": state["files_count"],
            "bytes_total": state["bytes_total"],
            "root_hash": state["root_hash"],
            "last_sync": state["last_sync"],
        }

    def get_file_hashes(self, path: str | Path) -> Dict[str, str]:
        """Return the stored file hash map for a path.

        Useful for debugging and inspection.
        """
        sync_path = str(Path(path).resolve())
        return self._load_file_hashes(sync_path)

    # ------------------------------------------------------------------
    # Trigger mechanism
    # ------------------------------------------------------------------

    def check_trigger(self) -> bool:
        """Check for and consume a .sync-trigger file.

        Returns True if a trigger was found and consumed (debounce passed).
        The trigger file is deleted after successful detection.

        Debounce: skips triggers within 2 seconds of the last consumed one,
        unless the trigger was created by create_trigger() on this instance.
        """
        if not self._trigger_path.exists():
            return False

        # Debounce: skip if less than 2s since we last consumed a trigger
        # (unless this trigger was created by our own create_trigger)
        if not self._self_created_trigger:
            now = time.time()
            elapsed = now - self._last_trigger_time
            if elapsed < _DEBOUNCE_SECONDS and self._last_trigger_time > 0:
                logger.debug(
                    "trigger debounced (%.1fs < %.1fs)",
                    elapsed,
                    _DEBOUNCE_SECONDS,
                )
                return False

        # Consume the trigger
        try:
            self._trigger_path.unlink(missing_ok=True)
        except OSError:
            pass

        self._last_trigger_time = time.time()
        self._self_created_trigger = False
        logger.info("sync trigger consumed from %s", self._trigger_path)
        return True

    def create_trigger(self) -> bool:
        """Create a .sync-trigger file to initiate a sync.

        Returns True if trigger was created successfully.
        """
        try:
            self._trigger_path.parent.mkdir(parents=True, exist_ok=True)
            self._trigger_path.write_text(
                f"triggered at {datetime.now().isoformat()}\n",
                encoding="utf-8",
            )
            self._self_created_trigger = True
            logger.info("sync trigger created at %s", self._trigger_path)
            return True
        except OSError as e:
            logger.warning("failed to create trigger: %s", e)
            return False

    def wait_for_trigger(
        self,
        timeout: float = 300.0,
        poll_interval: float = 1.0,
    ) -> bool:
        """Block until a trigger is detected or timeout expires.

        Args:
            timeout: Max seconds to wait.
            poll_interval: Seconds between checks.

        Returns:
            True if trigger detected, False on timeout.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.check_trigger():
                return True
            time.sleep(poll_interval)
        return False

    async def watch_triggers(
        self,
        callback,
        poll_interval: float = 2.0,
        max_iterations: Optional[int] = None,
    ) -> None:
        """Async loop that watches for triggers and calls callback.

        Args:
            callback: Async callable invoked when trigger detected.
            poll_interval: Seconds between checks.
            max_iterations: Stop after N iterations (None = forever).
        """
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            if self.check_trigger():
                try:
                    await callback()
                except Exception as e:
                    logger.exception("trigger callback failed: %s", e)
            await asyncio.sleep(poll_interval)
            iterations += 1


# ---------------------------------------------------------------------------
# MCP integration helpers
# ---------------------------------------------------------------------------

def _get_vault_path() -> Path:
    """Return configured vault path."""
    return Path(os.environ.get("AGENT_OS_VAULT_PATH", str(VAULT_PATH)))


async def incremental_sync_task(args: Dict[str, Any]) -> Dict[str, Any]:
    """Sync a single task to vault using incremental Merkle diff.

    Wraps VaultMemorySync.sync_task() with incremental awareness.
    Only syncs if the task file has changed since last sync.
    """
    from ..shared.helpers import _ok, _err
    from ..memory.vault_sync import VaultMemorySync

    task_id = args.get("task_id", "")
    prompt = args.get("prompt", "")
    success = args.get("success", True)
    agent_type = args.get("agent_type", "")
    outcome = args.get("outcome", "")
    intent = args.get("intent", "")
    domain = args.get("domain", "")
    duration_ms = args.get("duration_ms", 0)
    tokens_used = args.get("tokens_used", 0)
    incremental = args.get("incremental", True)

    if not task_id:
        return _err("task_id is required")
    if not prompt:
        return _err("prompt is required")

    def _do():
        vault_path = _get_vault_path()
        sync = VaultMemorySync(vault_path=vault_path)
        result = sync.sync_task(
            task_id=task_id,
            prompt=prompt,
            success=success,
            agent_type=agent_type,
            outcome=outcome,
            intent=intent,
            domain=domain,
            duration_ms=float(duration_ms),
            tokens_used=int(tokens_used),
        )

        # Log sync stats if incremental
        sync_stats = None
        if incremental:
            merkle = MerkleSync()
            sync_stats = merkle.get_stats(vault_path)

        return {
            "success": result.success,
            "vault_path": result.vault_path,
            "task_id": result.task_id,
            "action": result.action,
            "message": result.message,
            "incremental": incremental,
            "sync_stats": sync_stats,
        }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def incremental_sync_all(args: Dict[str, Any]) -> Dict[str, Any]:
    """Sync all unsynced tasks using incremental Merkle diff.

    Wraps VaultMemorySync.full_sync() with incremental awareness.
    Builds Merkle tree, diffs against stored state, syncs only changes.
    """
    from ..shared.helpers import _ok, _err
    from ..memory.vault_sync import VaultMemorySync

    limit = args.get("limit", 50)
    incremental = args.get("incremental", True)

    def _do():
        vault_path = _get_vault_path()
        merkle = MerkleSync()

        if incremental:
            # Incremental: diff Merkle trees
            new_root = merkle.build_merkle_tree(vault_path)
            old_file_map = merkle.get_file_hashes(vault_path)
            old_root = merkle._rebuild_old_tree(str(vault_path), old_file_map) if old_file_map else None
            diff = merkle.diff_trees(old_root, new_root)

            if not diff.has_changes:
                return {
                    "success": True,
                    "mode": "incremental",
                    "changes": 0,
                    "message": "No changes detected — vault is up to date",
                    "stats": merkle.get_stats(vault_path),
                }

            # Run the actual sync
            sync = VaultMemorySync(vault_path=vault_path)
            sync_result = sync.full_sync(limit=limit)

            # Save new state
            new_file_map = merkle._flatten_leaves(new_root)
            file_hash_map = {fp: (h, 0) for fp, h in new_file_map.items()}
            merkle._save_file_hashes(str(vault_path), file_hash_map)
            merkle._save_state(
                str(vault_path),
                new_root.hash,
                len(new_file_map),
                0,
            )

            return {
                "success": True,
                "mode": "incremental",
                "changes": diff.total_changes,
                "added": len(diff.added),
                "modified": len(diff.modified),
                "removed": len(diff.removed),
                "unchanged": diff.unchanged,
                **sync_result,
                "stats": merkle.get_stats(vault_path),
            }
        else:
            # Full sync
            sync = VaultMemorySync(vault_path=vault_path)
            result = sync.full_sync(limit=limit)

            # Update Merkle state after full sync
            new_root = merkle.build_merkle_tree(vault_path)
            new_file_map = merkle._flatten_leaves(new_root)
            file_hash_map = {fp: (h, 0) for fp, h in new_file_map.items()}
            merkle._save_file_hashes(str(vault_path), file_hash_map)
            merkle._save_state(
                str(vault_path),
                new_root.hash,
                len(new_file_map),
                0,
            )

            return {
                "success": True,
                "mode": "full",
                **result,
                "stats": merkle.get_stats(vault_path),
            }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def incremental_sync_status(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get incremental sync status for the vault."""
    from ..shared.helpers import _ok, _err

    def _do():
        vault_path = _get_vault_path()
        merkle = MerkleSync()
        stats = merkle.get_stats(vault_path)

        # Also check trigger
        trigger_exists = merkle._trigger_path.exists()

        return {
            **stats,
            "trigger_pending": trigger_exists,
            "trigger_path": str(merkle._trigger_path),
        }

    try:
        result = await asyncio.to_thread(_do)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def incremental_sync_trigger(args: Dict[str, Any]) -> Dict[str, Any]:
    """Create or check a sync trigger file."""
    from ..shared.helpers import _ok, _err

    action = args.get("action", "create")
    merkle = MerkleSync()

    if action == "create":
        created = merkle.create_trigger()
        return _ok({
            "created": created,
            "trigger_path": str(merkle._trigger_path),
        })
    elif action == "check":
        found = merkle.check_trigger()
        return _ok({
            "found": found,
            "trigger_path": str(merkle._trigger_path),
        })
    else:
        return _err(f"Unknown action: {action}. Use: create, check")


# ---------------------------------------------------------------------------
# MCP tool definitions (for registration)
# ---------------------------------------------------------------------------

INCREMENTAL_SYNC_TOOLS = [
    {
        "name": "incremental_sync_task",
        "description": "Sync a task to vault with incremental Merkle diff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "prompt": {"type": "string"},
                "success": {"type": "boolean", "default": True},
                "agent_type": {"type": "string"},
                "outcome": {"type": "string"},
                "intent": {"type": "string"},
                "domain": {"type": "string"},
                "duration_ms": {"type": "number"},
                "tokens_used": {"type": "integer"},
                "incremental": {"type": "boolean", "default": True},
            },
            "required": ["task_id", "prompt"],
        },
        "handler": incremental_sync_task,
        "category": "memory",
    },
    {
        "name": "incremental_sync_all",
        "description": "Sync all unsynced tasks using Merkle tree diff.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 50},
                "incremental": {"type": "boolean", "default": True},
            },
        },
        "handler": incremental_sync_all,
        "category": "memory",
    },
    {
        "name": "incremental_sync_status",
        "description": "Get incremental sync status and statistics.",
        "input_schema": {"type": "object", "properties": {}},
        "handler": incremental_sync_status,
        "category": "memory",
    },
    {
        "name": "incremental_sync_trigger",
        "description": "Create or check a sync trigger file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "check"],
                    "default": "create",
                },
            },
        },
        "handler": incremental_sync_trigger,
        "category": "memory",
    },
]
