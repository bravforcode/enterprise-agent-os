# Graxia Hub — Unified AI Agent OS Design

## Overview

Graxia Hub เป็น MCP server เดียวที่ครอบคลุมทุกอย่าง: agents, skills, RAG, memory, vault integration, auto-systems, token optimization — ใช้ได้กับทุก IDE

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Graxia Hub MCP Server                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Agents   │ │ Skills   │ │ RAG      │ │ Memory   │  │
│  │ (18)     │ │ (1390)   │ │ (12)     │ │ (3-layer)│  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐  │
│  │ Vault    │ │ Auto-    │ │ Cost     │ │ Token    │  │
│  │ Tools    │ │ Systems  │ │ Engine   │ │ Optimizer│  │
│  │ (9)      │ │ (12)     │ │ (5)      │ │ (3-layer)│  │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘  │
└─────────────────────────────────────────────────────────┘
         │              │              │
         ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Claude Code │ │ Codex       │ │ Gemini      │
│ (MCP stdio) │ │ (MCP stdio) │ │ (MCP stdio) │
└─────────────┘ └─────────────┘ └─────────────┘
         │              │              │
         ▼              ▼              ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Cursor      │ │ Windsurf    │ │ OpenCode    │
│ (MCP stdio) │ │ (MCP stdio) │ │ (MCP stdio) │
└─────────────┘ └─────────────┘ └─────────────┘
```

## Components

### 1. Unified MCP Server (35 tools)

**Existing 23 tools:**
agent_run, agent_list, pipeline_run, multi_agent_run, guard_check,
auto_route, memory_recall, memory_store, context_cache_get, context_cache_stats,
skills_list, vault_search, vault_read, web_search, web_fetch,
cost_estimate, cost_report, metrics_store, metrics_query,
audit_log, context_compact, governance_check

**New vault tools (from brain MCP):**
vault_write, vault_link, vault_tag, vault_moc, vault_tasks, vault_graph, vault_analytics

**New auto-system tools:**
vault_auto_link, vault_auto_classify, vault_auto_tag, vault_auto_clean, vault_optimize

### 2. Vault Integration

**Path**: `AGENT_OS_VAULT_PATH` or auto-detect `~/Documents/ObsidianVault/Second Brain/`

**Operations:**
- Read/Write notes (file system)
- Search (BM25 + TF-IDF scoring)
- Link/Tag (frontmatter manipulation)
- MOC generation
- Task extraction
- Graph analysis

### 3. Auto-systems Integration

12 auto-systems from vault, triggered via MCP tools:

| Tool | Script | Action |
|------|--------|--------|
| `vault_auto_link` | auto_linker.py + batch_linker.py | Fix orphaned files |
| `vault_auto_tag` | auto_tagger.py | Add tags |
| `vault_auto_classify` | auto_classifier.py | Classify into PARA |
| `vault_auto_clean` | auto_duplicate_finder.py + auto_consistency_checker.py | Find duplicates + broken links |
| `vault_optimize` | vault_optimizer.py + auto_master.py | Run all systems |

### 4. Unified Memory

**3 sources, 1 interface:**

```
SessionMemory (task outcomes)
  ↕ sync
ContextCache (routing decisions)
  ↕ sync
