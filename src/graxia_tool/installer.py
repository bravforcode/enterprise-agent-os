"""Graxia Tool — One-line installer.

Installs everything needed to use Graxia with OpenRouter (free) or Ollama (offline):
1. Checks OPENROUTER_API_KEY (recommended — free cloud, auto-fallback chain)
2. Ensures Ollama is installed and running (offline fallback)
3. Pulls default model
4. Configures MCP clients (Claude Desktop, Codex, Gemini, OpenCode, Cursor)
5. Creates launcher scripts

Usage:
    pip install graxia-tool
    # Optional: set OPENROUTER_API_KEY in env for cloud free tier
    python -c "from graxia_tool.installer import install; install()"
    # Or:
    graxia-install
"""
from __future__ import annotations

import asyncio
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Optional

# Force UTF-8 output on Windows (default cp1252 chokes on ✓)
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# Import lazily to avoid forcing httpx at import time


GRAXIA_MCP_CONFIG = {
    "command": sys.executable,
    "args": ["-m", "graxia_tool"],
    "env": {},
}


def _graphify_mcp_config() -> Optional[dict]:
    """Return graphify MCP config if graphify is installed and graph exists."""
    try:
        import graphify  # noqa: F401
    except ImportError:
        return None
    # Find graph.json in common locations
    for loc in ["graphify-out/graph.json", "src/graxia_tool/graphify-out/graph.json"]:
        if Path(loc).exists():
            return {
                "command": sys.executable,
                "args": ["-m", "graphify.serve", loc],
                "env": {},
            }
    return None


def _config_path_claude() -> Path:
    """Claude Desktop config path."""
    system = platform.system().lower()
    if system == "windows":
        appdata = os.getenv("APPDATA", "")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    elif system == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _config_path_codex() -> Path:
    """Codex config path."""
    return Path.home() / ".codex" / "config.yaml"


def _config_path_gemini() -> Path:
    """Gemini config path."""
    return Path.home() / ".gemini" / "settings.json"


def _config_path_opencode() -> Path:
    """OpenCode config path."""
    return Path.home() / ".config" / "opencode" / "config.json"


def _read_json(path: Path) -> dict:
    """Read JSON file, return empty dict if missing."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict):
    """Write JSON file with pretty formatting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def configure_claude_desktop() -> bool:
    """Add Graxia MCP server to Claude Desktop config."""
    path = _config_path_claude()
    config = _read_json(path)
    servers = config.setdefault("mcpServers", {})
    servers["graxia"] = GRAXIA_MCP_CONFIG
    gf = _graphify_mcp_config()
    if gf:
        servers["graphify"] = gf
    _write_json(path, config)
    return True


def configure_codex() -> bool:
    """Add Graxia MCP server to Codex config."""
    path = _config_path_codex()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    config = _read_json(path)
    # Codex config is typically YAML but we use JSON-style here
    mcp = config.setdefault("mcpServers", {})
    mcp["graxia"] = GRAXIA_MCP_CONFIG
    gf = _graphify_mcp_config()
    if gf:
        mcp["graphify"] = gf
    _write_json(path, config)
    return True


def configure_gemini() -> bool:
    """Add Graxia MCP server to Gemini config."""
    path = _config_path_gemini()
    config = _read_json(path)
    mcp = config.setdefault("mcpServers", {})
    mcp["graxia"] = GRAXIA_MCP_CONFIG
    gf = _graphify_mcp_config()
    if gf:
        mcp["graphify"] = gf
    _write_json(path, config)
    return True


def configure_opencode() -> bool:
    """Add Graxia MCP server to OpenCode config."""
    path = _config_path_opencode()
    config = _read_json(path)
    mcp = config.setdefault("mcp", {})
    servers = mcp.setdefault("servers", {})
    servers["graxia"] = GRAXIA_MCP_CONFIG
    gf = _graphify_mcp_config()
    if gf:
        servers["graphify"] = gf
    _write_json(path, config)
    return True


def configure_all_clients() -> dict[str, bool]:
    """Configure all detected MCP clients."""
    results = {}
    for name, fn in [
        ("claude_desktop", configure_claude_desktop),
        ("codex", configure_codex),
        ("gemini", configure_gemini),
        ("opencode", configure_opencode),
    ]:
        try:
            results[name] = fn()
        except Exception as e:
            print(f"  ! {name}: {e}")
            results[name] = False
    return results


