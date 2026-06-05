"""Graxia Tool — Auto-configure all IDEs for zero-install MCP.

Run once: python setup_ide.py
Detects Python, sets PYTHONPATH, configures all IDEs automatically.

Supported IDEs:
- Claude Code (~/.claude/.mcp.json)
- Claude Desktop (~/.claude/claude_desktop_config.json)
- Codex (.codex/config.toml)
- Gemini (~/.gemini/mcp.json)
- OpenCode (.config/opencode/config.json)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


# ── Config ──────────────────────────────────────────────────────────────

PYTHON_EXE = sys.executable
PROJECT_ROOT = Path(os.environ.get("AGENT_OS_ROOT", r"C:\Users\menum\enterprise-agent-os"))
SRC_DIR = PROJECT_ROOT / "src"
VAULT_PATH = r"C:\Users\menum\Documents\ObsidianVault\Second Brain"

MCP_ENV = {
    "PYTHONPATH": str(SRC_DIR).replace("\\", "/"),
    "PYTHONIOENCODING": "utf-8",
    "AGENT_OS_VAULT_PATH": VAULT_PATH,
}


# ── Helpers ─────────────────────────────────────────────────────────────

def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  OK {path}")


def _backup(path: Path) -> None:
    if path.exists():
        backup = path.with_suffix(path.suffix + ".bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())


# ── Claude Code ─────────────────────────────────────────────────────────

def setup_claude_code() -> None:
    """Configure ~/.claude/.mcp.json for Claude Code."""
    print("\n[Claude Code]")
    path = Path.home() / ".claude" / ".mcp.json"
    _backup(path)

    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    servers = data.get("mcpServers", {})

    # Add/update graxia
    servers["graxia"] = {
        "command": PYTHON_EXE,
        "args": ["-m", "graxia_tool.mcp"],
        "env": MCP_ENV,
    }

    # Add/update run (if missing)
    if "run" not in servers:
        servers["run"] = {
            "command": PYTHON_EXE,
            "args": ["-m", "graxia_tool.mcp"],
            "env": MCP_ENV,
        }

    data["mcpServers"] = servers
    _write_json(path, data)


# ── Claude Desktop ──────────────────────────────────────────────────────

def setup_claude_desktop() -> None:
    """Configure ~/.claude/claude_desktop_config.json for Claude Desktop."""
    print("\n[Claude Desktop]")
    path = Path.home() / ".claude" / "claude_desktop_config.json"
    _backup(path)

    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    servers = data.get("mcpServers", {})
    servers["graxia_tool"] = {
        "command": PYTHON_EXE,
        "args": ["-m", "graxia_tool.mcp", "--transport", "stdio"],
        "env": MCP_ENV,
    }
    data["mcpServers"] = servers
    _write_json(path, data)


# ── Codex ───────────────────────────────────────────────────────────────

def setup_codex() -> None:
    """Configure .codex/config.toml for Codex."""
    print("\n[Codex]")
    path = PROJECT_ROOT / ".codex" / "config.toml"
    _backup(path)

    # Read existing TOML as text and inject/update graxia section
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)

    # Remove old graxia section if exists
    new_lines = []
    skip = False
    for line in lines:
        if line.strip() == "[mcp_servers.graxia]":
            skip = True
            continue
        if skip and line.strip().startswith("[") and not line.strip().startswith("[mcp_servers.graxia"):
            skip = False
        if skip and line.strip().startswith("[mcp_servers.graxia.env]"):
            continue
        if skip and (line.strip().startswith("command") or line.strip().startswith("args") or
                     line.strip().startswith("startup_timeout") or line.strip().startswith("PYTHONPATH") or
                     line.strip().startswith("PYTHONIOENCODING") or line.strip().startswith("AGENT_OS")):
            continue
        if not skip:
            new_lines.append(line)

    # Add graxia section at end
    graxia_toml = f"""
[mcp_servers.graxia]
command = "{PYTHON_EXE}"
args = ["-m", "graxia_tool.mcp"]
startup_timeout_sec = 180

[mcp_servers.graxia.env]
PYTHONPATH = "{MCP_ENV['PYTHONPATH']}"
PYTHONIOENCODING = "{MCP_ENV['PYTHONIOENCODING']}"
AGENT_OS_VAULT_PATH = "{MCP_ENV['AGENT_OS_VAULT_PATH']}"
"""
    new_lines.append(graxia_toml)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(new_lines), encoding="utf-8")
    print(f"  OK {path}")


# ── Gemini ──────────────────────────────────────────────────────────────

def setup_gemini() -> None:
    """Configure ~/.gemini/mcp.json for Gemini."""
    print("\n[Gemini]")
    path = Path.home() / ".gemini" / "mcp.json"
    _backup(path)

    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    servers = data.get("mcpServers", {})
    servers["graxia"] = {
        "command": PYTHON_EXE,
        "args": ["-m", "graxia_tool.mcp"],
        "env": MCP_ENV,
    }
    data["mcpServers"] = servers
    _write_json(path, data)


# ── OpenCode ────────────────────────────────────────────────────────────

def setup_opencode() -> None:
    """Configure .config/opencode/config.json for OpenCode."""
    print("\n[OpenCode]")
    path = Path.home() / ".config" / "opencode" / "config.json"
    _backup(path)

    data = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))

    mcp = data.get("mcp", {})
    mcp["graxia"] = {
        "type": "local",
        "command": [PYTHON_EXE, "-m", "graxia_tool.mcp"],
        "environment": MCP_ENV,
        "enabled": True,
        "timeout": 120000,
    }
    data["mcp"] = mcp
    _write_json(path, data)


# ── Main ────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("Graxia Tool — IDE Auto-Configuration")
    print("=" * 60)
    print(f"Python: {PYTHON_EXE}")
    print(f"Source: {SRC_DIR}")
    print(f"Vault:  {VAULT_PATH}")

    setup_claude_code()
    setup_claude_desktop()
    setup_codex()
    setup_gemini()
    setup_opencode()

    print("\n" + "=" * 60)
    print("DONE! All IDEs configured for zero-install MCP.")
    print("=" * 60)
    print("\nRestart your IDEs to pick up the new config.")
    print("Each IDE will auto-connect to Graxia MCP on startup.")


if __name__ == "__main__":
    main()
