# SPEC: Loose Coupling Architecture — Graxia Tool + Graxia OS

## Overview

Redesign `graxia_tool` package into 3 clear layers with strict dependency direction:
`tool/` → `os/` → `storage/` → `shared/`

## Current State

- 22 top-level files, 16 core files, 21 MCP files
- `pipeline.py` depends on 12 modules (tight coupling)
- `shared.helpers` (`_ok`, `_err`) imported by 8 MCP files
- No clear interface boundary

## Target Architecture

```
src/graxia_tool/
├── tool/          # MCP Interface Layer (Graxia Tool)
├── os/            # Core Logic Layer (Graxia OS)
├── storage/       # Persistence Layer
├── shared/        # Pure utilities (no business logic)
├── plugins.py     # Plugin loader
├── installer.py   # Installer
├── integrate.py   # Integration testing
├── ollama_helper.py
├── adapters_facade.py
├── cost_engine_facade.py
└── __main__.py
```

## Layer Responsibilities

### tool/ (MCP Interface)
- MCP protocol types (Tool, Result, Error)
- ToolRegistry
- 5 unified tool handlers (brain, run, guard, data, sys)
- Fast path optimization (lazy imports, pickle cache)
- Daemon management
- Delegates ALL business logic to os/

### os/ (Core Logic)
- All business logic, algorithms, agents
- Auth, config, models, logging, database
- Intent routing, model routing, context compression
- Cost tracking, token budgeting, prompt caching
- Approval flow, output validation, run logging
- Orchestration engine, governance, security
- Session memory, context cache, auto routing
- Pipeline orchestration
- LLM clients, 15 agent types, swarm, autonomous
- Faker, skills, learning, optimization, multi-agent
- RAG (12 techniques), memory, integrations, vault
- Cost engine, adapters, observability

### storage/ (Persistence)
- Storage backends (SQLite, Postgres, Qdrant, Pickle)
- Semantic cache + LRU + TTL
- Hybrid search (BM25 + recency)
- 4-tier memory, FTS5, dedup
- Skill registry + semver + trust
- Security validation + audit + circuit breaker
- Cost budget + routing + cache-first
- Persistent daemon

### shared/ (Utilities)
- `_ok`, `_err` (pure functions)
- BM25 scoring (pure functions)
- Zero business logic

## Dependency Rules

1. **tool/** depends on: os/, shared/
2. **os/** depends on: shared/, storage/
3. **storage/** depends on: shared/
4. **shared/** depends on: nothing (stdlib only)
5. **NO reverse dependencies** (os/ never imports from tool/)
6. **NO circular dependencies**

## Migration Steps

1. Create directory structure
2. Move files to new locations
3. Update all imports
4. Create __init__.py exports
5. Verify all tests pass
6. Commit

## Verification

- All 8/8 unified tool tests pass
- All 41/41 full suite tests pass
- No circular imports
- Import direction follows rules
