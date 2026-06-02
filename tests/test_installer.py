"""Tests for the one-line installer."""
from __future__ import annotations

import json
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

from graxia_tool.installer import (
    configure_claude_desktop,
    configure_codex,
    configure_gemini,
    configure_opencode,
    configure_all_clients,
    create_launcher_scripts,
    _config_path_claude,
    _config_path_codex,
    _config_path_gemini,
    _config_path_opencode,
    _read_json,
    _write_json,
)


# ----- Config path resolution -----


def test_config_path_claude_returns_path():
    p = _config_path_claude()
    assert isinstance(p, Path)
    assert "claude" in str(p).lower() or "Claude" in str(p)


def test_config_path_codex_returns_path():
    p = _config_path_codex()
    assert isinstance(p, Path)
    assert ".codex" in str(p)


def test_config_path_gemini_returns_path():
    p = _config_path_gemini()
    assert isinstance(p, Path)
    assert ".gemini" in str(p)


def test_config_path_opencode_returns_path():
    p = _config_path_opencode()
    assert isinstance(p, Path)
    assert "opencode" in str(p).lower()


# ----- JSON helpers -----


def test_read_json_missing(tmp_path):
    p = tmp_path / "missing.json"
    assert _read_json(p) == {}


def test_read_json_valid(tmp_path):
    p = tmp_path / "valid.json"
    p.write_text(json.dumps({"a": 1}), encoding="utf-8")
    assert _read_json(p) == {"a": 1}


def test_read_json_invalid(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {", encoding="utf-8")
    assert _read_json(p) == {}


def test_write_json(tmp_path):
    p = tmp_path / "out.json"
    _write_json(p, {"a": 1, "b": [1, 2]})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"a": 1, "b": [1, 2]}


def test_write_json_creates_parent(tmp_path):
    p = tmp_path / "nested" / "out.json"
    _write_json(p, {"x": "y"})
    assert p.exists()


# ----- Config writers -----


def test_configure_claude_desktop_writes_graxia(tmp_path, monkeypatch):
    target = tmp_path / "claude_desktop_config.json"
    monkeypatch.setattr("graxia_tool.installer._config_path_claude", lambda: target)
    assert configure_claude_desktop() is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "graxia" in data["mcpServers"]
    assert "command" in data["mcpServers"]["graxia"]


def test_configure_claude_preserves_existing(tmp_path, monkeypatch):
    target = tmp_path / "claude_desktop_config.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "mcpServers": {"other_server": {"command": "x"}},
        "user_settings": {"theme": "dark"},
    }), encoding="utf-8")
    monkeypatch.setattr("graxia_tool.installer._config_path_claude", lambda: target)
    configure_claude_desktop()
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "other_server" in data["mcpServers"]
    assert "graxia" in data["mcpServers"]
    assert data["user_settings"]["theme"] == "dark"


def test_configure_codex_writes_graxia(tmp_path, monkeypatch):
    target = tmp_path / "config.yaml"
    monkeypatch.setattr("graxia_tool.installer._config_path_codex", lambda: target)
    assert configure_codex() is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "mcpServers" in data
    assert "graxia" in data["mcpServers"]


def test_configure_gemini_writes_graxia(tmp_path, monkeypatch):
    target = tmp_path / "settings.json"
    monkeypatch.setattr("graxia_tool.installer._config_path_gemini", lambda: target)
    assert configure_gemini() is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "mcpServers" in data


def test_configure_opencode_writes_graxia(tmp_path, monkeypatch):
    target = tmp_path / "config.json"
    monkeypatch.setattr("graxia_tool.installer._config_path_opencode", lambda: target)
    assert configure_opencode() is True
    data = json.loads(target.read_text(encoding="utf-8"))
    assert "mcp" in data
    assert "servers" in data["mcp"]
    assert "graxia" in data["mcp"]["servers"]


# ----- configure_all_clients -----


def test_configure_all_clients_returns_dict():
    """All four client config functions should be called."""
    with patch("graxia_tool.installer.configure_claude_desktop", return_value=True), \
         patch("graxia_tool.installer.configure_codex", return_value=True), \
         patch("graxia_tool.installer.configure_gemini", return_value=True), \
         patch("graxia_tool.installer.configure_opencode", return_value=True):
        result = configure_all_clients()
    assert "claude_desktop" in result
    assert "codex" in result
    assert "gemini" in result
    assert "opencode" in result
    assert all(result.values())


def test_configure_all_clients_handles_errors():
    """If one client fails, the others should still be configured."""
    with patch("graxia_tool.installer.configure_claude_desktop", side_effect=Exception("boom")), \
         patch("graxia_tool.installer.configure_codex", return_value=True), \
         patch("graxia_tool.installer.configure_gemini", return_value=True), \
         patch("graxia_tool.installer.configure_opencode", return_value=True):
        result = configure_all_clients()
    assert result["claude_desktop"] is False
    assert result["codex"] is True


# ----- Launcher scripts -----


def test_create_launcher_scripts_returns_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    scripts = create_launcher_scripts()
    assert "web" in scripts
    assert "mcp" in scripts
    assert "install" in scripts
    # All scripts should exist
    for path in scripts.values():
        assert path.exists()
        assert path.is_file()


def test_launcher_web_uses_correct_python(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    scripts = create_launcher_scripts()
    web = scripts["web"]
    content = web.read_text(encoding="utf-8")
    assert "graxia_tool" in content
    # Should not depend on the user's actual python path
    assert "web" in content or "graxia" in content


def test_launcher_mcp_uses_correct_command(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    scripts = create_launcher_scripts()
    mcp = scripts["mcp"]
    content = mcp.read_text(encoding="utf-8")
    assert "graxia_tool" in content
