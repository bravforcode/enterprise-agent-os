"""File watcher for vault, code, and config changes.

Polling-based (os.scandir + mtime) — no external deps.
3 targets: vault (.md), code (.py), config (AGENT_RULES.md, .mcp.json)
"""
from __future__ import annotations

import os
import time
import threading
from pathlib import Path
from typing import Any, Callable, Optional

logger = __import__("logging").getLogger(__name__)


class FileWatcher:
    """Polling-based file watcher with debounce.

    Usage:
        watcher = FileWatcher(
            vault_path="/path/to/vault",
            code_path="/path/to/src",
            config_paths=["/path/to/AGENT_RULES.md"],
            on_vault_change=lambda paths: reindex(paths),
            on_code_change=lambda paths: invalidate(paths),
            on_config_change=lambda paths: reload(paths),
        )
        watcher.start()
        # ... later ...
        watcher.stop()
    """

    POLL_INTERVAL = 0.5  # seconds
    DEBOUNCE_WINDOW = 2.0  # seconds

    def __init__(
        self,
        vault_path: Optional[str] = None,
        code_path: Optional[str] = None,
        config_paths: Optional[list[str]] = None,
        on_vault_change: Optional[Callable[[list[str]], None]] = None,
        on_code_change: Optional[Callable[[list[str]], None]] = None,
        on_config_change: Optional[Callable[[list[str]], None]] = None,
    ) -> None:
        self._vault_path = vault_path
        self._code_path = code_path
        self._config_paths = config_paths or []
        self._on_vault_change = on_vault_change
        self._on_code_change = on_code_change
        self._on_config_change = on_config_change

        self._mtimes: dict[str, float] = {}
        self._pending: dict[str, float] = {}  # file -> first change time
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _scan_mtimes(self, root: str, ext: Optional[str] = None) -> dict[str, float]:
        """Scan directory tree, return {path: mtime}."""
        mtimes = {}
        try:
            for entry in os.scandir(root):
                if entry.is_file(follow_symlinks=False):
                    if ext is None or entry.name.endswith(ext):
                        try:
                            mtimes[entry.path] = entry.stat().st_mtime
                        except OSError:
                            pass
                elif entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    mtimes.update(self._scan_mtimes(entry.path, ext))
        except OSError:
            pass
        return mtimes

    def _scan_single_files(self, paths: list[str]) -> dict[str, float]:
        """Scan specific files, return {path: mtime}."""
        mtimes = {}
        for p in paths:
            try:
                mtimes[p] = os.stat(p).st_mtime
            except OSError:
                pass
        return mtimes

    def _detect_changes(self) -> dict[str, list[str]]:
        """Detect changed files since last scan. Returns {category: [paths]}."""
        changes: dict[str, list[str]] = {
            "vault": [],
            "code": [],
            "config": [],
        }

        with self._lock:
            # Vault changes
            if self._vault_path and self._on_vault_change:
                new_mtimes = self._scan_mtimes(self._vault_path, ext=".md")
                for path, mtime in new_mtimes.items():
                    old = self._mtimes.get(path, 0)
                    if mtime > old:
                        changes["vault"].append(path)
                self._mtimes.update(new_mtimes)

            # Code changes
            if self._code_path and self._on_code_change:
                new_mtimes = self._scan_mtimes(self._code_path, ext=".py")
                for path, mtime in new_mtimes.items():
                    old = self._mtimes.get(path, 0)
                    if mtime > old:
                        changes["code"].append(path)
                self._mtimes.update(new_mtimes)

            # Config changes
            if self._config_paths and self._on_config_change:
                new_mtimes = self._scan_single_files(self._config_paths)
                for path, mtime in new_mtimes.items():
                    old = self._mtimes.get(path, 0)
                    if mtime > old:
                        changes["config"].append(path)
                self._mtimes.update(new_mtimes)

        return changes

    def _poll_loop(self) -> None:
        """Main polling loop."""
        while self._running:
            try:
                changes = self._detect_changes()
                now = time.time()

                for category, paths in changes.items():
                    if not paths:
                        continue
                    for path in paths:
                        first_seen = self._pending.get(path, now)
                        if now - first_seen >= self.DEBOUNCE_WINDOW:
                            # Debounce passed, trigger callback
                            self._pending.pop(path, None)
                            callback = {
                                "vault": self._on_vault_change,
                                "code": self._on_code_change,
                                "config": self._on_config_change,
                            }.get(category)
                            if callback:
                                logger.info("file_changed category=%s path=%s", category, path)
                                try:
                                    callback(paths)
                                except Exception as e:
                                    logger.warning("callback_failed category=%s error=%s", category, e)
                        else:
                            # Still in debounce window
                            self._pending[path] = first_seen

            except Exception as e:
                logger.warning("poll_error error=%s", e)

            time.sleep(self.POLL_INTERVAL)

    def start(self) -> None:
        """Start the file watcher in a background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="file-watcher")
        self._thread.start()
        logger.info("file_watcher_started vault=%s code=%s configs=%d",
                     self._vault_path, self._code_path, len(self._config_paths))

    def stop(self) -> None:
        """Stop the file watcher."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("file_watcher_stopped")
