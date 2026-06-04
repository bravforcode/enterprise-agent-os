# Agent Instructions

## Auto-Routing (MANDATORY)

Every prompt → `AutoRouter().route(prompt)` → skills, RAG, agent, model, tools.

Flow: Cache → Route → Skills → Recall → Execute → Store.

## Graxia Tools (USE EVERY SESSION)

**Every session MUST use Graxia MCP tools.** They are registered in your IDE config.

### Startup Protocol
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

## lean-ctx

Prefer lean-ctx MCP tools over native equivalents for token savings.

## RTK

All CLI commands must use `rtk` prefix.

## Skills

Skills auto-load via `skill` tool. Available: brainstorming, caveman, lean-ctx, systematic-debugging, rtk-tdd, web-search, mcp-builder, pdf, docx, pptx, xlsx, imagegen, and 80+ more.
