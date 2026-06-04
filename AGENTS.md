# Agent Instructions

## MANDATORY STARTUP (before ANY work)

**STEP 1:** Call `auto_route` with the user's first message.
**STEP 2:** Call `memory_recall` to check past work.
**STEP 3:** Start working.

Example:
```
Tool call: auto_route(prompt="the user's message here")
Tool call: memory_recall(query="keywords from the task")
Then: do the actual work
```

## Rules

- Do what has been asked; nothing more, nothing less
- NEVER create files unless absolutely necessary
- ALWAYS read a file before editing it
- NEVER commit secrets or .env files
- Keep files under 500 lines

## Graxia Tools — Call These First

| When | Tool | Example |
|------|------|---------|
| **Start** | `auto_route` | route the user's prompt |
| **Start** | `memory_recall` | check if done before |
| **During** | `graxia_memory_ext(action="learn")` | learn from this task |
| **During** | `graxia_data(action="generate")` | generate test data |
| **After** | `memory_store` | store what you learned |
| **After** | `cost_report` | track token usage |

Full list: agent_run, agent_list, pipeline_run, multi_agent_run, system_status, auto_route, guard_check, memory_search, memory_recall, memory_store, rag_query, cache_get, cache_set, cost_report, context_cache_get, graxia_skills, graxia_vault, graxia_vault_auto, graxia_memory_ext, graxia_swarm, graxia_autonomous, graxia_data, graxia_optimize, governance_check, eval_run, context_cache_stats
