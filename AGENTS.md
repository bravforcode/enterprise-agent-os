# Agent Instructions

<!-- lean-ctx -->
## lean-ctx

Prefer lean-ctx MCP tools over native equivalents for token savings.
Full rules: @LEAN-CTX.md
<!-- /lean-ctx -->

## Auto-Routing (MANDATORY)

Every prompt MUST be auto-routed before execution. The system has:

1. **AutoRouter** — `from graxia_tool.auto_router import AutoRouter`
   - Automatically selects skills, RAG technique, agent, model tier, MCP tools
   - Call `AutoRouter().route(prompt)` to get routing decision
   
2. **SessionMemory** — `from graxia_tool.session_memory import SessionMemory`
   - Remembers task outcomes, codebase knowledge, user preferences
   - Call `recall(query)` to find relevant past context
   - Call `remember_task(task)` after completing work

3. **ContextCache** — `from graxia_tool.context_cache import ContextCache`
   - Caches routing decisions and results
   - Call `get(prompt)` to check cache before re-computing

### Flow (follow this for EVERY interaction):

```
1. Check ContextCache for cached routing
2. If miss → run AutoRouter.route(prompt)
3. Load suggested skills via skill tool
4. Recall relevant memories from SessionMemory
5. Execute with selected agent/RAG/MCP
6. Store result in SessionMemory + ContextCache
```

### Skill Auto-Loading

Skills are in `.claude/skills/*/SKILL.md`. The `skill` tool auto-loads when triggers match.
Skills available: brainstorming, caveman, lean-ctx, systematic-debugging, rtk-tdd, 
web-search, mcp-builder, pdf, docx, pptx, xlsx, imagegen, and 80+ more.

## lean-ctx
Prefer lean-ctx MCP tools over native equivalents for token savings.

## RTK
All CLI commands must use `rtk` prefix.
