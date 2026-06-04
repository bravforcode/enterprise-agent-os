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

## Graxia MCP Tools (v0.5.0 — 45 tools, call via tool name)

| When | Tool | Args |
|------|------|------|
| **START** | `auto_route` | `prompt="user's message"` |
| **START** | `memory_recall` | `query="keywords"` |
| ALWAYS | `system_status` | (no args) |
| ALWAYS | `agent_list` | (no args) |
| ALWAYS | `agent_run` | `agent_name="coder", query="..."` |
| ALWAYS | `guard_check` | `text="...", direction="input"` |
| ALWAYS | `rag_query` | `query="...", top_k=5` |
| ALWAYS | `context_cache_get` | `prompt="..."` |
| DURING | `memory_search` | `query="...", layers=["..."]` |
| DURING | `memory_store` | `memory_type="task", content="...", outcome="success"` |
| DURING | `cache_get` | `key="..."` |
| DURING | `cache_set` | `key="...", value="...", ttl=3600` |
| DURING | `context_cache_stats` | (no args) |
| DURING | `graxia_skills` | `action="list"` |
| DURING | `skill_search` | `query="..."` |
| DURING | `skill_load` | `skill_name="..."` |
| DURING | `skill_detect` | `query="..."` |
| DURING | `skill_refresh` | (no args) |
| DURING | `graxia_vault` | `action="search", query="..."` |
| DURING | `graxia_vault` | `action="read", path="..."` |
| DURING | `graxia_vault` | `action="write", path="...", content="..."` |
| DURING | `graxia_vault` | `action="analytics"` |
| DURING | `graxia_vault_auto` | `action="auto_link"` |
| DURING | `graxia_vault_auto` | `action="auto_tag"` |
| DURING | `graxia_memory_ext` | `action="learn", space="x", messages=[...]` |
| DURING | `graxia_memory_ext` | `action="recall", space="x", query="..."` |
| DURING | `graxia_memory_ext` | `action="summarize", messages=[...]` |
| DURING | `graxia_memory_ext` | `action="rerank", query="...", candidates=[...]` |
| DURING | `graxia_memory_ext` | `action="categorize", content="..."` |
| DURING | `graxia_memory_ext` | `action="compress", content="..."` |
| DURING | `graxia_memory_ext` | `action="merge", memories=["..."]` |
| DURING | `graxia_swarm` | `action="init", topology="hierarchical", agents=["coder","tester"]` |
| DURING | `graxia_swarm` | `action="run", swarm_id="...", query="..."` |
| DURING | `graxia_swarm` | `action="status", swarm_id="..."` |
| DURING | `graxia_swarm` | `action="sona_record", intent="...", agent="...", success=true` |
| DURING | `graxia_swarm` | `action="sona_suggest", intent="..."` |
| DURING | `graxia_autonomous` | `action="plan", goal="...", constraints=["..."]` |
| DURING | `graxia_autonomous` | `action="run", goal="..."` |
| DURING | `graxia_autonomous` | `action="list_runs"` |
| DURING | `graxia_data` | `action="generate", category="person", field="first_name", locale="th", count=5` |
| DURING | `graxia_data` | `action="generate", category="phone", field="phone_number", locale="th", count=3` |
| DURING | `graxia_data` | `action="generate", category="location", field="city", locale="th", count=5` |
| DURING | `graxia_data` | `action="generate", category="finance", field="account", count=3` |
| DURING | `graxia_data` | `action="locales"` |
| DURING | `graxia_data` | `action="schema", schema={"name":"string.email","age":"int"}` |
| DURING | `graxia_optimize` | `action="report"` |
| DURING | `graxia_optimize` | `action="optimize", text="...", context="command"` |
| DURING | `eval_run` | `dataset_name="qa", agent_name="general"` |
| DURING | `governance_check` | `action="...", context={...}` |
| DURING | `governance_audit_query` | `query="..."` |
| DURING | `governance_audit_stats` | (no args) |
| DURING | `governance_content_filter` | `text="..."` |
| DURING | `workflow_chain` | `query="...", agents=[...]` |
| DURING | `workflow_parallel` | `query="...", agents=[...]` |
| DURING | `workflow_router` | `query="...", rules=[...]` |
| DURING | `workflow_orchestrator` | `query="...", pattern="..."` |
| DURING | `workflow_evaluator_optimizer` | `query="...", criteria=[...]` |
| DURING | `incremental_sync_task` | `task_id="..."` |
| DURING | `incremental_sync_all` | (no args) |
| DURING | `incremental_sync_status` | (no args) |
| DURING | `incremental_sync_trigger` | (no args) |
| DURING | `hybrid_rag_search` | `query="...", top_k=5` |
| DURING | `hybrid_rag_rerank` | `query="...", candidates=[...]` |
| DURING | `hybrid_rag_stats` | (no args) |
| DURING | `pipeline_run` | `query="...", pattern="..."` |
| DURING | `multi_agent_run` | `pattern="pipeline", query="..."` |
| AFTER | `cost_report` | `period="all"` |

## Skills

**425 skills** loaded from curated repos (awesome-copilot, AI-Research-SKILLs, openclaw, fast-agent, mcp-local-rag) plus 60+ built-in.

Progressive loading via `skill_search` (metadata first, full load on demand):
```
Tool call: skill_search(query="frontend")        # find matching skills (metadata)
Tool call: graxia_skills(action="list")          # list all loaded skills
Tool call: graxia_skills(action="load", skill_name="...")  # full load
```

**Skill locations:**
- `src/graxia_tool/skills/` — copilot-*, research-*, openclaw-*, rag-* (425 external)
- Built-in: brainstorming, caveman, lean-ctx, systematic-debugging, rtk-tdd, web-search, mcp-builder, pdf, docx, pptx, xlsx, imagegen, frontend-design, security-review, code-reviewer, deep-research, pair-programming, sparc-methodology, skill-creator, webapp-testing, and more

**Python ext modules** (`src/graxia_tool/ext/`):
- `memory_plus` — enhanced memory patterns
- `mcp_skillset` — MCP-based skill orchestration
- `fast_agent` — fast agent framework integration

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