Vault Notes (knowledge, learning)
```

**Memory flow:**
1. Task completed → SessionMemory.store()
2. Auto-sync → create vault note in 03-Resources/
3. Next session → SessionMemory.recall() + vault_search()
4. Self-learning → analyze outcomes, update routing

### 5. Token Optimization Stack

| Layer | Tool | Savings |
|-------|------|---------|
| Shell | RTK prefix | 60-90% |
| File reads | lean-ctx modes | 60-99% |
| Thai | Thai Token Optimizer | 60-75% |
| Skills | Smart loader (BM25+MiniLM) | 70-80% |
| RAG | Auto-router | 50-70% |
| LLM | Cost engine (cache+dedup) | 80-95% |

**Combined: ~90% token reduction**

### 6. Self-learning

**Learning triggers:**
- Task failed → try fallback agent, store failure reason
- Skill useful → increase trust score
- Routing wrong → adjust patterns
- User corrected → store as preference

**Implementation:**
- SessionMemory tracks success/failure
- AutoRouter adjusts routing based on outcomes
- SkillRegistry updates trust scores
- Vault stores learning notes

## Config Files

### Claude Code (`~/.claude/settings.json`)
```json
{
  "mcpServers": {
    "graxia": {
      "command": "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "graxia_tool.mcp"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "AGENT_OS_VAULT_PATH": "C:/Users/menum/Documents/ObsidianVault/Second Brain"
      }
    }
  }
}
```

### Codex (`~/.codex/config.toml`)
```toml
[mcp_servers.graxia]
command = "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe"
args = ["-m", "graxia_tool.mcp"]
env = { PYTHONIOENCODING = "utf-8", AGENT_OS_VAULT_PATH = "C:/Users/menum/Documents/ObsidianVault/Second Brain" }
startup_timeout_sec = 90
```

### Gemini (`~/.gemini/settings.json`)
```json
{
  "mcpServers": {
    "graxia": {
      "command": "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "graxia_tool.mcp"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "AGENT_OS_VAULT_PATH": "C:/Users/menum/Documents/ObsidianVault/Second Brain"
      }
    }
  }
}
```

### OpenCode (`~/.config/opencode/config.json`)
```json
{
  "mcpServers": {
    "graxia": {
      "command": "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "graxia_tool.mcp"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "AGENT_OS_VAULT_PATH": "C:/Users/menum/Documents/ObsidianVault/Second Brain"
      }
    }
  }
}
```

### Cursor (`~/.cursor/mcp.json`)
```json
{
  "mcpServers": {
    "graxia": {
      "command": "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "graxia_tool.mcp"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "AGENT_OS_VAULT_PATH": "C:/Users/menum/Documents/ObsidianVault/Second Brain"
      }
    }
  }
}
```

### Windsurf (`~/.windsurf/mcp.json`)
```json
{
  "mcpServers": {
    "graxia": {
      "command": "C:/Users/menum/AppData/Local/Programs/Python/Python312/python.exe",
      "args": ["-m", "graxia_tool.mcp"],
      "env": {
        "PYTHONIOENCODING": "utf-8",
        "AGENT_OS_VAULT_PATH": "C:/Users/menum/Documents/ObsidianVault/Second Brain"
      }
    }
  }
}
```

## Obsidian Integration: Help or Hurt?

**Answer: HELP significantly**

Benefits:
1. **1,390 skills** — Graxia leverages vault's skill library
2. **Auto-systems** — vault maintenance runs automatically
3. **Knowledge base** — vault stores learning, decisions, patterns
4. **Templates** — standardized note creation
5. **Graph** — note relationships for context
6. **MOCs** — organized knowledge maps
7. **Memory sync** — task outcomes persist in vault

No downsides:
- Vault is read-only for Graxia (unless writing notes)
- Auto-systems are optional (trigger via MCP)
- No dependency on Obsidian app (file system access)

## Implementation Plan

### Phase 1: Vault Integration (2 hours)
1. Add vault tools to MCP server
2. Implement vault_read/write/search/link/tag
3. Test with Obsidian vault

### Phase 2: Auto-systems (2 hours)
1. Port auto-systems to Python
2. Add auto-system tools to MCP
3. Test auto_linker, auto_tagger, auto_classifier

### Phase 3: Unified Memory (1 hour)
1. Connect SessionMemory to vault
2. Implement memory sync
3. Test memory recall from vault

### Phase 4: Token Optimization (1 hour)
1. Integrate RTK + lean-ctx + TTO
2. Add token optimization tools
3. Test token savings

### Phase 5: Self-learning (1 hour)
1. Implement learning triggers
2. Add routing adjustment
3. Test self-improvement

### Phase 6: Config & Testing (1 hour)
1. Update all IDE configs
2. Test with Claude Code, Codex, Gemini, Cursor, Windsurf, OpenCode
3. Verify all 35 tools work

**Total: ~8 hours**
