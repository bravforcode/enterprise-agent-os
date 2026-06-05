"""File watcher for vault, code, and config changes.

Polling-based (os.scandir + mtime) — no external deps.
3 targets: vault (.md), code (.py), config (AGENT_RULES.md, .mcp.json)
"""
from __future__ import annotations

import logging
import os
import time
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)


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
        self._running = threading.Event()
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
                            logger.debug("scan_stat_failed path=%s", entry.path)
                elif entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    mtimes.update(self._scan_mtimes(entry.path, ext))
        except OSError:
            logger.debug("scan_dir_failed root=%s", root)
        return mtimes

    def _scan_single_files(self, paths: list[str]) -> dict[str, float]:
        """Scan specific files, return {path: mtime}."""
        mtimes = {}
        for p in paths:
            try:
                mtimes[p] = os.stat(p).st_mtime
            except OSError:
                logger.debug("scan_single_stat_failed path=%s", p)
        return mtimes

    def _categorize(self, path: str) -> str:
        """Determine category of a file path.

        Matches the most specific (longest) prefix first to avoid
        ambiguous matches when paths overlap.
        """
        candidates: list[tuple[int, str]] = []
        if self._vault_path and path.startswith(self._vault_path):
            candidates.append((len(self._vault_path), "vault"))
        if self._code_path and path.startswith(self._code_path):
            candidates.append((len(self._code_path), "code"))
        if candidates:
            candidates.sort(key=lambda c: c[0], reverse=True)
            return candidates[0][1]
        return "config"

    def _poll_loop(self) -> None:
        """Main polling loop with proper debounce."""
        while self._running.is_set():
            try:
                now = time.time()

                # Scan all files
                all_mtimes = {}
                if self._vault_path and self._on_vault_change:
                    all_mtimes.update(self._scan_mtimes(self._vault_path, ext=".md"))
                if self._code_path and self._on_code_change:
                    all_mtimes.update(self._scan_mtimes(self._code_path, ext=".py"))
                if self._config_paths and self._on_config_change:
                    all_mtimes.update(self._scan_single_files(self._config_paths))

                ready: list[str] = []
                with self._lock:
                    # Detect NEW changes
                    for path, mtime in all_mtimes.items():
                        old = self._mtimes.get(path, 0)
                        if mtime > old and path not in self._pending:
                            self._pending[path] = now

                    self._mtimes.update(all_mtimes)

                    # Check pending files for debounce completion (inside lock)
                    for path in list(self._pending):
                        first_seen = self._pending[path]
                        if now - first_seen >= self.DEBOUNCE_WINDOW:
                            ready.append(path)
                            del self._pending[path]

                # Trigger callbacks for ready files
                for path in ready:
                    category = self._categorize(path)
                    callback = {
                        "vault": self._on_vault_change,
                        "code": self._on_code_change,
                        "config": self._on_config_change,
                    }.get(category)
                    if callback:
                        logger.info("file_changed category=%s path=%s", category, path)
                        try:
                            callback([path])
                        except Exception as e:
                            logger.warning("callback_failed category=%s error=%s", category, e)

            except Exception as e:
                logger.warning("poll_error error=%s", e)

            time.sleep(self.POLL_INTERVAL)

    def start(self) -> None:
        """Start the file watcher in a background thread."""
        with self._lock:
            if self._running.is_set():
                return
            self._running.set()
        self._thread = threading.Thread(target=self._poll_loop, daemon=True, name="file-watcher")
        self._thread.start()
        logger.info("file_watcher_started vault=%s code=%s configs=%d",
                     self._vault_path, self._code_path, len(self._config_paths))

    def stop(self) -> None:
        """Stop the file watcher."""
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("file_watcher_stopped")
