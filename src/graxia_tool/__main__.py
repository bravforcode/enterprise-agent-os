"""Graxia Tool CLI entry point.

Usage:
    python -m graxia_tool                 # Start MCP server (default)
    python -m graxia_tool web             # Start web UI
    python -m graxia_tool install         # Run installer
    python -m graxia_tool agents          # List available agents
    python -m graxia_tool status          # Show system status
    python -m graxia_tool ollama          # Setup Ollama
"""
from __future__ import annotations

import argparse
import asyncio
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="graxia",
        description="Graxia Tool — zero-setup AI agent platform",
    )
    subparsers = parser.add_subparsers(dest="cmd", help="Command")

    # Default = MCP server
    subparsers.add_parser("mcp", help="Start MCP server (default)")
    subparsers.add_parser("web", help="Start web UI")
    subparsers.add_parser("install", help="Run one-line installer")
    subparsers.add_parser("agents", help="List available agents")
    subparsers.add_parser("status", help="Show system status")
    subparsers.add_parser("ollama", help="Setup Ollama")

    # If no args, default to mcp
    if len(sys.argv) == 1:
        sys.argv.append("mcp")

    args = parser.parse_args()

    if args.cmd == "install":
        from .installer import install
        install()
        return

    if args.cmd == "web":
        try:
            from .web import run_server
        except ImportError as e:
            print(f"Web UI requires: pip install graxia-tool[web]")
            print(f"Error: {e}")
            sys.exit(1)
        run_server()
        return

    if args.cmd == "agents":
        try:
            from .agents import AGENT_REGISTRY
            for name, cls in sorted(AGENT_REGISTRY.items()):
                desc = getattr(cls, "description", "")
                print(f"  {name:20s}  {desc}")
        except ImportError as e:
            print(f"Error: {e}")
        return

    if args.cmd == "status":
        from .ollama_helper import is_ollama_installed, is_ollama_running
        print("Graxia Tool Status")
        print("=" * 40)
        print(f"  Ollama installed: {'YES' if is_ollama_installed() else 'NO'}")

        async def check_running():
            running = await is_ollama_running()
            print(f"  Ollama running:   {'YES' if running else 'NO'}")
            if running:
                from .llm import OllamaClient
                client = OllamaClient()
                models = await client.list_models()
                print(f"  Models available: {len(models)}")
                for m in models[:5]:
                    print(f"    - {m}")
                await client.close()
            try:
                from .agents import AGENT_REGISTRY
                print(f"  Agents loaded:    {len(AGENT_REGISTRY)}")
            except Exception:
                pass

        asyncio.run(check_running())
        return

    if args.cmd == "ollama":
        from .ollama_helper import ensure_ollama
        asyncio.run(ensure_ollama())
        return

    # Default: start MCP server
    try:
        from .mcp import main as mcp_main, MCPServer
    except ImportError as e:
        print(f"MCP server requires: pip install graxia-tool[mcp]")
        print(f"Error: {e}")
        sys.exit(1)
    # MCP's main() uses argparse on sys.argv. We've already parsed 'mcp'
    # out, so strip our own args before delegating.
    sys.argv = [sys.argv[0]]
    # If no MCP args, run stdio directly to avoid argparse parsing our subcommand
    if len(sys.argv) == 1:
        asyncio.run(MCPServer().run_stdio())
    else:
        mcp_main()


if __name__ == "__main__":
    main()
