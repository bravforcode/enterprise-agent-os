# Agent Rules — Unified Config for All IDEs

## MANDATORY STARTUP

**BEFORE responding to ANY user message:**
1. `auto_route(prompt="user's message")` — route to best tools
2. `memory_recall(query="keywords")` — load past context
3. Work on task
4. `memory_store(...)` — save progress

## Tool Usage Rules

| Task | Tool | When |
|------|------|------|
| Any question | `auto_route` | ALWAYS first |
| Coding | `rag_query` | Search codebase |
| File ops | `lean-ctx_ctx_read` | Not raw read |
| Search | `lean-ctx_ctx_search` | Not raw grep |
| Features | `graxia_skills(action="load")` | Load skill |
| Debug | `skill_search(query="debug")` | Find skill |
| Complex work | `graxia_swarm` | Multi-agent |
| Memory | `graxia_memory_ext(action="recall")` | Check first |
| Review | `graxia_skills(action="load", skill_name="code-reviewer")` | Load review |
| Planning | `graxia_skills(action="load", skill_name="writing-plans")` | Load plan |

**NEVER** respond without calling tools first.

## Available Tools (19 essential)

| Tool | Purpose |
|------|---------|
| `auto_route` | Route to best tools/skills |
| `memory_recall` | Recall past memories |
| `memory_store` | Store new memories |
| `rag_query` | Search documents |
| `skill_search` | Search 403+ skills |
| `graxia_skills` | Load/manage skills |
| `graxia_vault` | Obsidian vault ops |
| `graxia_memory_ext` | Extended memory |
| `graxia_data` | Generate data |
| `graxia_optimize` | Token optimization |
| `system_status` | System health |
| `agent_list` | List agents |
| `guard_check` | Input/output guard |
| `cache_get/set` | Cache ops |
| `cost_report` | Cost tracking |
| `governance_check` | Safety + audit + content filter |
| `workflow_run` | Chain/parallel/router/orchestrator/evaluator |
| `hybrid_rag_search` | Hybrid search + rerank |
| `incremental_sync` | Sync + status + trigger |

## Skills

- 403+ skills from repos (awesome-copilot, AI-Research, openclaw)
- Location: `src/graxia_tool/skills/`
- Search: `skill_search(query="...")`
- Load: `graxia_skills(action="load", skill_name="...")`
