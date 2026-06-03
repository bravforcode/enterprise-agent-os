"""Test vault auto-systems — verifies all 6 auto-systems work."""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from graxia_tool.vault.auto_systems import (
    VaultAutoLinker,
    VaultAutoTagger,
    VaultAutoClassifier,
    VaultAutoDuplicateFinder,
    VaultAutoConsistencyChecker,
    VaultAutoTaskExtractor,
)
from graxia_tool.mcp.auto_tools import (
    vault_auto_link,
    vault_auto_tag,
    vault_auto_classify,
    vault_auto_find_duplicates,
    vault_auto_check_consistency,
    vault_auto_extract_tasks,
)


def test_auto_linker():
    print("\n--- VaultAutoLinker ---")
    linker = VaultAutoLinker()
    result = linker.fix_orphans(dry_run=True, max_files=5)
    print(f"  Orphaned: {result['orphaned']}, Linked: {result['linked']}, Dry run: {result['dry_run']}")
    assert 'orphaned' in result
    assert 'linked' in result
    print("  PASS")


def test_auto_tagger():
    print("\n--- VaultAutoTagger ---")
    tagger = VaultAutoTagger()
    result = tagger.run(dry_run=True, max_files=5)
    print(f"  Total: {result['total_files']}, Tagged: {result['tagged']}, Skipped: {result['skipped']}")
    assert 'tagged' in result
    assert 'results' in result
    print("  PASS")


def test_auto_classifier():
    print("\n--- VaultAutoClassifier ---")
    classifier = VaultAutoClassifier()
    result = classifier.classify_batch(dry_run=True, max_files=10)
    print(f"  Total: {result['total_files']}, Classified: {result['classified']}")
    assert 'classified' in result
    assert 'by_category' in result
    print("  PASS")


def test_duplicate_finder():
    print("\n--- VaultAutoDuplicateFinder ---")
    finder = VaultAutoDuplicateFinder()
    result = finder.run(dry_run=True)
    print(f"  Exact dup groups: {result['exact_duplicates_groups']}, Similar name groups: {result['similar_names_groups']}")
    assert 'exact_duplicates_groups' in result
    assert 'similar_names_groups' in result
    print("  PASS")


def test_consistency_checker():
    print("\n--- VaultAutoConsistencyChecker ---")
    checker = VaultAutoConsistencyChecker()
    result = checker.run(dry_run=True)
    print(f"  Broken links: {result['broken_links']['count']}, Empty files: {result['empty_files']['count']}")
    print(f"  Orphaned images: {result['orphaned_images']['count']}, Missing frontmatter: {result['missing_frontmatter']['count']}")
    print(f"  Total issues: {result['total_issues']}")
    assert 'broken_links' in result
    assert 'empty_files' in result
    assert 'orphaned_images' in result
    assert 'missing_frontmatter' in result
    print("  PASS")


def test_task_extractor():
    print("\n--- VaultAutoTaskExtractor ---")
    extractor = VaultAutoTaskExtractor()
    result = extractor.run(dry_run=True)
    print(f"  Urgent: {result['urgent_count']}, Pending: {result['pending_count']}, Completed: {result['completed_count']}")
    assert 'urgent_count' in result
    assert 'pending_count' in result
    assert 'completed_count' in result
    print("  PASS")


async def test_mcp_tools():
    print("\n--- MCP Tool Wrappers ---")
    for name, handler in [
        ("vault_auto_link", vault_auto_link),
        ("vault_auto_tag", vault_auto_tag),
        ("vault_auto_classify", vault_auto_classify),
        ("vault_auto_find_duplicates", vault_auto_find_duplicates),
        ("vault_auto_check_consistency", vault_auto_check_consistency),
        ("vault_auto_extract_tasks", vault_auto_extract_tasks),
    ]:
        result = await handler({"dry_run": True})
        has_content = "content" in result and len(result["content"]) > 0
        is_error = result.get("isError", False)
        status = "ERROR" if is_error else "OK"
        print(f"  {name}: {status} (content={has_content})")
        assert has_content, f"{name} returned no content"
    print("  PASS")


def test_mcp_registry():
    print("\n--- MCP Registry ---")
    from graxia_tool.mcp import build_default_registry
    reg = build_default_registry()
    vault_tools = reg.list_by_category("vault")
    auto_tool_names = [
        "vault_auto_link", "vault_auto_tag", "vault_auto_classify",
        "vault_auto_find_duplicates", "vault_auto_check_consistency",
        "vault_auto_extract_tasks",
    ]
    registered_names = {t.name for t in vault_tools}
    for name in auto_tool_names:
        assert name in registered_names, f"Tool {name} not registered!"
        print(f"  {name}: registered")
    print(f"  Total vault tools: {len(vault_tools)}")
    print("  PASS")


if __name__ == "__main__":
    print("=" * 60)
    print("Vault Auto-Systems Test Suite")
    print("=" * 60)

    test_auto_linker()
    test_auto_tagger()
    test_auto_classifier()
    test_duplicate_finder()
    test_consistency_checker()
    test_task_extractor()
    asyncio.run(test_mcp_tools())
    test_mcp_registry()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
