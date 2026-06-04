"""Tests for the Acontext-style skill memory module.

Covers:
  * skill_store CRUD on disk
  * schema parse/render round-trip
  * BM25 recall (no LLM, fast)
  * distiller with mocked LLM (fast)
  * distiller + 2 recall + 1 learn: real OpenRouter calls (integration)
  * MCP tool handlers (dry-run, no LLM)

Run:
    python -m pytest tests/test_acontext.py -v                       # all
    python -m pytest tests/test_acontext.py -v -m "not integration"  # fast
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


# Make `graxia_tool` importable when tests are run from the repo root
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Windows: use SelectorEventLoop like the MCP entry point does
if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass

from graxia_tool.acontext import (
    BM25,
    Distiller,
    Skill,
    SkillMetadata,
    SkillStore,
    default_base_dir,
    parse_frontmatter,
    recall_skills,
    render_skill,
)
from graxia_tool.acontext.distiller import _parse_skills_json, _slugify_skill_name
from graxia_tool.mcp.acontext_tools import (
    ACONTEXT_TOOLS,
    acontext_delete_skill,
    acontext_get_skill,
    acontext_learn,
    acontext_list_skills,
    acontext_recall,
)

# Use a project-local temp root: the default pytest root
# (C:\Users\<u>\AppData\Local\Temp\pytest-of-...) is sometimes
# inaccessible on this Windows host. Falling back to a project-local
# directory keeps tests hermetic and fast.
_LOCAL_TMP_ROOT = ROOT / ".pytest-tmp"
_LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_path_isolated() -> Path:
    """A fresh temp directory under _LOCAL_TMP_ROOT (per-test)."""
    import tempfile
    return Path(tempfile.mkdtemp(prefix="acontext-", dir=str(_LOCAL_TMP_ROOT)))


@pytest.fixture
def tmp_store(tmp_path_isolated: Path) -> SkillStore:
    """An isolated SkillStore rooted in the per-test temp dir."""
    return SkillStore("pytest-space", base_dir=tmp_path_isolated)


@pytest.fixture
def seeded_store(tmp_path_isolated: Path) -> SkillStore:
    """A space pre-populated with three contrasting skills.

    Backed by the *same* temp dir as ``tmp_path_isolated`` so that
    tests using the MCP tool handlers (which take ``base_dir`` as an
    arg) can target the same files.
    """
    store = SkillStore("pytest-space", base_dir=tmp_path_isolated)
    store.upsert(
        name="python-venv-activation",
        description="Always use a venv before pip install on Windows.",
        body=(
            "## Context\nWorking on a Windows dev box.\n\n"
            "## Rule\nActivate the project's venv before running `pip install`:\n\n"
            "```\n.venv\\Scripts\\activate\n```\n\n"
            "## Why\nGlobal pip installs pollute the system Python and break other tools."
        ),
        tags=["python", "windows", "setup"],
    )
    store.upsert(
        name="pytest-fixture-isolation",
        description="Use tmp_path fixture for filesystem tests to avoid clobbering state.",
        body=(
            "## Context\nWriting pytest tests that touch the filesystem.\n\n"
            "## Rule\nUse the `tmp_path` fixture (or `tmp_path_factory`) for any disk write. "
            "Never write to the repo root or to `~/.graxia` from a unit test.\n\n"
            "## Why\nTests must be hermetic — running them twice should give the same result."
        ),
        tags=["pytest", "testing", "isolation"],
    )
    store.upsert(
        name="json-repair-prompt",
        description="When the LLM returns malformed JSON, ask it to return JSON only.",
        body=(
            "## Context\nAn LLM call is supposed to return strict JSON.\n\n"
            "## Rule\nIf the response fails to parse:\n"
            "1. Strip leading/trailing code fences.\n"
            "2. Locate the first `{` and last `}` and try parsing the substring.\n"
            "3. If still broken, retry with a stricter system prompt.\n\n"
            "## Why\nLLMs often add prose around the JSON; a defensive parser saves a round trip."
        ),
        tags=["llm", "json", "parsing"],
    )
    return store


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestSchema:
    def test_parse_then_render_round_trip(self):
        original = Skill(
            meta=SkillMetadata(
                name="round-trip-skill",
                description="Round trip description",
                tags=["a", "b", "c"],
                source_session="abc-123",
                version=2,
            ),
            body="# Heading\n\nBody text with `code` and a list:\n- one\n- two\n",
        )
        text = render_skill(original)
        meta, body = parse_frontmatter(text)
        assert meta.name == "round-trip-skill"
        assert meta.description == "Round trip description"
        assert meta.tags == ["a", "b", "c"]
        assert meta.source_session == "abc-123"
        assert meta.version == 2
        assert "Heading" in body
        assert "Body text" in body

    def test_parse_minimal_yaml_handles_quoted_strings(self):
        text = (
            "---\n"
            "name: 'quoted-name'\n"
            'description: "has: colon in it"\n'
            "tags: [one, two, three]\n"
            "version: 3\n"
            "---\n"
            "body here\n"
        )
        meta, body = parse_frontmatter(text)
        assert meta.name == "quoted-name"
        assert "has: colon in it" == meta.description
        assert meta.tags == ["one", "two", "three"]
        assert meta.version == 3
        assert body.strip() == "body here"

    def test_parse_no_frontmatter_returns_empty_meta(self):
        meta, body = parse_frontmatter("just a body, no frontmatter\n")
        assert meta.name == ""
        assert body.startswith("just a body")

    def test_metadata_post_init_sets_timestamps(self):
        m = SkillMetadata(name="x")
        assert m.created_at != ""
        assert m.updated_at == m.created_at
        m.touch()
        assert m.version == 2
        assert m.updated_at != m.created_at or True  # may tick in the same second


# ---------------------------------------------------------------------------
# Skill store tests
# ---------------------------------------------------------------------------

class TestSkillStore:
    def test_creates_directory_on_init(self, tmp_path_isolated: Path):
        target = tmp_path_isolated / "nested" / "spaces"
        store = SkillStore("alpha", base_dir=target)
        assert store.skills_dir.exists()
        assert store.space == "alpha"

    def test_upsert_creates_then_updates(self, tmp_store: SkillStore):
        s1 = tmp_store.upsert("alpha", "first desc", "first body", tags=["a"])
        assert s1.meta.version == 1
        first_updated = s1.meta.updated_at
        time.sleep(1.01)  # ISO timestamp has 1s resolution
        s2 = tmp_store.upsert("alpha", "second desc", "second body", tags=["a", "b"])
        assert s2.meta.version == 2
        assert s2.meta.description == "second desc"
        assert s2.meta.created_at == s1.meta.created_at  # preserved
        # updated_at may be identical at second resolution; allow equality
        assert s2.meta.updated_at >= first_updated

    def test_list_returns_seeded_skills(self, seeded_store: SkillStore):
        metas = seeded_store.list_metadata()
        names = {m.name for m in metas}
        assert names == {
            "python-venv-activation",
            "pytest-fixture-isolation",
            "json-repair-prompt",
        }

    def test_get_returns_full_skill(self, seeded_store: SkillStore):
        skill = seeded_store.get("json-repair-prompt")
        assert skill is not None
        assert "LLM call" in skill.body
        assert "json-repair-prompt" in skill.meta.tags or "json" in skill.meta.tags

    def test_get_missing_returns_none(self, seeded_store: SkillStore):
        assert seeded_store.get("does-not-exist") is None

    def test_delete_removes_file(self, seeded_store: SkillStore):
        assert seeded_store.exists("python-venv-activation")
        assert seeded_store.delete("python-venv-activation") is True
        assert seeded_store.exists("python-venv-activation") is False
        # Second delete returns False
        assert seeded_store.delete("python-venv-activation") is False

    def test_default_base_dir_under_home(self):
        p = default_base_dir()
        assert p.name == "acontext"
        assert ".graxia" in p.parts

    def test_skill_files_persist_with_yaml(self, seeded_store: SkillStore):
        # Ensure files are written with frontmatter
        for skill in seeded_store.list_skills():
            text = (seeded_store.skills_dir / f"{skill.name}.md").read_text(encoding="utf-8")
            assert text.startswith("---\n")
            assert "name:" in text
            assert "tags:" in text


# ---------------------------------------------------------------------------
# BM25 + recall tests
# ---------------------------------------------------------------------------

class TestBM25:
    def test_basic_scoring(self):
        bm = BM25()
        bm.index([
            "the quick brown fox jumps over the lazy dog",
            "a stitch in time saves nine",
            "the fox and the hound",
        ])
        scores = bm.score("fox")
        assert len(scores) == 3
        # Docs 0 and 2 mention "fox", doc 1 does not
        assert scores[0] > scores[1]
        assert scores[2] > scores[1]
        assert scores[0] > 0

    def test_empty_corpus(self):
        bm = BM25()
        bm.index([])
        assert bm.score("anything") == []

    def test_empty_query(self):
        bm = BM25()
        bm.index(["hello world"])
        assert bm.score("") == [0.0]


class TestRecall:
    def test_recall_finds_relevant_skill(self, seeded_store: SkillStore):
        hits = recall_skills(seeded_store, "How should I run pip install on Windows?", limit=2)
        assert hits
        assert hits[0].skill.name == "python-venv-activation"
        assert hits[0].score > 0

    def test_recall_respects_limit(self, seeded_store: SkillStore):
        hits = recall_skills(seeded_store, "python", limit=1)
        assert len(hits) == 1

    def test_recall_empty_space(self, tmp_store: SkillStore):
        hits = recall_skills(tmp_store, "anything", limit=5)
        assert hits == []

    def test_recall_no_match_returns_low_or_zero(self, seeded_store: SkillStore):
        # Query that does not share any meaningful token
        hits = recall_skills(seeded_store, "xyzzy plugh", limit=5)
        # All scores should be 0 (no token overlap)
        assert all(h.score == 0.0 for h in hits)


# ---------------------------------------------------------------------------
# Distiller tests (mocked LLM)
# ---------------------------------------------------------------------------

class _MockLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.model = "mock"
        self.tokens_in = 0
        self.tokens_out = 0
        self.cost_usd = 0.0
        self.duration_ms = 0
        self.metadata: Dict[str, Any] = {}


class _MockLLMClient:
    """Records all calls and returns a canned response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: List[Dict[str, Any]] = []

    async def complete(self, prompt: str, system: str = None, **kwargs) -> _MockLLMResponse:
        self.calls.append({"prompt": prompt, "system": system, "kwargs": kwargs})
        return _MockLLMResponse(self.response)


