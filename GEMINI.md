## MANDATORY STARTUP

**STEP 1:** Call `auto_route` with the user's first message.
**STEP 2:** Call `memory_recall` to check past work.
**STEP 3:** Start working.

```
Tool call: auto_route(prompt="user's message")
Tool call: memory_recall(query="keywords from task")
Then: do the actual work
```

## Rules

- Do what has been asked; nothing more, nothing less
- NEVER create files unless absolutely necessary
- ALWAYS read a file before editing it
- NEVER commit secrets or .env files
- Keep files under 500 lines

## Graxia MCP Tools (26 tools, call via tool name)

| When | Tool | Args |
|------|------|------|
| **START** | `auto_route` | `prompt="user's message"` |
| **START** | `memory_recall` | `query="keywords"` |
| DURING | `graxia_memory_ext` | `action="learn", space="x", messages=[...]` |
| DURING | `graxia_memory_ext` | `action="recall", space="x", query="..."` |
| DURING | `graxia_memory_ext` | `action="summarize", messages=[...]` |
| DURING | `graxia_memory_ext` | `action="rerank", query="...", candidates=[...]` |
| DURING | `graxia_memory_ext` | `action="categorize", content="..."` |
| DURING | `graxia_memory_ext` | `action="compress", content="..."` |
| DURING | `graxia_memory_ext` | `action="merge", memories=["..."]` |
| DURING | `graxia_data` | `action="generate", category="person", field="first_name", locale="th", count=5` |
| DURING | `graxia_data` | `action="generate", category="phone", field="phone_number", locale="th", count=3` |
| DURING | `graxia_data` | `action="generate", category="location", field="city", locale="th", count=5` |
| DURING | `graxia_data` | `action="generate", category="finance", field="account", count=3` |
| DURING | `graxia_data` | `action="locales"` |
| DURING | `graxia_data` | `action="schema", schema={"name":"string.email","age":"int"}` |
| DURING | `graxia_swarm` | `action="init", topology="hierarchical", agents=["coder","tester"]` |
| DURING | `graxia_swarm` | `action="run", swarm_id="...", query="..."` |
| DURING | `graxia_swarm` | `action="status", swarm_id="..."` |
| DURING | `graxia_swarm` | `action="sona_record", intent="...", agent="...", success=true` |
| DURING | `graxia_swarm` | `action="sona_suggest", intent="..."` |
| DURING | `graxia_autonomous` | `action="plan", goal="...", constraints=["..."]` |
| DURING | `graxia_autonomous` | `action="run", goal="..."` |
| DURING | `graxia_autonomous` | `action="list_runs"` |
| DURING | `graxia_vault` | `action="search", query="..."` |
| DURING | `graxia_vault` | `action="read", path="..."` |
| DURING | `graxia_vault` | `action="write", path="...", content="..."` |
| DURING | `graxia_vault` | `action="analytics"` |
| DURING | `graxia_skills` | `action="list"` |
| DURING | `graxia_skills` | `action="load", skill_name="..."` |
| DURING | `graxia_optimize` | `action="report"` |
| DURING | `graxia_optimize` | `action="optimize", text="...", context="command"` |
| AFTER | `memory_store` | `memory_type="task", content="...", outcome="success", success=true` |
| AFTER | `memory_store` | `memory_type="preference", key="...", content="..."` |
| AFTER | `memory_store` | `memory_type="codebase", content="...", path="..."` |
| AFTER | `cache_set` | `key="...", value="...", ttl=3600` |
| AFTER | `cost_report` | `period="all"` |
| ALWAYS | `system_status` | (no args) |
| ALWAYS | `agent_list` | (no args) |
| ALWAYS | `agent_run` | `agent_name="coder", query="..."` |
| ALWAYS | `guard_check` | `text="...", direction="input"` |
| ALWAYS | `rag_query` | `query="...", top_k=5` |
| ALWAYS | `context_cache_get` | `prompt="..."` |

## Skills

Load skills when task matches:
```
Tool call: graxia_skills(action="list")
Tool call: graxia_skills(action="load", skill_name="brainstorming")
```

Available: brainstorming, caveman, lean-ctx, systematic-debugging, rtk-tdd, web-search, mcp-builder, pdf, docx, pptx, xlsx, imagegen, frontend-design, security-review, code-reviewer, deep-research, pair-programming, sparc-methodology, skill-creator, webapp-testing, and 60+ more.

## RAG

Query the knowledge base:
```
Tool call: rag_query(query="Python async patterns", top_k=5)
```

## Graphify

Query the codebase knowledge graph:
```
Tool call: graxia_vault(action="search", query="MCP tools")
```

Or use graphify CLI:
```
graphify query "where are MCP tools defined?"
graphify path "MCPServer" "ToolRegistry"
graphify explain "HybridLLMClient"
```
