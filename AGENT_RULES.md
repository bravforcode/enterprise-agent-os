# Agent Rules — Unified Config for All IDEs

## MANDATORY STARTUP

**BEFORE responding to ANY user message:**
1. `brain(action="auto_route", prompt="user's message")` — route to best tools
2. `brain(action="recall", query="keywords")` — load past context
3. Work on task
4. `brain(action="store", content="...", memory_type="task")` — save progress

## 5 Tools, 39 Actions

### `brain` — All knowledge + memory (17 actions)
| Action | Purpose |
|--------|---------|
| `recall` | Search past memories |
| `store` | Store new memories |
| `search` | Search codebase (RAG) |
| `hybrid_search` | Hybrid BM25+vector search |
| `skill_search` | Search 403+ skills |
| `skill_load` | Load full skill content |
| `skill_list` | List loaded skills |
| `vault_search` | Search Obsidian vault |
| `vault_read` | Read vault note |
| `vault_write` | Write vault note |
| `vault_analytics` | Vault statistics |
| `sync` | Incremental sync status |
| `sync_task` | Sync specific task |
| `sync_all` | Sync all |
| `learn` | Distill session into skill |
| `memory_stats` | Memory statistics |
| `auto_route` | Route to best tools |

### `run` — Execute tasks + workflows (8 actions)
| Action | Purpose |
|--------|---------|
| `agent` | Run single agent |
| `chain` | Chain agents in sequence |
| `parallel` | Run agents in parallel |
| `router` | Route to best agent |
| `orchestrator` | Plan and execute |
| `evaluator` | Generate→evaluate→refine |
| `pipeline` | Guard→route→execute→validate |
| `agents` | List available agents |

### `guard` — Safety + quality (6 actions)
| Action | Purpose |
|--------|---------|
| `check` | Input/output guard |
| `filter` | Content filter |
| `audit` | Audit trail query |
| `audit_stats` | Governance statistics |
| `optimize` | Token optimization |
| `cost` | Cost report |

### `data` — Data generation (3 actions)
| Action | Purpose |
|--------|---------|
| `generate` | Generate fake data |
| `locales` | List available locales |
| `schema` | Generate from schema |

### `sys` — System + cache (5 actions)
| Action | Purpose |
|--------|---------|
| `status` | System health |
| `agents` | List available agents |
| `cache_get` | Get cached value |
| `cache_set` | Set cached value |
| `cache_stats` | Cache statistics |
