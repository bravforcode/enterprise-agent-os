"""Integration test: FileWatcher + MemoryManager + auto-persist."""
import os
import tempfile
import time
from pathlib import Path

from graxia_tool.control_plane.watcher import FileWatcher
from graxia_tool.control_plane.memory import MemoryManager, MemoryTier


def test_memory_store_recall():
    """Store and recall from MemoryManager."""
    db = os.path.join(tempfile.gettempdir(), "test_integration.db")
    mm = MemoryManager(db_path=db)
    mid = mm.store("test cross-session memory", tier=MemoryTier.LONGTERM, key="test_key")
    results = mm.recall(key="test_key")
    assert len(results) == 1
    assert results[0]["content"] == "test cross-session memory"
    mm.close()
    os.remove(db)


def test_auto_persist():
    """Auto-persist snapshots working → longterm."""
    db = os.path.join(tempfile.gettempdir(), "test_persist.db")
    mm = MemoryManager(db_path=db, working_ttl=1)  # 1 second TTL
    mm.store("working memory", tier=MemoryTier.WORKING, key="wk")
    time.sleep(2)  # Wait for expiry
    count = mm._snapshot_working_to_longterm()
    assert count >= 1
    results = mm.recall(key="wk")
    assert len(results) == 1
    mm.close()
    os.remove(db)


def test_file_watcher_detects_change():
    """FileWatcher detects .md file changes."""
    changes_detected = []

    with tempfile.TemporaryDirectory() as tmpdir:
        # Create initial file
        md_file = Path(tmpdir) / "test.md"
        md_file.write_text("initial content")

        watcher = FileWatcher(
            vault_path=tmpdir,
            on_vault_change=lambda paths: changes_detected.extend(paths),
        )
        watcher.start()
        time.sleep(1)

        # Modify file
        md_file.write_text("updated content")
        time.sleep(3)  # Wait for debounce

        watcher.stop()

    assert len(changes_detected) > 0
    assert any("test.md" in p for p in changes_detected)
