"""Auto-system MCP tools — thin wrappers around vault auto-systems core logic."""
from __future__ import annotations
from typing import Any, Dict
from ..shared.helpers import _ok, _err
from ..vault.auto_systems import (
    VaultAutoLinker, VaultAutoTagger, VaultAutoClassifier,
    VaultAutoDuplicateFinder, VaultAutoConsistencyChecker, VaultAutoTaskExtractor,
)


async def vault_run_auto_link(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find orphaned notes and create links (auto-system version)."""
    dry_run = args.get("dry_run", False)
    max_files = int(args.get("max_files", 50))
    try:
        linker = VaultAutoLinker()
        result = linker.fix_orphans(dry_run=dry_run, max_files=max_files)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def vault_run_auto_tag(args: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze content and add tags (auto-system version)."""
    dry_run = args.get("dry_run", False)
    max_files = int(args.get("max_files", 200))
    try:
        tagger = VaultAutoTagger()
        result = tagger.run(dry_run=dry_run, max_files=max_files)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def vault_auto_classify(args: Dict[str, Any]) -> Dict[str, Any]:
    """Classify notes into PARA structure."""
    dry_run = args.get("dry_run", False)
    max_files = int(args.get("max_files", 100))
    try:
        classifier = VaultAutoClassifier()
        result = classifier.classify_batch(dry_run=dry_run, max_files=max_files)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def vault_auto_find_duplicates(args: Dict[str, Any]) -> Dict[str, Any]:
    """Find duplicate and similar notes."""
    dry_run = args.get("dry_run", False)
    try:
        finder = VaultAutoDuplicateFinder()
        result = finder.run(dry_run=dry_run)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def vault_auto_check_consistency(args: Dict[str, Any]) -> Dict[str, Any]:
    """Check vault integrity: broken links, empty files, orphaned images."""
    dry_run = args.get("dry_run", False)
    try:
        checker = VaultAutoConsistencyChecker()
        result = checker.run(dry_run=dry_run)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


async def vault_auto_extract_tasks(args: Dict[str, Any]) -> Dict[str, Any]:
    """Extract TODOs, FIXMEs, and task items from notes."""
    dry_run = args.get("dry_run", False)
    try:
        extractor = VaultAutoTaskExtractor()
        result = extractor.run(dry_run=dry_run)
        return _ok(result)
    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")
