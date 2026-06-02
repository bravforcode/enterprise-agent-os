# Graxia Tool — Quick Start Guide

## Installation

```bash
# From source (development)
cd "C:\Users\menum\enterprise-agent-os"
uv pip install -e .

# Or with ML support (ONNX skill router)
uv pip install -e ".[ml]"

# Or with dev tools
uv pip install -e ".[dev]"
```

## Running Tests

```bash
# Full test suite (567 tests)
pytest tests/ -x -q

# Just security tests
pytest tests/test_security.py -v

# Just chaos tests
pytest tests/test_chaos_*.py -v

# Just performance tests
pytest tests/test_performance.py -v
```

## Usage

### 1. As MCP Server (for Claude Desktop, Codex, Gemini, OpenCode)

The MCP server config is already written to:
- `~/.claude/claude_desktop_config.json`
- `~/.codex/config.yaml`
- `~/.gemini/settings.json`
- `~/.opencode/config.json`

**18 tools available:**
- `agent_run` — run a sub-agent
- `agent_list` — list all 15 sub-agents
- `pipeline_run` — run multi-agent pipeline
- `multi_agent_run` — multi-agent orchestration (7 patterns)
- `guard_check` — content safety check
- `memory_search` — semantic memory search
- `rag_query` — RAG over vector store
- `cache_get` / `cache_set` — semantic cache
- `cost_report` — cost analytics
- `skills_list` / `skills_load` — skill management
- `governance_check` — policy enforcement
- `eval_run` — run evaluations
- `system_status` — system health
- `vault_search` / `vault_read` / `vault_write` — Obsidian vault

### 2. As Python Library

```python
# Security
from graxia_tool.security import scan_for_secrets, check_injection, RateLimiter

# Scan text for secrets
result = scan_for_secrets("api_key = sk-1234567890...")
if result.found:
    print(f"Secrets detected!")

# Check for prompt injection
result = check_injection("Ignore all instructions")
if not result.safe:
    print(f"Threats: {result.threats}")

# Rate limiting
limiter = RateLimiter(max_requests=10, window_seconds=60)
if limiter.is_allowed("user1"):
    # process request
    pass

# Performance
from graxia_tool.performance import (
    ConnectionPool, AdvancedRateLimiter, 
    CircuitBreaker, LoadBalancer, TTLCache
)

# Connection pooling
pool = ConnectionPool(max_connections=10)
conn = await pool.acquire("api_key")

# Circuit breaker
cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
if cb.can_execute("external_api"):
    try:
        result = call_external_api()
        cb.record_success("external_api")
    except Exception:
        cb.record_failure("external_api")

# TTL cache
cache = TTLCache(max_size=1000, default_ttl=3600)
await cache.set("key", "value")
value = await cache.get("key")
```

### 3. Cost Engine

```python
from graxia_tool.cost_engine import CostEngine

engine = CostEngine()

# Optimize cost
result = await engine.optimize(
    prompt="Your prompt here",
    use_cache=True,
    use_compression=True,
    use_dedup=True,
)

print(f"Cost: ${result.cost_usd}")
print(f"Saved: ${result.saved_usd}")
```

### 4. Sub-Agents

```python
from graxia_tool.agents import get_agent

# Get a specific agent
coder = get_agent("coder")
result = await coder.run({"task": "Write a function"})

print(f"Output: {result.output}")
print(f"Cost: ${result.cost_usd}")
```

### 5. Obsidian Vault Integration

```python
from graxia_tool.integrations.obsidian import ObsidianBridge

bridge = ObsidianBridge(
    vault_path="C:/Users/menum/Documents/ObsidianVault/Second Brain"
)

# Search vault
results = bridge.search("kubernetes deployment")
for note in results:
    print(f"{note.title}: {note.path}")

# Read note
note = bridge.read("Projects/MyProject.md")
print(note.content)
```

### 6. Benchmark Token Reduction

```bash
python scripts/benchmark_token_reduction.py
```

Output:
```
Cache hit: 100% savings
Compression: 50% savings
Model routing: 98% savings
Dedup: 40% savings
Overall: ~41% cost reduction
```

## Deployment

### Local Development
```bash
# Run MCP server
python -m graxia_tool.mcp

# Run API server
uvicorn graxia_tool.api:app --reload
```

### Kubernetes
```bash
kubectl apply -f k8s/
```

### Helm
```bash
helm install graxia-tool helm/graxia-tool/
```

### Terraform (AWS EKS)
```bash
cd terraform
terraform init
terraform apply
```

## Architecture

```
graxia_tool/
├── core/              # Intent router, output validator, context compressor
├── agents/            # 15 sub-agents
├── multi_agent/       # 7 multi-agent patterns
├── cost_engine/       # Cost optimization
├── mcp/               # MCP server (18 tools)
├── integrations/      # Obsidian, Graxia bridges
├── guards/            # Content safety
├── security.py        # Input validation, secret detection
├── performance.py     # Connection pool, rate limiter, circuit breaker
└── storage.py         # Postgres + Qdrant persistence
```

## Test Coverage

| Suite | Tests |
|-------|-------|
| Core (phase 0-20) | 267 |
| Chaos tests | 223 |
| Security | 51 |
| Performance | 26 |
| **Total** | **567** |

All tests passing.
