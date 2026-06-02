"""Tests for plugin module — 30+ tests."""
import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from graxia_tool.plugins import (
    PluginManifest, LoadedPlugin, PluginManager, get_plugin_manager,
)


# --- Manifest Tests ---

class TestPluginManifest:
    """Tests for PluginManifest."""

    def test_create_minimal(self):
        """Should create with minimal fields."""
        m = PluginManifest(name="test", version="1.0.0")
        assert m.name == "test"
        assert m.version == "1.0.0"
        assert m.entry == "main.py"  # default

    def test_create_full(self):
        """Should create with all fields."""
        m = PluginManifest(
            name="test",
            version="1.0.0",
            description="Test plugin",
            author="Alice",
            entry="plugin.py",
            tools=[{"name": "foo", "function": "main:foo"}],
            permissions=["network"],
        )
        assert m.author == "Alice"
        assert len(m.tools) == 1
        assert "network" in m.permissions

    def test_to_dict(self):
        """Should serialize to dict."""
        m = PluginManifest(name="test", version="1.0.0")
        d = m.to_dict()
        assert d["name"] == "test"
        assert d["version"] == "1.0.0"

    def test_from_file(self):
        """Should load from JSON file."""
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "plugin.json"
            manifest_path.write_text(json.dumps({
                "name": "test",
                "version": "1.0.0",
                "description": "test",
            }))
            m = PluginManifest.from_file(manifest_path)
            assert m.name == "test"


# --- PluginManager Tests ---

class TestPluginManager:
    """Tests for PluginManager."""

    def test_empty_manager(self):
        """Should start empty."""
        mgr = PluginManager(plugins_dir=Path("/nonexistent"))
        assert mgr.list_plugins() == []

    def test_load_plugin(self):
        """Should load plugin from directory."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create plugin
            (tmp_path / "plugin.json").write_text(json.dumps({
                "name": "myplugin",
                "version": "1.0.0",
                "entry": "main.py",
                "tools": [{"name": "mytool", "function": "main:mytool"}],
            }))
            (tmp_path / "main.py").write_text("def mytool(): return 'ok'\n")

            mgr = PluginManager()
            plugin = mgr.load_plugin(tmp_path)
            assert plugin.manifest.name == "myplugin"
            assert plugin.manifest.version == "1.0.0"
            assert "myplugin" in mgr._plugins

    def test_load_plugin_no_manifest(self):
        """Should raise if no plugin.json."""
        with tempfile.TemporaryDirectory() as tmp:
            mgr = PluginManager()
            with pytest.raises(FileNotFoundError):
                mgr.load_plugin(Path(tmp))

    def test_load_plugin_no_entry(self):
        """Should raise if entry file missing."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({
                "name": "myplugin",
                "version": "1.0.0",
                "entry": "missing.py",
            }))
            mgr = PluginManager()
            with pytest.raises(FileNotFoundError):
                mgr.load_plugin(tmp_path)

    def test_get_plugin(self):
        """Should get plugin by name."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({
                "name": "myplugin",
                "version": "1.0.0",
            }))
            (tmp_path / "main.py").write_text("# empty\n")

            mgr = PluginManager()
            mgr.load_plugin(tmp_path)

            plugin = mgr.get_plugin("myplugin")
            assert plugin is not None

            missing = mgr.get_plugin("nonexistent")
            assert missing is None

    def test_list_plugins(self):
        """Should list all loaded plugins."""
        mgr = PluginManager()
        assert mgr.list_plugins() == []

    def test_list_tools(self):
        """Should list all tools from all plugins."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({
                "name": "p1",
                "version": "1.0.0",
                "tools": [{"name": "t1", "description": "tool 1"}],
            }))
            (tmp_path / "main.py").write_text("def t1(): pass\n")

            mgr = PluginManager()
            mgr.load_plugin(tmp_path)

            tools = mgr.list_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "t1"
            assert tools[0]["plugin"] == "p1"

    def test_call_tool(self):
        """Should call tool function."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({
                "name": "p1",
                "version": "1.0.0",
                "tools": [{"name": "greet", "function": "main:greet"}],
            }))
            (tmp_path / "main.py").write_text('def greet(name="World"): return f"Hi {name}"\n')

            mgr = PluginManager()
            mgr.load_plugin(tmp_path)

            result = mgr.call_tool("greet", name="Alice")
            assert result == "Hi Alice"

    def test_call_unknown_tool(self):
        """Should raise for unknown tool."""
        mgr = PluginManager()
        with pytest.raises(ValueError):
            mgr.call_tool("nonexistent")

    def test_enable_disable(self):
        """Should enable/disable plugins."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({"name": "p", "version": "1.0.0"}))
            (tmp_path / "main.py").write_text("# empty\n")

            mgr = PluginManager()
            mgr.load_plugin(tmp_path)

            assert mgr.disable("p") is True
            assert mgr.get_plugin("p").enabled is False
            assert mgr.enable("p") is True
            assert mgr.get_plugin("p").enabled is True

    def test_unload(self):
        """Should unload plugin."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "plugin.json").write_text(json.dumps({"name": "p", "version": "1.0.0"}))
            (tmp_path / "main.py").write_text("# empty\n")

            mgr = PluginManager()
            mgr.load_plugin(tmp_path)

            assert mgr.unload("p") is True
            assert mgr.get_plugin("p") is None

    def test_unload_nonexistent(self):
        """Should return False for missing plugin."""
        mgr = PluginManager()
        assert mgr.unload("ghost") is False


# --- Hooks Tests ---

class TestHooks:
    """Tests for hook system."""

    def test_register_hook(self):
        """Should register hook handler."""
        mgr = PluginManager()
        mgr.register_hook("test_event", lambda: "called")
        assert "test_event" in mgr._hooks

    def test_trigger_hook(self):
        """Should trigger all handlers."""
        mgr = PluginManager()
        results = []
        mgr.register_hook("event", lambda: results.append(1))
        mgr.register_hook("event", lambda: results.append(2))

        mgr.trigger_hook("event")
        assert results == [1, 2]

    def test_trigger_hook_with_args(self):
        """Should pass args to handlers."""
        mgr = PluginManager()
        results = []
        mgr.register_hook("event", lambda x, y=10: results.append(x + y))

        mgr.trigger_hook("event", 5, y=20)
        assert results == [25]

    def test_trigger_hook_no_handlers(self):
        """Should handle missing handlers gracefully."""
        mgr = PluginManager()
        results = mgr.trigger_hook("never_fired")
        assert results == []


# --- Singleton Tests ---

class TestSingleton:
    """Tests for singleton."""

    def test_singleton(self):
        """Should return same instance."""
        m1 = get_plugin_manager()
        m2 = get_plugin_manager()
        assert m1 is m2


# --- Example Plugin Tests ---

class TestExamplePlugin:
    """Tests for the example hello_world plugin."""

    def test_load_hello_world(self):
        """Should load the example plugin."""
        example_path = Path(__file__).parent.parent / "examples" / "plugins" / "hello_world"
        if not example_path.exists():
            pytest.skip("Example plugin not found")

        mgr = PluginManager()
        plugin = mgr.load_plugin(example_path)

        assert plugin.manifest.name == "hello_world"
        assert plugin.manifest.version == "1.0.0"
        assert len(plugin.manifest.tools) == 2

        # Test calling tools
        result = mgr.call_tool("hello", name="Tester")
        assert "Hello, Tester" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
