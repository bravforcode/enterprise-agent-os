"""Plugin marketplace — load external plugins dynamically.

Plugin manifest format (plugin.json):
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "...",
  "author": "...",
  "entry": "main.py",
  "tools": [
    {
      "name": "my_tool",
      "description": "...",
      "function": "main:my_tool"
    }
  ]
}

Plugins can register:
- Tools (MCP-compatible)
- Agents (BaseSubAgent subclasses)
- Skills (SKILL.md content)
- Hooks (event handlers)
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class PluginManifest:
    """Plugin manifest from plugin.json."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    entry: str = "main.py"
    tools: list[dict] = field(default_factory=list)
    agents: list[dict] = field(default_factory=list)
    skills: list[dict] = field(default_factory=list)
    hooks: list[dict] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> "PluginManifest":
        """Load manifest from JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "entry": self.entry,
            "tools": self.tools,
            "agents": self.agents,
            "skills": self.skills,
            "hooks": self.hooks,
            "permissions": self.permissions,
        }


@dataclass
class LoadedPlugin:
    """A loaded plugin with its manifest and module."""
    manifest: PluginManifest
    module: Any
    path: Path
    enabled: bool = True

    def get_tool(self, name: str) -> Optional[Callable]:
        """Get tool function by name."""
        for tool in self.manifest.tools:
            if tool["name"] == name:
                func_name = tool.get("function", f"main:{name}")
                module_name, attr = func_name.split(":")
                return getattr(self.module, attr, None)
        return None


class PluginManager:
    """Manages loading and lifecycle of plugins."""

    def __init__(self, plugins_dir: Optional[Path] = None):
        self.plugins_dir = plugins_dir or Path("./plugins")
        self._plugins: dict[str, LoadedPlugin] = {}
        self._hooks: dict[str, list[Callable]] = {}

    def load_plugin(self, path: Path) -> LoadedPlugin:
        """Load a plugin from a directory containing plugin.json."""
        manifest_path = path / "plugin.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No plugin.json in {path}")

        manifest = PluginManifest.from_file(manifest_path)

        # Load entry module
        entry_path = path / manifest.entry
        if not entry_path.exists():
            raise FileNotFoundError(f"Entry {manifest.entry} not found in {path}")

        spec = importlib.util.spec_from_file_location(
            f"graxia_plugin_{manifest.name}",
            entry_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Failed to load spec for {entry_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)

        plugin = LoadedPlugin(manifest=manifest, module=module, path=path)
        self._plugins[manifest.name] = plugin

        # Register hooks
        for hook in manifest.hooks:
            event = hook.get("event", "")
            func_name = hook.get("function", "")
            if ":" in func_name:
                module_name, attr = func_name.split(":")
                func = getattr(module, attr, None)
                if func:
                    self._hooks.setdefault(event, []).append(func)

        return plugin

    def load_all(self) -> int:
        """Load all plugins from plugins_dir."""
        if not self.plugins_dir.exists():
            return 0

        count = 0
        for path in self.plugins_dir.iterdir():
            if path.is_dir() and (path / "plugin.json").exists():
                try:
                    self.load_plugin(path)
                    count += 1
                except Exception as e:
                    print(f"Failed to load plugin {path.name}: {e}")
        return count

    def get_plugin(self, name: str) -> Optional[LoadedPlugin]:
        """Get a loaded plugin by name."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[PluginManifest]:
        """List all loaded plugins."""
        return [p.manifest for p in self._plugins.values()]

    def list_tools(self) -> list[dict]:
        """List all tools from all plugins."""
        tools = []
        for plugin in self._plugins.values():
            for tool in plugin.manifest.tools:
                tools.append({
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "plugin": plugin.manifest.name,
                })
        return tools

    def call_tool(self, tool_name: str, *args, **kwargs) -> Any:
        """Call a tool by name."""
        for plugin in self._plugins.values():
            func = plugin.get_tool(tool_name)
            if func is not None:
                return func(*args, **kwargs)
        raise ValueError(f"Tool {tool_name} not found in any plugin")

    def register_hook(self, event: str, func: Callable) -> None:
        """Register a hook handler."""
        self._hooks.setdefault(event, []).append(func)

    def trigger_hook(self, event: str, *args, **kwargs) -> list[Any]:
        """Trigger all hooks for an event."""
        results = []
        for func in self._hooks.get(event, []):
            try:
                results.append(func(*args, **kwargs))
            except Exception as e:
                print(f"Hook error for {event}: {e}")
        return results

    def enable(self, name: str) -> bool:
        """Enable a plugin."""
        plugin = self._plugins.get(name)
        if plugin:
            plugin.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """Disable a plugin."""
        plugin = self._plugins.get(name)
        if plugin:
            plugin.enabled = False
            return True
        return False

    def unload(self, name: str) -> bool:
        """Unload a plugin."""
        if name in self._plugins:
            del self._plugins[name]
            return True
        return False


# Singleton
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    """Get global plugin manager."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