def create_launcher_scripts() -> dict[str, Path]:
    """Create convenient launcher scripts in the user's home dir.

    Creates:
    - ~/graxia (or graxia.bat on Windows): launches web UI
    - ~/graxia-mcp: starts MCP server
    - ~/graxia-install: re-runs installer
    """
    home = Path.home()
    system = platform.system().lower()
    is_windows = system == "windows"
    ext = ".bat" if is_windows else ""
    scripts = {}

    # Main launcher — starts web UI
    web_launcher = home / f"graxia{ext}"
    if is_windows:
        web_launcher.write_text(
            f'@echo off\r\n'
            f'echo Starting Graxia Tool web UI...\r\n'
            f'"{sys.executable}" -m graxia_tool web\r\n'
            f'pause\r\n',
            encoding="utf-8",
        )
    else:
        web_launcher.write_text(
            f"#!/bin/sh\n"
            f"echo 'Starting Graxia Tool web UI...'\n"
            f"exec {sys.executable} -m graxia_tool web\n",
            encoding="utf-8",
        )
        web_launcher.chmod(0o755)
    scripts["web"] = web_launcher

    # MCP launcher
    mcp_launcher = home / f"graxia-mcp{ext}"
    if is_windows:
        mcp_launcher.write_text(
            f'@echo off\r\n"{sys.executable}" -m graxia_tool\r\n',
            encoding="utf-8",
        )
    else:
        mcp_launcher.write_text(
            f"#!/bin/sh\nexec {sys.executable} -m graxia_tool\n",
            encoding="utf-8",
        )
        mcp_launcher.chmod(0o755)
    scripts["mcp"] = mcp_launcher

    # Re-install launcher
    install_launcher = home / f"graxia-install{ext}"
    if is_windows:
        install_launcher.write_text(
            f'@echo off\r\n"{sys.executable}" -c "from graxia_tool.installer import install; install()"\r\n'
            f'pause\r\n',
            encoding="utf-8",
        )
    else:
        install_launcher.write_text(
            f"#!/bin/sh\nexec {sys.executable} -c 'from graxia_tool.installer import install; install()'\n",
            encoding="utf-8",
        )
        install_launcher.chmod(0o755)
    scripts["install"] = install_launcher

    return scripts


def create_desktop_shortcut_windows() -> Optional[Path]:
    """Create a desktop shortcut on Windows pointing to the web UI launcher."""
    if platform.system().lower() != "windows":
        return None
    try:
        import win32com.client  # type: ignore
    except ImportError:
        return None

    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return None

    web_launcher = Path.home() / "graxia.bat"
    if not web_launcher.exists():
        create_launcher_scripts()

    shortcut_path = desktop / "Graxia Tool.lnk"
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(web_launcher)
    shortcut.WorkingDirectory = str(Path.home())
    shortcut.IconLocation = "shell32.dll,13"
    shortcut.Description = "Graxia Tool — AI agent platform"
    shortcut.save()
    return shortcut_path


