# Global AI Agent Control Plane — Architecture

## Overview

Modular, protocol-driven, local-first control plane for AI agents.
Compatible with Claude/Cursor/Codex/Gemini/OpenCode/local models.
Not vendor-locked.

## Layers

```
┌─────────────────────────────────────────────┐
│  IDE Layer (Claude/Codex/Gemini/OpenCode)   │
├─────────────────────────────────────────────┤
│  MCP Transport (stdio/pipe)                 │
├─────────────────────────────────────────────┤
│  Unified Tools (5 tools, 39 actions)        │
├─────────────────────────────────────────────┤
│  Control Plane (orchestrator)               │
│  ┌──────────┬──────────┬──────────┐         │
│  │ Memory   │ Skills   │ Cache    │         │
│  │ Layer    │ Registry │ Layer    │         │
│  ├──────────┼──────────┼──────────┤         │
│  │ Search   │ Security │ Cost     │         │
│  │ Engine   │ Gate     │ Optimizer│         │
│  ├──────────┼──────────┼──────────┤         │
│  │ Audit    │ File     │ Daemon   │         │
│  │ Trail    │ Watcher  │ Process  │         │
│  └──────────┴──────────┴──────────┘         │
├─────────────────────────────────────────────┤
│  Storage (SQLite WAL + FTS5 + pickle)       │
└─────────────────────────────────────────────┘
```

## Components

### 1. Daemon Process
- Single long-running process
- IPC via named pipe (Windows) / Unix socket
- Health check endpoint
- Auto-restart on failure

### 2. Memory Layer
- **Session memory**: Current conversation (in-memory)
- **Working memory**: Recent decisions (SQLite, TTL 1h)
- **Long-term memory**: Permanent knowledge (SQLite, no expiry)
- **Project memory**: Per-project context (SQLite, scoped)
- Dedup: content hash + semantic similarity (threshold 0.92)

### 3. Skill Registry
- SKILL.md + YAML frontmatter format
- Progressive disclosure: metadata → body → references
- Semantic versioning (semver)
- Auto-loading based on task context
- Trust levels: TRUSTED/VERIFIED/UNTRUSTED

### 4. Cache Layer
- Tool result caching (hash-based keys)
- Semantic caching (embedding similarity)
- TTL: 1h dynamic, 24h static
- LRU eviction + background cleanup

### 5. Search Engine
- BM25 (keyword) + Dense (vector) + Reranker
- Hybrid scoring: `w_bm25 * bm25 + w_vec * cosine + w_recency * decay`
- Configurable weights per query type

### 6. Security Gate
- Input validation (prompt injection detection)
- Content filtering (exfiltration, escalation)
- Audit trail (structured event log)
- Circuit breaker (failure_threshold=5)

### 7. Cost Optimizer
- Model routing by task complexity
- Token budget tracking
- Cache-first policy (skip LLM if cached)
- Cost ceiling per session

### 8. File Watcher
- Watch for file changes
- Auto-sync to memory/index
- Debounce (2s window)
- Trigger on `.sync-trigger` file

## Storage Schema

```sql
-- Memory
CREATE TABLE memory (
    id INTEGER PRIMARY KEY,
    tier TEXT NOT NULL,  -- session|working|longterm|project
    content TEXT NOT NULL,
    content_hash TEXT,
    embedding BLOB,
    metadata JSON,
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    project TEXT
);

-- Skills
CREATE TABLE skills (
    name TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    description TEXT,
    triggers JSON,
    category TEXT,
    trust_level TEXT,
    file_path TEXT,
    content_hash TEXT,
    updated_at TIMESTAMP
);

-- Cache
CREATE TABLE cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    embedding BLOB,
    ttl_seconds INTEGER,
    created_at TIMESTAMP,
    expires_at TIMESTAMP,
    hit_count INTEGER DEFAULT 0
);

-- Audit
CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    tool TEXT,
    action TEXT,
    args JSON,
    result_status TEXT,
    duration_ms INTEGER,
    tokens_used INTEGER,
    session_id TEXT
);

-- Cost
CREATE TABLE cost (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    model TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    session_id TEXT
);
```