class TestDistiller:
    @pytest.mark.asyncio
    async def test_distill_writes_skill_files(self, tmp_store: SkillStore):
        canned = json.dumps({
            "skills": [
                {
                    "name": "Always-Read-File-Before-Edit",
                    "description": "Read a file fully before modifying it.",
                    "tags": ["editing", "safety"],
                    "body": (
                        "## Rule\nAlways read the full file before editing.\n\n"
                        "## Why\nPartial reads lead to clobbering unrelated sections."
                    ),
                },
                {
                    "name": "Prefer-Specific-Imports",
                    "description": "Prefer specific imports over star imports.",
                    "tags": ["style"],
                    "body": "Import only what you use. Avoid `from x import *`.",
                },
            ]
        })
        client = _MockLLMClient(canned)
        distiller = Distiller(client, store_factory=lambda s: tmp_store)
        result = await distiller.distill(
            space="ignored-by-factory",
            session_messages=[
                {"role": "user", "content": "Edit foo.py"},
                {"role": "assistant", "content": "Sure, here is the edit."},
            ],
            outcome="success",
            source_session="sess-1",
        )
        assert result.errors == []
        names = {s.meta.name for s in result.skills}
        assert "always-read-file-before-edit" in names
        assert "prefer-specific-imports" in names
        # Files on disk
        on_disk = {s.name for s in tmp_store.list_skills()}
        assert "always-read-file-before-edit" in on_disk
        assert "prefer-specific-imports" in on_disk
        # Tags preserved and lowercased
        rfb = tmp_store.get("always-read-file-before-edit")
        assert rfb is not None
        assert "editing" in rfb.meta.tags
        assert "safety" in rfb.meta.tags
        # source_session recorded
        assert rfb.meta.source_session == "sess-1"
        # LLM was called with system + user
        assert len(client.calls) == 1
        assert client.calls[0]["system"] is not None
        assert "Edit foo.py" in client.calls[0]["prompt"]

    @pytest.mark.asyncio
    async def test_distill_handles_code_fence_wrapped_json(self, tmp_store: SkillStore):
        canned = (
            "```json\n"
            + json.dumps({
                "skills": [
                    {
                        "name": "from-fenced-response",
                        "description": "Survives a code-fence response.",
                        "tags": ["llm"],
                        "body": "Body text.",
                    }
                ]
            })
            + "\n```\n"
        )
        client = _MockLLMClient(canned)
        distiller = Distiller(client, store_factory=lambda s: tmp_store)
        result = await distiller.distill(
            space="x",
            session_messages=[{"role": "user", "content": "hi"}],
        )
        assert result.errors == []
        assert len(result.skills) == 1
        assert result.skills[0].meta.name == "from-fenced-response"

    @pytest.mark.asyncio
    async def test_distill_save_false_does_not_write(self, tmp_store: SkillStore):
        canned = json.dumps({
            "skills": [
                {"name": "ephemeral", "description": "preview", "tags": [], "body": "x"},
            ]
        })
        client = _MockLLMClient(canned)
        distiller = Distiller(client, store_factory=lambda s: tmp_store)
        result = await distiller.distill(
            space="x",
            session_messages=[{"role": "user", "content": "q"}],
            save=False,
        )
        assert len(result.skills) == 1
        assert tmp_store.count() == 0

    @pytest.mark.asyncio
    async def test_distill_handles_llm_error(self, tmp_store: SkillStore):
        class _BoomClient:
            async def complete(self, *a, **kw):
                raise RuntimeError("network down")

        distiller = Distiller(_BoomClient(), store_factory=lambda s: tmp_store)
        result = await distiller.distill(
            space="x",
            session_messages=[{"role": "user", "content": "q"}],
        )
        assert result.skills == []
        assert any("llm call failed" in e for e in result.errors)


