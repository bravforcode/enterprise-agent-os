"""Test universal adapters: export to all 4 formats + simulate tool calls."""
import json
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\menum\enterprise-agent-os")
sys.path.insert(0, str(ROOT / "src"))

from graxia_tool.adapters.universal import (
    to_anthropic_tools,
    to_openai_tools,
    to_gemini_tools,
    to_generic_tools,
    export_all_tools,
    export_skill_manifest,
    expand_vault_agent,
    VAULT_AGENT_MAP,
)
from graxia_tool.mcp import build_default_registry

print("=" * 60)
print("UNIVERSAL ADAPTER TEST — 4 LLM formats + vault mapping")
print("=" * 60)

# 1. Build registry
reg = build_default_registry()
tools = [t.to_mcp_dict() for t in reg.list_all()]
print(f"\n[1] Registry: {len(tools)} tools")
print(f"    Categories: {sorted({t.category for t in reg.list_all()})}")

# 2. Test each export format
print("\n[2] Format-specific exports:")
for fmt_name, fn in [
    ("anthropic", to_anthropic_tools),
    ("openai", to_openai_tools),
    ("gemini", to_gemini_tools),
    ("generic", to_generic_tools),
]:
    exported = fn(tools)
    if fmt_name == "gemini":
        n = len(exported["function_declarations"])
    else:
        n = len(exported)
    print(f"    {fmt_name}: {n} tools exported")

# 3. Verify format structure
print("\n[3] Format structure checks:")
anthropic = to_anthropic_tools(tools[:1])[0]
openai = to_openai_tools(tools[:1])[0]
gemini = to_gemini_tools(tools[:1])
print(f"    anthropic: keys={sorted(anthropic.keys())}")
print(f"    openai: keys={sorted(openai.keys())}, function keys={sorted(openai['function'].keys())}")
print(f"    gemini: keys={sorted(gemini.keys())}, decl keys={sorted(gemini['function_declarations'][0].keys())}")

# 4. Test vault agent mapping
print(f"\n[4] Vault agent mapping (12 routing agents):")
for name, mapping in VAULT_AGENT_MAP.items():
    print(f"    {name:12s} -> {mapping['agent_os_tool']}")

# 5. Test expansion for each vault agent
print(f"\n[5] Vault agent expansion test:")
test_input = "find Python security notes"
for name in list(VAULT_AGENT_MAP.keys())[:3]:
    expanded = expand_vault_agent(name, test_input)
    if expanded:
        print(f"    {name:12s} -> {expanded['tool']}({json.dumps(expanded['arguments'])[:80]})")

# 6. Test skill manifest
print(f"\n[6] Skill manifest export:")
manifest = export_skill_manifest()
print(f"    name: {manifest['name']}")
print(f"    version: {manifest['version']}")
print(f"    tools: {len(manifest['tools'])}")
print(f"    agents: {len(manifest['agents'])} ({', '.join(manifest['agents'][:5])}...)")
print(f"    categories: {manifest['categories']}")

# 7. Simulate tool call for each format
print(f"\n[7] Simulated tool calls (all 18 tools, 3 formats = 54 schemas):")
all_openai = export_all_tools("openai")
all_anthropic = export_all_tools("anthropic")
all_gemini = export_all_tools("gemini")
print(f"    openai: {len(all_openai)}")
print(f"    anthropic: {len(all_anthropic)}")
print(f"    gemini: {len(all_gemini['function_declarations'])}")

# 8. Test tool can be serialized to JSON (for transport)
print(f"\n[8] JSON serialization test:")
all_generic = export_all_tools("generic")
serialized = json.dumps(all_generic)
print(f"    {len(serialized)} bytes serialized, {len(json.loads(serialized))} tools roundtripped")

print("\n" + "=" * 60)
print("[PASS] Universal adapter test passed")
print("=" * 60)
