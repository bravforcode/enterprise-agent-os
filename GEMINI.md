## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## graxia

Graxia Tool is an AI agent platform with 26 MCP tools, 102 agents, and autonomous execution.

MCP Server: `python -m graxia_tool.mcp`
Tools: `graxia_memory_ext`, `graxia_swarm`, `graxia_autonomous`, `graxia_data`, `graxia_vault`, `graxia_vault_auto`, `graxia_skills`, `graxia_optimize`

### Startup Protocol (EVERY SESSION)
1. `auto_route` — route the user's prompt to optimal skills/RAG/agent/model
2. `memory_recall` — check if this task was done before
3. `context_cache_get` — check for cached routing decisions

### Task Execution
4. `graxia_memory_ext(action="learn")` — distill what you learned into skill files
5. `graxia_memory_ext(action="recall", query="...")` — find relevant past knowledge
6. `graxia_data(action="generate")` — generate test data (Thai locale available)
7. `graxia_swarm` — coordinate multiple agents for complex tasks
8. `graxia_autonomous` — plan and execute autonomous tasks

### After Task
9. `memory_store` — store the outcome (task type, success, what was learned)
10. `cache_set` — cache the routing decision
11. `cost_report` — track token usage