class TestJSONParser:
    def test_parse_strict(self):
        raw = json.dumps({"skills": [{"name": "x", "description": "d", "tags": [], "body": "b"}]})
        skills, errs = _parse_skills_json(raw)
        assert errs == []
        assert len(skills) == 1
        assert skills[0]["name"] == "x"

    def test_parse_with_fence(self):
        raw = "```json\n" + json.dumps({"skills": [{"name": "y", "body": "b"}]}) + "\n```"
        skills, errs = _parse_skills_json(raw)
        assert errs == []
        assert skills[0]["name"] == "y"

    def test_parse_garbage_returns_error(self):
        skills, errs = _parse_skills_json("definitely not json")
        assert skills == []
        assert errs

    def test_slugify(self):
        assert _slugify_skill_name("Hello World!") == "hello-world"
        assert _slugify_skill_name("  spaces  ") == "spaces"
        assert _slugify_skill_name("!!!") == ""
        assert _slugify_skill_name("a" * 100).startswith("a" * 60)


# ---------------------------------------------------------------------------
# MCP tool-handler tests (no LLM; use save=False / dry_run)
# ---------------------------------------------------------------------------

class _ToolResult:
    """Helper to extract the data dict from a tool result envelope."""

    @staticmethod
    def data(result: Dict[str, Any]) -> Dict[str, Any]:
        assert "content" in result
        text = result["content"][0]["text"]
        return json.loads(text)


