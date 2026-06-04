"""Ask command - LLM-powered help for coding questions."""

import re

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel


console = Console()

# Patterns that indicate a date-related query about skills
DATE_QUERY_PATTERNS = [
    r"\brecent(ly)?\b.*\b(skill|update)",
    r"\bupdate[ds]?\b.*\b(recent|lately|last)",
    r"\bnew(est)?\b.*\bskill",
    r"\blast\b.*\b(week|month|day|update)",
    r"\bwhat.*\bupdate[ds]?\b",
    r"\bwhich.*\b(new|recent|update)",
]


def _is_date_query(question: str) -> bool:
    """Check if the question is asking about recently updated skills."""
    question_lower = question.lower()
    return any(re.search(pattern, question_lower) for pattern in DATE_QUERY_PATTERNS)


@click.command()
@click.argument("question", nargs=-1, required=True)
@click.option(
    "--no-context",
    is_flag=True,
    help="Skip skill search for context (faster but less specific)",
)
@click.option(
    "--model",
    default=None,
    help="Override LLM model (e.g., anthropic/claude-3-sonnet)",
)
def ask(question: tuple[str, ...], no_context: bool, model: str | None) -> None:
    """Ask a question about coding practices or skills.

    The ask command uses an LLM to answer questions about coding practices,
    tools, and development workflows. It optionally searches the skill library
    to provide context-aware answers.

    Examples:

    \b
        # Ask about pytest fixtures
        mcp-skillset ask "How do I write pytest fixtures?"

    \b
        # Multiple words without quotes
        mcp-skillset ask How do I mock dependencies in tests

    \b
        # Skip skill context for faster response
        mcp-skillset ask "What are SOLID principles?" --no-context

    \b
        # Use a different model
        mcp-skillset ask "Explain async/await" --model anthropic/claude-3-sonnet

    Configuration:

    \b
        Set your OpenRouter API key via one of:
        - Environment: export OPENROUTER_API_KEY=sk-or-...
        - Config file: mcp-skillset config (LLM settings)
        - .env file: OPENROUTER_API_KEY=sk-or-...

    Get an API key at: https://openrouter.ai/
    """
    from mcp_skills.models.config import MCPSkillsConfig
    from mcp_skills.services.indexing import IndexingEngine
    from mcp_skills.services.llm_service import LLMService
    from mcp_skills.services.skill_manager import SkillManager

    # Join question parts
    question_text = " ".join(question)

    # Display question
    console.print(f"\n[bold cyan]Question:[/bold cyan] {question_text}\n")

    # Load configuration
    try:
        config = MCPSkillsConfig()
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to load configuration: {e}")
        raise SystemExit(1) from e

    # Override model if specified
    if model:
        config.llm.model = model
        console.print(f"[dim]Using model: {model}[/dim]\n")

    # Initialize LLM service
    llm_service = LLMService(config.llm)

    # Check for API key
    if not llm_service.get_api_key():
        console.print("[red]Error:[/red] No OpenRouter API key configured.\n")
        console.print("[yellow]Configure your API key via one of:[/yellow]")
        console.print("  1. Environment: export OPENROUTER_API_KEY=sk-or-...")
        console.print("  2. Config file: mcp-skillset config (LLM settings)")
        console.print("  3. .env file: OPENROUTER_API_KEY=sk-or-...")
        console.print("\n[dim]Get an API key at: https://openrouter.ai/[/dim]")
        raise SystemExit(1)

    # Check if this is a date-related query about skills
    is_date_query = _is_date_query(question_text)

    # Search for relevant skills to provide context
    context = ""
    if not no_context:
        try:
            skill_manager = SkillManager()
            indexing_engine = IndexingEngine(skill_manager=skill_manager)

            # For date-related queries, get recent skills instead of semantic search
            if is_date_query:
                with console.status("[cyan]Finding recently updated skills...[/cyan]"):
                    from datetime import UTC, datetime, timedelta

                    # Get skills updated in last 30 days
                    since = datetime.now(UTC) - timedelta(days=30)
                    all_skills = skill_manager.discover_skills()

                    # Filter and sort by update date
                    recent_skills = [
                        s for s in all_skills if s.updated_at and s.updated_at >= since
                    ]
                    recent_skills.sort(
                        key=lambda s: s.updated_at or datetime.min.replace(tzinfo=UTC),
                        reverse=True,
                    )
                    recent_skills = recent_skills[:10]  # Top 10

                    if recent_skills:
                        context_parts = [
                            "## Recently Updated Skills (last 30 days)\n"
                            "Here are skills that have been updated recently:\n"
                        ]
                        console.print("[dim]Recently updated skills:[/dim]")

                        for skill in recent_skills:
                            # updated_at is guaranteed non-None by filter above
                            assert skill.updated_at is not None
                            age = datetime.now(UTC) - skill.updated_at
                            if age.days == 0:
                                age_str = "Today"
                            elif age.days == 1:
                                age_str = "Yesterday"
                            elif age.days < 7:
                                age_str = f"{age.days} days ago"
                            elif age.days < 14:
                                age_str = "1 week ago"
                            else:
                                age_str = f"{age.days // 7} weeks ago"

                            console.print(f"  • {skill.name} ({age_str})")
                            context_parts.append(
                                f"- **{skill.name}** (ID: {skill.id}) - Updated {age_str}\n"
                                f"  Description: {skill.description[:200]}"
                            )

                        context = "\n".join(context_parts)
                        console.print()
                    else:
                        console.print("[dim]No skills updated in last 30 days[/dim]\n")

            else:
                # Standard semantic search for non-date queries
                with console.status("[cyan]Searching relevant skills...[/cyan]"):
                    results = indexing_engine.search(question_text, top_k=3)

                    if results:
                        context_parts = []
                        console.print("[dim]Found relevant skills:[/dim]")

                        for r in results:
                            console.print(
                                f"  • {r.skill.id} (relevance: {r.score:.2f})"
                            )

                            # Use skill instructions from search results for context
                            if r.skill and r.skill.instructions:
                                # Limit context to 2000 chars per skill to avoid token limits
                                skill_content = r.skill.instructions[:2000]
                                context_parts.append(
                                    f"## {r.skill.name}\n{skill_content}"
                                )

                        context = "\n\n".join(context_parts)
                        console.print()

        except Exception as e:
            # Non-fatal: continue without skill context
            console.print(f"[yellow]Warning:[/yellow] Could not search skills: {e}\n")

    # Ask LLM
    try:
        with console.status("[cyan]Thinking...[/cyan]"):
            answer = llm_service.ask(question_text, context)

        # Display answer in a panel with markdown rendering
        console.print(
            Panel(
                Markdown(answer),
                title="[bold green]Answer[/bold green]",
                border_style="green",
                padding=(1, 2),
            )
        )

    except ValueError as e:
        # Configuration or API errors
        console.print(f"[red]Error:[/red] {e}")
        raise SystemExit(1) from e

    except Exception as e:
        # Unexpected errors
        console.print(f"[red]Error:[/red] Unexpected error: {e}")
        if config.server.log_level == "debug":
            console.print_exception()
        raise SystemExit(1) from e
