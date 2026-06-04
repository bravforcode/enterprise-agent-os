"""Command: mcp - Start MCP server for Claude Code integration."""

from __future__ import annotations

import sys

import click
from rich.console import Console


# Create stderr console for MCP mode - stdout must be reserved for JSON-RPC
stderr_console = Console(stderr=True, force_terminal=True)


@click.command(name="mcp")
@click.option("--dev", is_flag=True, help="Development mode")
def mcp(dev: bool) -> None:
    """Start MCP server for Claude Code integration.

    Starts the FastMCP server using stdio transport, making skills
    available to Claude Code via Model Context Protocol.

    Usage:
        mcp-skillset mcp

    The server will run in stdio mode and communicate with Claude Code.

    IMPORTANT: All output goes to stderr to preserve stdout for JSON-RPC protocol.
    """
    stderr_console.print(
        "🚀 [bold green]Starting MCP server for Claude Code...[/bold green]"
    )
    stderr_console.print("📡 stdio transport")

    if dev:
        stderr_console.print("🔧 [yellow]Development mode enabled[/yellow]")

    # Import and configure MCP server
    from mcp_skills.mcp.server import configure_services
    from mcp_skills.mcp.server import main as mcp_main

    try:
        # Initialize services (SkillManager, IndexingEngine, ToolchainDetector, RepositoryManager)
        stderr_console.print("⚙️  Configuring services...")
        configure_services()

        stderr_console.print("✅ Services configured")
        stderr_console.print("📡 stdio transport active")
        stderr_console.print("🎯 Ready for Claude Code connection\n")

        # Start FastMCP server (blocks until terminated)
        mcp_main()
    except KeyboardInterrupt:
        stderr_console.print("\n[yellow]⚠️  Server stopped by user[/yellow]")
        raise SystemExit(0)
    except Exception as e:
        stderr_console.print(f"\n[red]❌ Server failed to start: {e}[/red]")
        import traceback

        if dev:
            traceback.print_exc(file=sys.stderr)
        raise SystemExit(1)