def install(
    ensure_model: str = "llama3.2",
    configure_clients: bool = True,
    create_shortcuts: bool = True,
    auto_pull: bool = True,
) -> dict:
    """Run the full Graxia install.

    Steps:
    1. Ensure Ollama is installed/running (skipped if no httpx)
    2. Pull default model
    3. Configure MCP clients
    4. Create launcher scripts
    5. (Windows) Create desktop shortcut

    Returns dict with overall result.
    """
    print("=" * 60)
    print("  Graxia Tool — One-line Installer")
    print("=" * 60)
    print()

    result = {
        "ollama": None,
        "openrouter": None,
        "clients": {},
        "scripts": {},
        "shortcut": None,
        "ready": False,
    }

    # Step 0: Check OpenRouter (preferred — free tier with auto-fallback chain)
    print("[0/5] Checking OpenRouter (free cloud LLM with auto-fallback)...")
    or_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if or_key:
        try:
            from .llm import OpenRouterClient
            or_client = OpenRouterClient(api_key=or_key)
            chain = list(or_client.fallback_chain)
            result["openrouter"] = {
                "configured": True,
                "fallback_chain": chain,
            }
            # Probe the primary model with a tiny request (best-effort, don't fail install)
            try:
                async def _probe():
                    try:
                        return await or_client.complete("ok", max_tokens=5)
                    finally:
                        await or_client.close()
                probe = asyncio.run(_probe())
                print(f"  [OK] OpenRouter ready: primary model = {probe.model}")
                result["openrouter"]["primary_model"] = probe.model
            except Exception as probe_err:
                err_short = str(probe_err)[:150]
                print(f"  ! OpenRouter key set, probe failed (rate-limited?): {err_short}")
                print(f"    (Will still work at runtime — fallback chain will try other models)")
                result["openrouter"]["probe_error"] = err_short
        except ImportError:
            print("  ! Could not import OpenRouterClient")
            result["openrouter"] = {"configured": bool(or_key), "error": "import_failed"}
    else:
        print("  No OPENROUTER_API_KEY in env -- OpenRouter disabled.")
        print("  Get a free key at https://openrouter.ai/keys and set:")
        print("    [System.Environment]::SetEnvironmentVariable('OPENROUTER_API_KEY', 'sk-or-v1-...', 'User')")
        result["openrouter"] = {"configured": False}

    # Step 1: Ensure Ollama (fallback for offline use)
    try:
        from .ollama_helper import ensure_ollama, is_ollama_installed, get_ollama_install_url
    except ImportError:
        try:
            from graxia_tool.ollama_helper import ensure_ollama, is_ollama_installed, get_ollama_install_url
        except ImportError:
            print("! Could not import ollama_helper. Skipping Ollama setup.")
            print("  Please install Ollama manually from: https://ollama.com")
            result["ollama"] = {"installed": False, "running": False, "model_available": False}
            return result

    print("[1/5] Checking Ollama (offline fallback)...")
    if not is_ollama_installed():
        print(f"  Ollama not found. Download from: {get_ollama_install_url()}")
        result["ollama"] = {"installed": False, "running": False, "model_available": False}
    else:
        try:
            ollama_status = asyncio.run(ensure_ollama(model=ensure_model, auto_pull=auto_pull))
            result["ollama"] = ollama_status
        except Exception as e:
            print(f"  ! Ollama setup error: {e}")
            result["ollama"] = {"error": str(e)}

    # Step 2: Configure MCP clients
    if configure_clients:
        print()
        print("[2/5] Configuring MCP clients...")
        try:
            result["clients"] = configure_all_clients()
            for name, ok in result["clients"].items():
                if ok:
                    print(f"  [OK] {name}")
                else:
                    print(f"  ! {name} (skipped)")
        except Exception as e:
            print(f"  ! Configure error: {e}")

    # Step 3: Create launcher scripts
    print()
    print("[3/5] Creating launcher scripts...")
    try:
        scripts = create_launcher_scripts()
        result["scripts"] = {k: str(v) for k, v in scripts.items()}
        for name, path in scripts.items():
            print(f"  [OK] {name}: {path}")
    except Exception as e:
        print(f"  ! Launcher error: {e}")

    # Step 4: Desktop shortcut (Windows only)
    if create_shortcuts and platform.system().lower() == "windows":
        print()
        print("[4/5] Creating desktop shortcut...")
        try:
            shortcut = create_desktop_shortcut_windows()
            if shortcut:
                result["shortcut"] = str(shortcut)
                print(f"  [OK] {shortcut}")
            else:
                print("  ! (skipped — pywin32 not installed or no desktop)")
        except Exception as e:
            print(f"  ! Shortcut error: {e}")
    else:
        print()
        print("[4/5] Skipping desktop shortcut (not Windows or disabled)")

    # Step 5: Summary
    print()
    print("[5/5] Summary")
    print("=" * 60)
    or_ready = result.get("openrouter", {}).get("configured", False) if isinstance(result.get("openrouter"), dict) else False
    ollama_ready = result.get("ollama", {}).get("ready", False) if isinstance(result.get("ollama"), dict) else False
    if or_ready:
        chain = result["openrouter"].get("fallback_chain", [])
        primary = result["openrouter"].get("primary_model", chain[0] if chain else "?")
        print(f"  LLM: OpenRouter (free, cloud, {len(chain)}-model fallback chain)")
        print(f"  Primary: {primary}")
        if len(chain) > 1:
            print(f"  Fallbacks: {len(chain) - 1} models")
        result["ready"] = True
    elif ollama_ready:
        print(f"  LLM: Ollama (local, offline)")
        result["ready"] = True
    else:
        print("  ! No LLM ready.")
        print("    Recommended: set OPENROUTER_API_KEY (free) — see [0/5] output above.")
        print("    Alternative: install Ollama from https://ollama.com")

    if result["ready"]:
        print()
        print("  Quick start:")
        print("    - Run 'graxia' to start the web UI")
        print("    - Run 'graxia-mcp' to start the MCP server")
        print("    - Configure Claude Desktop / Codex / Gemini / OpenCode / Cursor")
        print("      to use Graxia as an MCP server")
    print("=" * 60)

    return result


if __name__ == "__main__":
    install()
