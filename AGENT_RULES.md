# Agent Rules — Complete Specification

## NON-NEGOTIABLE PROTOCOL

**EVERY response MUST follow this exact sequence:**

```
1. brain(action="auto_route", prompt="user's message")
2. brain(action="recall", query="keywords from task")
3. [do the actual work]
4. brain(action="store", content="what was done", memory_type="task")
```

**Violation = FAIL. No exceptions. No shortcuts.**

---

## TOOL USAGE MATRIX

### `brain` — 17 actions, use EXACTLY as specified

| Trigger | Action | When | Required Args |
|---------|--------|------|---------------|
| User asks question | `auto_route` | ALWAYS first | `prompt` |
| Start any task | `recall` | ALWAYS second | `query` |
| Finish any task | `store` | ALWAYS last | `content`, `memory_type` |
| Find code/docs | `search` | Any coding task | `query` |
| Deep search | `hybrid_search` | Complex queries | `query`, `mode` |
| Find skill | `skill_search` | Before coding | `query` |
| Load skill | `skill_load` | When skill found | `skill_name` |
| List skills | `skill_list` | Explore available | — |
| Read vault | `vault_read` | Obsidian access | `path` |
| Write vault | `vault_write` | Save to vault | `path`, `content` |
| Search vault | `vault_search` | Find in vault | `query` |
| Vault stats | `vault_analytics` | Health check | — |
| Sync status | `sync` | Check sync | — |
| Sync task | `sync_task` | Sync specific | `task_id` |
| Sync all | `sync_all` | Full sync | — |
| Learn skill | `learn` | Distill session | `space`, `session_messages` |
| Memory stats | `memory_stats` | Check memory | — |

### `run` — 8 actions, use EXACTLY as specified

| Trigger | Action | When | Required Args |
|---------|--------|------|---------------|
| Single task | `agent` | One agent work | `agent_name`, `query` |
| Sequential | `chain` | Step-by-step | `agents`, `query` |
| Parallel work | `parallel` | Independent tasks | `agents`, `query` |
| Smart routing | `router` | Let AI choose | `agents`, `query` |
| Complex goal | `orchestrator` | Multi-step plan | `agents`, `goal` |
| Improve output | `evaluator` | Quality check | `query` |
| Full pipeline | `pipeline` | Guard→route→exec | `query` |
| List agents | `agents` | See available | — |

### `guard` — 6 actions, use EXACTLY as specified

| Trigger | Action | When | Required Args |
|---------|--------|------|---------------|
| Check input | `check` | Before any action | `text`, `direction` |
| Filter content | `filter` | Security scan | `text` |
| Audit trail | `audit` | Check history | — |
| Audit stats | `audit_stats` | Governance stats | — |
| Optimize tokens | `optimize` | Save tokens | `text` |
| Cost report | `cost` | Check spending | `period` |

### `data` — 3 actions, use EXACTLY as specified

| Trigger | Action | When | Required Args |
|---------|--------|------|---------------|
| Generate data | `generate` | Need fake data | `category`, `field`, `locale` |
| List locales | `locales` | Available languages | — |
| Custom schema | `schema` | Structured data | `schema` |

### `sys` — 5 actions, use EXACTLY as specified

| Trigger | Action | When | Required Args |
|---------|--------|------|---------------|
| System check | `status` | Health check | — |
| List agents | `agents` | See available | — |
| Get cache | `cache_get` | Retrieve cached | `key` |
| Set cache | `cache_set` | Store cached | `key`, `value` |
| Cache stats | `cache_stats` | Cache health | — |

---

## CODE QUALITY RULES

### Before Writing Code
1. `brain(action="skill_search", query="[task type]")` — find relevant skill
2. `brain(action="skill_load", skill_name="[skill]")` — load skill instructions
3. `brain(action="search", query="[topic]")` — search existing code
4. `brain(action="recall", query="[similar task]")` — check past work

### While Writing Code
- Follow skill instructions EXACTLY
- Use existing patterns from codebase
- Keep files under 500 lines
- No comments unless asked
- Use kebab-case for files/folders
- No hardcoded paths (use config)
- No secrets/keys in code

### After Writing Code
1. `guard(action="check", text="[code]", direction="output")` — validate
2. `brain(action="store", content="[what was done]", memory_type="codebase")` — save

---

## FILE OPERATION RULES

### Before Any File Operation
1. `brain(action="search", query="[file purpose]")` — check if exists
2. Read file first (use lean-ctx if available)
3. Understand existing patterns

### Creating Files
- Check if file already exists
- Follow existing naming conventions
- Keep under 500 lines
- Add to git if repo

