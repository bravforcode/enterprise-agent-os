"""Command: enrich-hook - Hook-optimized prompt enrichment for Claude Code."""

from __future__ import annotations

import json
import logging
import sys

import click

from mcp_skills.models.config import MCPSkillsConfig
from mcp_skills.services.indexing.engine import IndexingEngine


logger = logging.getLogger(__name__)


def _get_engine() -> IndexingEngine | None:
    """Get IndexingEngine instance, returns None if not available."""
    try:
        config = MCPSkillsConfig()
        return IndexingEngine(config=config)
    except Exception:
        return None


@click.command("enrich-hook")
@click.option(
    "--threshold",
    default=0.6,
    type=float,
    help="Similarity threshold (0.0-1.0, default: 0.6)",
)
@click.option(
    "--max-skills",
    default=5,
    type=int,
    help="Maximum skills to suggest (default: 5)",
)
def enrich_hook(threshold: float, max_skills: int) -> None:
    """Hook command for Claude Code prompt enrichment.

    Reads JSON from stdin (Claude Code UserPromptSubmit format),
    performs semantic search for matching skills, and outputs
    skill hints as a systemMessage.

    This command is designed for use as a Claude Code hook and
    will fail silently (output {}) on any error to avoid
    interrupting the user's workflow.

    Input format (stdin):
        {"user_prompt": "Write pytest tests for my API"}

    Output format (stdout):
        {"systemMessage": "Skills: pytest-fixtures, mock-patterns - use /skill <name> to load"}

    Or empty on no matches/errors:
        {}
    """
    try:
        # Read JSON from stdin
        input_data = json.load(sys.stdin)
        prompt = input_data.get("user_prompt", "")

        if not prompt or not prompt.strip():
            # No prompt provided - return empty
            print(json.dumps({}))
            return

        # Get indexing engine
        engine = _get_engine()
        if engine is None:
            print(json.dumps({}))
            return

        # Search for matching skills
        results = engine.search(prompt, top_k=max_skills * 2)  # Get extra for filtering

        # Filter by threshold
        matching = [r for r in results if r.score >= threshold]

        if not matching:
            print(json.dumps({}))
            return

        # Take top N skills
        top_skills = matching[:max_skills]

        # Format brief hint
        skill_names = [r.skill.name for r in top_skills]
        hint = f"Skills: {', '.join(skill_names)} - use /skill <name> to load"

        # Output response
        response = {"systemMessage": hint}
        print(json.dumps(response))

    except Exception:
        # Silent failure - never interrupt user workflow
        print(json.dumps({}))
