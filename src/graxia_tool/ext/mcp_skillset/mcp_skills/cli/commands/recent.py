"""Command: recent - Show recently updated skills."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import click
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from mcp_skills.cli.shared.console import console
from mcp_skills.services.skill_manager import SkillManager


@click.command()
@click.option(
    "--days",
    type=int,
    default=7,
    help="Show skills updated in last N days (default: 7)",
)
@click.option(
    "--since",
    type=str,
    help="Show skills updated since date (ISO format: YYYY-MM-DD)",
)
@click.option("--limit", type=int, default=20, help="Maximum results (default: 20)")
def recent(days: int, since: str | None, limit: int) -> None:
    """Show recently updated skills.

    Displays skills that have been added or updated recently based on file
    modification time. Useful for discovering new content.

    Examples:
        mcp-skillset recent                  # Last 7 days
        mcp-skillset recent --days 30        # Last 30 days
        mcp-skillset recent --since 2025-01-01  # Since specific date
        mcp-skillset recent --days 14 --limit 50  # Last 2 weeks, max 50 results
    """
    # Determine cutoff date
    if since:
        try:
            cutoff_date = datetime.fromisoformat(since).replace(tzinfo=UTC)
            console.print(f"📅 [bold]Showing skills updated since:[/bold] {since}")
        except ValueError:
            console.print(
                f"[red]Invalid date format: {since}[/red]\n"
                "Use ISO format: YYYY-MM-DD (e.g., 2025-01-01)"
            )
            raise SystemExit(1)
    else:
        cutoff_date = datetime.now(tz=UTC) - timedelta(days=days)
        console.print(f"📅 [bold]Showing skills updated in last {days} days[/bold]")

    console.print()

    try:
        # Initialize services with progress indicator
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,  # Remove spinner after completion
        ) as progress:
            task = progress.add_task("Discovering skills...", total=None)

            # Initialize skill manager and discover all skills
            skill_manager = SkillManager()
            all_skills = skill_manager.discover_skills()

            progress.update(task, description="Filtering recent skills...")

            # Filter skills by updated_at date
            recent_skills = []
            for skill in all_skills:
                if skill.updated_at and skill.updated_at >= cutoff_date:
                    recent_skills.append(skill)

            # Sort by updated_at descending (most recent first)
            recent_skills.sort(key=lambda s: s.updated_at or datetime.min, reverse=True)

            # Limit results
            recent_skills = recent_skills[:limit]

            progress.update(task, completed=True)

        if not recent_skills:
            console.print("[yellow]No recently updated skills found[/yellow]")
            console.print("\nTry:")
            console.print("  • Increasing --days value")
            console.print("  • Using --since with an earlier date")
            console.print("  • Running: mcp-skillset discover")
            return

        # Display results in table
        table = Table(title=f"Recently Updated Skills ({len(recent_skills)} found)")
        table.add_column("Name", style="cyan", no_wrap=True)
        table.add_column("Category", style="magenta")
        table.add_column("Updated", style="green")
        table.add_column("Tags", style="dim")

        for skill in recent_skills:
            # Format updated_at timestamp
            if skill.updated_at:
                # Calculate relative time
                time_delta = datetime.now(tz=UTC) - skill.updated_at
                if time_delta.days == 0:
                    updated_str = "Today"
                elif time_delta.days == 1:
                    updated_str = "Yesterday"
                elif time_delta.days < 7:
                    updated_str = f"{time_delta.days}d ago"
                elif time_delta.days < 30:
                    weeks = time_delta.days // 7
                    updated_str = f"{weeks}w ago"
                else:
                    months = time_delta.days // 30
                    updated_str = f"{months}mo ago"
            else:
                updated_str = "Unknown"

            # Format tags
            tags_str = ", ".join(skill.tags[:3])  # Show first 3 tags
            if len(skill.tags) > 3:
                tags_str += f" +{len(skill.tags) - 3}"

            table.add_row(
                skill.name,
                skill.category,
                updated_str,
                tags_str,
            )

        console.print(table)
        console.print("\n[dim]Use 'mcp-skillset info <skill-id>' for details[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to load recent skills: {e}[/red]")
        import logging

        logger = logging.getLogger(__name__)
        logger.exception("Recent command failed")
        raise SystemExit(1)