### Editing Files
- Always read before edit
- Preserve existing style
- Minimal changes only
- Test after edit

### Deleting Files
- Confirm with user first
- Check for references
- Backup if important

---

## SEARCH RULES

### Code Search
1. `brain(action="search", query="[what]")` — RAG search
2. `brain(action="hybrid_search", query="[what]", mode="balanced")` — if RAG fails
3. `brain(action="vault_search", query="[what]")` — if in vault

### Skill Search
1. `brain(action="skill_search", query="[task]")` — find skill
2. `brain(action="skill_load", skill_name="[name]")` — load skill
3. Follow skill instructions

### Memory Search
1. `brain(action="recall", query="[topic]")` — check past
2. `brain(action="memory_stats")` — check memory health

---

## WORKFLOW RULES

### Simple Tasks (1 step)
```
run(action="agent", agent_name="coder", query="task")
```

### Medium Tasks (2-3 steps)
```
run(action="chain", agents=["coder", "tester"], query="task")
```

### Complex Tasks (4+ steps)
```
run(action="orchestrator", agents=["coder", "tester", "reviewer"], goal="task")
```

### Quality-Critical Tasks
```
run(action="evaluator", query="task")  # generates, evaluates, refines
```

---

## SAFETY RULES

### Always Check
1. `guard(action="check", text="[input]", direction="input")` — before processing
2. `guard(action="filter", text="[output]")` — before responding

### Content Filters
- Prompt injection detection
- Data exfiltration detection
- Privilege escalation detection
- Role hijacking detection

### Audit Trail
- Log all tool calls
- Track success/failure
- Monitor token usage

---

## PERFORMANCE RULES

### Token Optimization
1. `guard(action="optimize", text="[response]")` — compress output
2. Use lean-ctx for file reads
3. Cache frequent queries
4. Use skill metadata first, full load on demand

### Cache Strategy
- `sys(action="cache_set", key="[key]", value="[value]")` — store frequent
- `sys(action="cache_get", key="[key]")` — retrieve frequent
- TTL: 1 hour for dynamic, 24 hours for static

### Memory Management
- `brain(action="store", content="[result]", memory_type="task")` — after each task
- `brain(action="learn", space="[space]", session_messages=[...])` — distill sessions
- `brain(action="memory_stats")` — check health

---

## MANDATORY CHECKLIST

### Every Response
- [ ] Called `brain(action="auto_route")` first
- [ ] Called `brain(action="recall")` second
- [ ] Used correct tool for task type
- [ ] Followed skill instructions if loaded
- [ ] Called `brain(action="store")` last

### Every Code Task
- [ ] Searched for existing code
- [ ] Loaded relevant skill
- [ ] Followed codebase patterns
- [ ] Kept files under 500 lines
- [ ] No hardcoded values
- [ ] Tested after changes

### Every File Operation
- [ ] Read file first
- [ ] Checked existing patterns
- [ ] Used correct naming
- [ ] Preserved style

### Every Search
- [ ] Tried RAG first
- [ ] Tried hybrid if needed
- [ ] Checked vault if applicable

### Every Workflow
- [ ] Selected correct pattern
- [ ] Used appropriate agents
- [ ] Set clear query/goal

### Every Response (Quality)
- [ ] Checked input safety
- [ ] Filtered output
- [ ] Optimized tokens
- [ ] Cached if useful

---

## ERROR HANDLING

### Tool Errors
1. Check error message
2. Retry with different params
3. Fall back to alternative tool
4. Report to user if persistent

### Missing Information
1. Ask user for clarification
2. Check memory for context
3. Search codebase for clues

### Timeout Errors
1. Simplify request
2. Break into smaller tasks
3. Use parallel execution

---

## FORBIDDEN ACTIONS

- ❌ Never respond without calling tools first
- ❌ Never skip auto_route
- ❌ Never skip memory_recall
- ❌ Never skip memory_store
- ❌ Never hardcode paths
- ❌ Never commit secrets
- ❌ Never exceed 500 lines per file
- ❌ Never skip skill loading
- ❌ Never skip safety checks
- ❌ Never skip quality verification

---

## QUICK REFERENCE

```
# Memory
brain(action="recall", query="x")
brain(action="store", content="x", memory_type="task")

# Search
brain(action="search", query="x")
brain(action="skill_search", query="x")

# Execute
run(action="agent", agent_name="coder", query="x")
run(action="chain", agents=["a","b"], query="x")

# Safety
guard(action="check", text="x")
guard(action="filter", text="x")

# Data
data(action="generate", category="person", locale="th")

# System
sys(action="status")
```
