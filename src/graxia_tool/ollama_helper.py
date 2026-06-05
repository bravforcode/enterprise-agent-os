"""Ollama helper — install, start, and manage local Ollama.

Provides zero-setup LLM access:
- No API key required
- Runs locally
- Free
- Offline

Usage:
    from graxia_tool.ollama_helper import ensure_ollama, get_default_model

    await ensure_ollama()  # Auto-install + start + pull model
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional


DEFAULT_MODEL = "llama3.2:1b"
OLLAMA_PORT = 11434
OLLAMA_URL = f"http://localhost:{OLLAMA_PORT}"


def is_ollama_installed() -> bool:
    """Check if Ollama binary is on PATH."""
    return shutil.which("ollama") is not None


def get_ollama_install_url() -> str:
    """Get the platform-specific Ollama download URL."""
    system = platform.system().lower()
    if system == "windows":
        return "https://ollama.com/download/OllamaSetup.exe"
    elif system == "darwin":
        return "https://ollama.com/download/Ollama.dmg"
    else:
        return "https://ollama.com/install.sh"


async def is_ollama_running(base_url: str = OLLAMA_URL) -> bool:
    """Check if Ollama server is running."""
    def _check():
        try:
            req = urllib.request.Request(f"{base_url}/api/tags")
            resp = urllib.request.urlopen(req, timeout=2)
            return resp.status == 200
        except Exception:
            return False
    return await asyncio.to_thread(_check)


async def wait_for_ollama(timeout_seconds: int = 30, base_url: str = OLLAMA_URL) -> bool:
    """Wait for Ollama server to become available."""
    start = time.time()
    while time.time() - start < timeout_seconds:
        if await is_ollama_running(base_url):
            return True
        await asyncio.sleep(1.0)
    return False


async def list_models(base_url: str = OLLAMA_URL) -> list[str]:
    """List available Ollama models."""
    def _list():
        try:
            req = urllib.request.Request(f"{base_url}/api/tags")
            resp = urllib.request.urlopen(req, timeout=5)
            data = _json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
    return await asyncio.to_thread(_list)


async def has_model(model: str, base_url: str = OLLAMA_URL) -> bool:
    """Check if a specific model is available."""
    models = await list_models(base_url)
    # Match name with or without tag
    return any(m == model or m.startswith(f"{model}:") for m in models)


async def pull_model(model: str, base_url: str = OLLAMA_URL, timeout: int = 600) -> bool:
    """Pull a model via Ollama API.

    Note: This requires ollama CLI to be running, since the
    pull API is stream-based. We use the CLI as a fallback.
    """
    if await has_model(model, base_url):
        return True

    # Try via API (non-streaming with long timeout)
    def _pull():
        try:
            data = _json.dumps({"name": model, "stream": False}).encode()
            req = urllib.request.Request(
                f"{base_url}/api/pull",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=timeout)
            return resp.status == 200
        except Exception:
            return False

    api_ok = await asyncio.to_thread(_pull)
    if api_ok:
        return await has_model(model, base_url)

    # Fallback: use ollama CLI
    if is_ollama_installed():
        try:
            result = subprocess.run(
                ["ollama", "pull", model],
                capture_output=True,
                timeout=timeout,
            )
            return result.returncode == 0
        except Exception:
            return False

    return False


def install_ollama() -> bool:
    """Install Ollama on the current platform.

    Returns True if install command was successful.
    """
    system = platform.system().lower()

    if is_ollama_installed():
        return True

    try:
        if system == "windows":
            # Windows: use winget if available, otherwise download installer
            if shutil.which("winget"):
                subprocess.run(
                    ["winget", "install", "Ollama.Ollama", "--accept-package-agreements"],
                    check=True,
                    timeout=300,
                )
            else:
                # Download and run installer
                import urllib.request
                installer = Path(os.getenv("TEMP", "/tmp")) / "OllamaSetup.exe"
                urllib.request.urlretrieve(get_ollama_install_url(), str(installer))
                subprocess.run([str(installer)], check=True, timeout=300)

        elif system == "darwin":
            # macOS: download and mount DMG
            if shutil.which("brew"):
                subprocess.run(["brew", "install", "ollama"], check=True, timeout=300)
            else:
                print("Please install Ollama from https://ollama.com/download/Ollama.dmg")
                return False

        else:
            # Linux: use install script
            subprocess.run(
                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                check=True,
                timeout=300,
            )

        return is_ollama_installed()
    except Exception as e:
        print(f"Auto-install failed: {e}")
        print(f"Please install Ollama manually from: {get_ollama_install_url()}")
        return False


def start_ollama() -> bool:
    """Start Ollama server in background."""
    if not is_ollama_installed():
        return False

    system = platform.system().lower()

    try:
        if system == "windows":
            # Windows: start ollama serve in background
            subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            # Unix: start in background
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        return True
    except Exception:
        return False


async def ensure_ollama(
    model: str = DEFAULT_MODEL,
    auto_install: bool = True,
    auto_start: bool = True,
    auto_pull: bool = True,
    base_url: str = OLLAMA_URL,
) -> dict[str, bool]:
    """Ensure Ollama is installed, running, and the model is available.

    Returns dict with status of each step:
        {
            "installed": bool,
            "running": bool,
            "model_available": bool,
            "ready": bool,  # all three
        }
    """
    status = {
        "installed": False,
        "running": False,
        "model_available": False,
        "ready": False,
    }

    # Step 1: Install
    if not is_ollama_installed():
        if not auto_install:
            status["ready"] = False
            return status
        print("Ollama not found. Installing...")
        if not install_ollama():
            print(f"Failed to install. Please install from: {get_ollama_install_url()}")
            return status
    status["installed"] = True

    # Step 2: Start
    if not await is_ollama_running(base_url):
        if not auto_start:
            status["ready"] = False
            return status
        print("Starting Ollama server...")
        start_ollama()
        if not await wait_for_ollama(timeout_seconds=30, base_url=base_url):
            print("Ollama failed to start within 30s")
            return status
    status["running"] = True

    # Step 3: Pull model
    if not await has_model(model, base_url):
        if not auto_pull:
            status["ready"] = False
            return status
        print(f"Pulling model '{model}' (this may take a few minutes)...")
        if not await pull_model(model, base_url):
            print(f"Failed to pull model '{model}'")
            return status
    status["model_available"] = True

    status["ready"] = all([
        status["installed"],
        status["running"],
        status["model_available"],
    ])

    if status["ready"]:
        print(f"✓ Ollama ready: {base_url} (model: {model})")

    return status


def get_quickstart_url() -> str:
    """Return URL to Ollama quickstart docs."""
    return "https://github.com/ollama/ollama/blob/main/docs/quickstart.md"


if __name__ == "__main__":
    # CLI: python -m graxia_tool.ollama_helper
    asyncio.run(ensure_ollama())