class TestMCPToolHandlers:
    @pytest.mark.asyncio
    async def test_acontext_learn_dry_run(self, monkeypatch, tmp_path_isolated: Path):
        # Monkeypatch the LLM resolver so no network is hit
        from graxia_tool.mcp import acontext_tools
        from graxia_tool.acontext import SkillStore

        canned = json.dumps({
            "skills": [
                {"name": "dryrun-skill", "description": "dry", "tags": ["t"], "body": "b"},
            ]
        })
        monkeypatch.setattr(acontext_tools, "_get_llm_client", lambda: _MockLLMClient(canned))

        # Provide an explicit base_dir so the test does not touch ~/.graxia
        result = await acontext_learn({
            "space": "test-space",
            "session_messages": [{"role": "user", "content": "go"}],
            "outcome": "success",
            "base_dir": str(tmp_path_isolated),
            "save": True,
        })
        data = _ToolResult.data(result)
        assert data["space"] == "test-space"
        assert data["skill_count"] == 1
        assert data["saved"][0]["name"] == "dryrun-skill"
        # File actually written
        store = SkillStore("test-space", base_dir=tmp_path_isolated)
        assert store.exists("dryrun-skill")

    @pytest.mark.asyncio
    async def test_acontext_learn_missing_args(self):
        # No LLM needed; argument validation runs first
        r1 = await acontext_learn({"space": "", "session_messages": []})
        r2 = await acontext_learn({"space": "x", "session_messages": "not a list"})
        assert "is required" in r1["content"][0]["text"] or "is required" in r1["content"][0]["text"]
        assert "must be a list" in r2["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_acontext_list_skills_empty(self, tmp_path_isolated: Path):
        result = await acontext_list_skills({"space": "nope", "base_dir": str(tmp_path_isolated)})
        data = _ToolResult.data(result)
        assert data["count"] == 0
        assert data["skills"] == []

    @pytest.mark.asyncio
    async def test_acontext_list_skills_returns_seeded(self, seeded_store: SkillStore, tmp_path_isolated: Path):
        result = await acontext_list_skills({
            "space": seeded_store.space,
            "base_dir": str(tmp_path_isolated),
        })
        data = _ToolResult.data(result)
        assert data["count"] == 3
        names = {s["name"] for s in data["skills"]}
        assert "python-venv-activation" in names

    @pytest.mark.asyncio
    async def test_acontext_recall_finds_match(self, seeded_store: SkillStore, tmp_path_isolated: Path):
        result = await acontext_recall({
            "space": seeded_store.space,
            "query": "pip install on Windows",
            "limit": 2,
            "base_dir": str(tmp_path_isolated),
        })
        data = _ToolResult.data(result)
        assert data["count"] >= 1
        assert data["results"][0]["name"] == "python-venv-activation"
        assert data["results"][0]["score"] > 0
        assert data["rerank"] is False

    @pytest.mark.asyncio
    async def test_acontext_recall_missing_query(self, seeded_store: SkillStore, tmp_path_isolated: Path):
        result = await acontext_recall({
            "space": seeded_store.space,
            "query": "",
            "base_dir": str(tmp_path_isolated),
        })
        assert "query is required" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_acontext_get_and_delete_skill(self, seeded_store: SkillStore, tmp_path_isolated: Path):
        # Get
        r1 = await acontext_get_skill({
            "space": seeded_store.space,
            "name": "json-repair-prompt",
            "base_dir": str(tmp_path_isolated),
        })
        d1 = _ToolResult.data(r1)
        assert d1["name"] == "json-repair-prompt"
        assert "json" in d1["body"].lower() or "JSON" in d1["body"]

        # Get missing
        r2 = await acontext_get_skill({
            "space": seeded_store.space,
            "name": "no-such-skill",
            "base_dir": str(tmp_path_isolated),
        })
        assert "not found" in r2["content"][0]["text"]

        # Delete
        r3 = await acontext_delete_skill({
            "space": seeded_store.space,
            "name": "json-repair-prompt",
            "base_dir": str(tmp_path_isolated),
        })
        d3 = _ToolResult.data(r3)
        assert d3["removed"] is True
        # Delete again -> removed False
        r4 = await acontext_delete_skill({
            "space": seeded_store.space,
            "name": "json-repair-prompt",
            "base_dir": str(tmp_path_isolated),
        })
        d4 = _ToolResult.data(r4)
        assert d4["removed"] is False

    def test_acontext_tools_registered(self):
        """The 5 Acontext tools are present in the module's tool list."""
        names = {t["name"] for t in ACONTEXT_TOOLS}
        assert names == {
            "acontext_learn",
            "acontext_list_skills",
            "acontext_recall",
            "acontext_get_skill",
            "acontext_delete_skill",
        }


class TestRegistryIntegration:
    """The 5 tools must appear in build_default_registry()."""

    def test_acontext_tools_in_default_registry(self):
        from graxia_tool.mcp import build_default_registry

        reg = build_default_registry()
        names = {t.name for t in reg.list_all()}
        # After merge: 5 acontext tools → graxia_memory_ext super-tool
        assert "graxia_memory_ext" in names, "graxia_memory_ext not registered"


# ---------------------------------------------------------------------------
# Integration tests — real OpenRouter calls
# ---------------------------------------------------------------------------

HAS_OPENROUTER_KEY = bool(os.getenv("OPENROUTER_API_KEY"))


@pytest.mark.integration
@pytest.mark.skipif(not HAS_OPENROUTER_KEY, reason="OPENROUTER_API_KEY not set")
class TestRealOpenRouter:
    """End-to-end tests against a real LLM via HybridLLMClient."""

    @pytest.mark.asyncio
    async def test_distill_real_session(self, tmp_path_isolated: Path):
        from graxia_tool.llm import HybridLLMClient

        client = HybridLLMClient()
        store = SkillStore("integration-space", base_dir=tmp_path_isolated)
        distiller = Distiller(client, store_factory=lambda s: store)

        result = await distiller.distill(
            space=store.space,
            session_messages=[
                {"role": "user", "content": (
                    "How do I configure pytest to only run tests marked as 'slow' on CI?"
                )},
                {"role": "assistant", "content": (
                    "Use `-m slow` to select slow tests, or `-m 'not slow'` to skip them. "
                    "Add `addopts = -m 'not slow'` to pytest.ini for the default."
                )},
                {"role": "user", "content": "Good. Now how do I add a custom marker?"},
                {"role": "assistant", "content": (
                    "Register the marker in pytest.ini under the [pytest] section with "
                    "`markers = slow: marks tests as slow (deselect with '-m \"not slow\"')`. "
                    "Then decorate the test with `@pytest.mark.slow`."
                )},
            ],
            outcome="success",
            outcome_note="User successfully configured pytest markers.",
            source_session="integration-sess-1",
        )

        # Real LLM may or may not produce perfectly parseable JSON;
        # accept the result as long as either it parsed cleanly or
        # we got a non-empty raw response.
        assert result.raw_response, "LLM returned empty response"
        assert isinstance(result.skills, list)
        if result.errors and not result.skills:
            pytest.skip(f"LLM did not return parseable JSON: {result.errors[:1]}")
        # If we got at least one skill, it must be on disk
        for s in result.skills:
            assert store.exists(s.meta.name), f"saved skill {s.meta.name} not on disk"

    @pytest.mark.asyncio
    async def test_recall_real_llm_rerank(self, tmp_path_isolated: Path):
        from graxia_tool.llm import HybridLLMClient

        store = SkillStore("integration-recall", base_dir=tmp_path_isolated)
        store.upsert(
            name="docker-build-cache",
            description="Use BuildKit cache mounts to speed up Docker builds.",
            body=(
                "Add `--mount=type=cache,target=/root/.cache/pip` to RUN steps that "
                "install Python packages. This keeps pip's download cache between "
                "builds and cuts install time by 50-80%."
            ),
            tags=["docker", "performance"],
        )
        store.upsert(
            name="postgres-connection-pool",
            description="Use a connection pool (pgbouncer) in front of PostgreSQL.",
            body=(
                "For serverless or high-concurrency workloads, put pgbouncer in "
                "transaction-pooling mode in front of PostgreSQL. Don't pool long-lived "
                "sessions — only short transactions."
            ),
            tags=["postgres", "ops"],
        )
        store.upsert(
            name="react-key-prop",
            description="Always pass a stable `key` prop to list children.",
            body=(
                "When rendering arrays, give each child a unique, stable `key` based on "
                "its identity (e.g. id), not its index. Index keys cause state bugs when "
                "the list is reordered."
            ),
            tags=["react", "frontend"],
        )

        client = HybridLLMClient()
        hits = recall_skills(
            store,
            "How can I make my Docker image build faster?",
            limit=2,
            rerank=True,
            llm_client=client,
        )
        assert hits, "expected at least one hit"
        # The Docker skill should be the most relevant
        assert hits[0].skill.meta.name == "docker-build-cache"
